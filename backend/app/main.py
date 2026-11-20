from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .db import Database
from .desks import desk_ids, get_desk, list_desk_configs, resolve_desk_id
from .ledger import (
    close_orphan_positions,
    ensure_desks,
    get_account,
    get_positions,
    maybe_unlock_t1,
    reset_account,
    reset_all_accounts,
    unlock_t1,
)
from .llm_ark import ArkError
from .market import MarketService
from .matching import MatchingEngine
from .schemas import (
    AccountOut,
    DeskSummaryOut,
    DesksOut,
    OrderCreate,
    OrderOut,
    PositionOut,
    QuoteOut,
    RuntimeOut,
    StrategyRunOut,
    StrategyRunsOut,
    StrategySchedulerOut,
    StrategySchedulersOut,
    WeekItem,
    WeeklyReportOut,
    WeeksOut,
)
from . import strategy as strategy_mod
from . import weekly as weekly_mod
from .strategy_scheduler import StrategyScheduler


def trading_instruments(config: dict[str, Any]) -> list[dict[str, Any]]:
    if str(config.get("trading_universe", "stocks")) == "stocks":
        return list(config.get("stocks") or [])
    return list(config.get("indices") or [])


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("daa")

ROOT = Path(__file__).resolve().parents[2]
CFG_PATH = ROOT / "config.yaml"
LOCAL_CFG = ROOT / "config.local.yaml"
ENV_FILE = ROOT / ".env"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def load_config() -> dict[str, Any]:
    _load_dotenv(ENV_FILE)
    with CFG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if LOCAL_CFG.exists():
        with LOCAL_CFG.open(encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        # shallow merge; nested ark/weekly/strategy override
        for k, v in local.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg


_raw_cfg = load_config()
db_path = ROOT / _raw_cfg["db_path"]
db = Database(db_path)

INSTRUMENTS = trading_instruments(_raw_cfg)
# MatchingEngine / 行情用交易池；周报仍用原始 indices
cfg = {
    **_raw_cfg,
    "indices": INSTRUMENTS,
    "weekly_indices": list(_raw_cfg.get("indices") or []),
}

DESK_IDS = desk_ids(cfg)
ensure_desks(db, float(cfg["initial_cash"]), DESK_IDS)


def _on_market_tick() -> None:
    result = maybe_unlock_t1(db)
    if result.get("unlocked"):
        log.info("T+1 auto-unlock trade_date=%s", result.get("trade_date"))


market = MarketService(
    db,
    INSTRUMENTS,
    poll_interval_sec=float(cfg["poll_interval_sec"]),
    degrade_age_sec=float(cfg["degrade_age_sec"]),
    halt_fail_count=int(cfg["halt_fail_count"]),
    halt_recover_success=int(cfg["halt_recover_success"]),
    force_session=bool(cfg.get("force_session", True)),
    source=str(cfg.get("market_source", "mock")),
    quote_kind=str(cfg.get("trading_universe", "stocks")),
    poll_only_in_session=bool(cfg.get("poll_only_in_session", True)),
    on_tick=_on_market_tick,
)
engine = MatchingEngine(db, market, cfg)

NAME_MAP = {i["symbol"]: i["name"] for i in INSTRUMENTS}

_auto = (cfg.get("strategy") or {}).get("auto") or {}
_schedulers: dict[str, StrategyScheduler] = {}
for _did in DESK_IDS:
    _schedulers[_did] = StrategyScheduler(
        desk_id=_did,
        enabled=bool(_auto.get("enabled", False)),
        interval_sec=int(_auto.get("interval_sec", 300)),
        only_in_session=bool(_auto.get("only_in_session", True)),
        run_fn=lambda desk=_did: strategy_mod.run_strategy_round(
            db=db, market=market, engine=engine, cfg=cfg, desk_id=desk
        ),
    )


def _resolve_desk_or_404(desk_id: Optional[str]) -> str:
    try:
        return resolve_desk_id(cfg, desk_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "DESK_NOT_FOUND", "message": f"未知策略台：{desk_id}"},
        ) from exc


def _account_out(desk_id: str) -> AccountOut:
    acct = get_account(db, desk_id)
    quotes_map = {q["symbol"]: q["last"] for q in market.list_quotes()}
    mkt = 0.0
    cost_open = 0.0
    for p in get_positions(db, desk_id):
        qty = int(p["qty"])
        cost = float(p["cost_basis"])
        cost_open += cost
        last = quotes_map.get(p["symbol"])
        if last is not None:
            mkt += float(last) * qty
    cash = float(acct["cash"])
    fees = float(acct["fees_total"])
    equity = cash + mkt
    initial = float(cfg["initial_cash"])
    pnl_unrealized = mkt - cost_open
    pnl_total = equity - initial
    pnl_realized = pnl_total - pnl_unrealized
    pnl_pct = (pnl_total / initial * 100.0) if initial else 0.0
    return AccountOut(
        desk_id=desk_id,
        cash=round(cash, 2),
        market_value=round(mkt, 2),
        fees_total=round(fees, 2),
        equity=round(equity, 2),
        initial_cash=round(initial, 2),
        pnl_total=round(pnl_total, 2),
        pnl_unrealized=round(pnl_unrealized, 2),
        pnl_realized=round(pnl_realized, 2),
        pnl_pct=round(pnl_pct, 4),
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    closed = close_orphan_positions(db, {i["symbol"] for i in INSTRUMENTS})
    if closed:
        log.warning("closed orphan positions outside trading pool: %s", ",".join(closed))
    market.start()
    if cfg.get("market_source") == "mock":
        market.set_demo_stale(16)
    for sched in _schedulers.values():
        sched.start()
    log.info(
        "market started source=%s ark_key=%s desks=%s auto=%s interval=%s",
        cfg.get("market_source"),
        "set" if os.environ.get("ARK_API_KEY") else "missing",
        ",".join(DESK_IDS),
        bool(_auto.get("enabled", False)),
        int(_auto.get("interval_sec", 300)),
    )
    yield
    for sched in _schedulers.values():
        sched.stop()
    market.stop()
    db.close()


app = FastAPI(title="大A 上证LLM模拟策略台", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5188",
        "http://localhost:5188",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runtime", response_model=RuntimeOut)
def runtime() -> RuntimeOut:
    return RuntimeOut(**market.snapshot_runtime())


@app.get("/api/quotes", response_model=list[QuoteOut])
def quotes() -> list[QuoteOut]:
    return [QuoteOut(**q) for q in market.list_quotes()]


@app.get("/api/desks", response_model=DesksOut)
def desks() -> DesksOut:
    summaries: list[DeskSummaryOut] = []
    for d in list_desk_configs(cfg):
        acct = _account_out(d["id"])
        summaries.append(
            DeskSummaryOut(
                id=d["id"],
                name=d["name"],
                model=d["model"],
                cash=acct.cash,
                market_value=acct.market_value,
                equity=acct.equity,
                initial_cash=acct.initial_cash,
                pnl_total=acct.pnl_total,
                pnl_pct=acct.pnl_pct,
                fees_total=acct.fees_total,
            )
        )
    leader_id: Optional[str] = None
    if summaries:
        leader = max(summaries, key=lambda s: (s.pnl_pct, s.equity, s.id))
        # 全平则不算领先
        if any(s.pnl_pct != summaries[0].pnl_pct for s in summaries):
            leader_id = leader.id
        elif any(s.equity != summaries[0].equity for s in summaries):
            leader_id = leader.id
    return DesksOut(desks=summaries, leader_id=leader_id)


@app.post("/api/desks/reset-all", response_model=DesksOut)
def desks_reset_all() -> DesksOut:
    reset_all_accounts(db, float(cfg["initial_cash"]), DESK_IDS)
    return desks()


@app.get("/api/account", response_model=AccountOut)
def account(desk_id: Optional[str] = Query(None)) -> AccountOut:
    did = _resolve_desk_or_404(desk_id)
    return _account_out(did)


@app.get("/api/positions", response_model=list[PositionOut])
def positions(desk_id: Optional[str] = Query(None)) -> list[PositionOut]:
    did = _resolve_desk_or_404(desk_id)
    quotes_map = {q["symbol"]: q["last"] for q in market.list_quotes()}
    out: list[PositionOut] = []
    for p in get_positions(db, did):
        last = float(quotes_map.get(p["symbol"], 0.0) or 0.0)
        qty = int(p["qty"])
        cost = float(p["cost_basis"])
        avg = (cost / qty) if qty else 0.0
        mkt_value = last * qty
        pnl_u = mkt_value - cost
        pnl_pct = (pnl_u / cost * 100.0) if cost else 0.0
        out.append(
            PositionOut(
                symbol=p["symbol"],
                name=NAME_MAP.get(p["symbol"], p["symbol"]),
                qty=qty,
                qty_sellable=int(p["qty_sellable"]),
                cost=round(cost, 2),
                avg_cost=round(avg, 4),
                last=round(last, 4),
                mkt_value=round(mkt_value, 2),
                pnl_unrealized=round(pnl_u, 2),
                pnl_pct=round(pnl_pct, 4),
            )
        )
    return out


@app.get("/api/orders", response_model=list[OrderOut])
def orders(
    limit: int = Query(50, ge=1, le=500),
    desk_id: Optional[str] = Query(None),
) -> list[OrderOut]:
    if desk_id:
        did = _resolve_desk_or_404(desk_id)
        return [OrderOut(**o) for o in engine.list_orders(limit=limit, desk_id=did)]
    return [OrderOut(**o) for o in engine.list_orders(limit=limit)]


@app.post("/api/orders", response_model=OrderOut)
def place_order(body: OrderCreate, desk_id: Optional[str] = Query(None)) -> OrderOut:
    did = _resolve_desk_or_404(desk_id)
    row = engine.place(
        symbol=body.symbol,
        side=body.side,
        qty=body.qty,
        order_type=body.type,
        limit=body.limit,
        desk_id=did,
    )
    return OrderOut(**{k: v for k, v in row.items() if k != "reject_code"})


@app.post("/api/account/reset", response_model=AccountOut)
def account_reset(desk_id: Optional[str] = Query(None)) -> AccountOut:
    did = _resolve_desk_or_404(desk_id)
    reset_account(db, float(cfg["initial_cash"]), did)
    return account(did)


@app.post("/api/dev/unlock-t1")
def dev_unlock_t1(desk_id: Optional[str] = Query(None)) -> dict[str, str]:
    """手动强制解锁（调试用）；日常由交易日 09:30 自动解锁。"""
    if desk_id:
        unlock_t1(db, _resolve_desk_or_404(desk_id))
    else:
        unlock_t1(db)
    return {"status": "ok"}


@app.post("/api/dev/stale")
def dev_stale(seconds: float = 14) -> RuntimeOut:
    market.set_demo_stale(seconds)
    return runtime()


@app.post("/api/dev/refresh")
def dev_refresh() -> RuntimeOut:
    market.demo_stale_sec = 0
    market.refresh_once()
    return runtime()


# ——— LLM 策略一轮 ———


@app.get("/api/strategy/scheduler", response_model=StrategySchedulersOut)
def strategy_scheduler(desk_id: Optional[str] = Query(None)) -> StrategySchedulersOut:
    if desk_id:
        did = _resolve_desk_or_404(desk_id)
        sched = _schedulers.get(did)
        if sched is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "DESK_NOT_FOUND", "message": f"未知策略台：{did}"},
            )
        return StrategySchedulersOut(schedulers=[StrategySchedulerOut(**sched.status().__dict__)])
    return StrategySchedulersOut(
        schedulers=[StrategySchedulerOut(**s.status().__dict__) for s in _schedulers.values()]
    )


@app.get("/api/strategy/latest", response_model=StrategyRunOut)
def strategy_latest(desk_id: Optional[str] = Query(None)) -> StrategyRunOut:
    if desk_id:
        did = _resolve_desk_or_404(desk_id)
        row = strategy_mod.latest_run(db, did)
    else:
        row = strategy_mod.latest_run(db)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "尚无策略运行记录"})
    # 补 desk_name
    try:
        desk = get_desk(cfg, row.get("desk_id") or DESK_IDS[0])
        row["desk_name"] = desk["name"]
    except KeyError:
        pass
    return StrategyRunOut(**row)


@app.get("/api/strategy/runs", response_model=StrategyRunsOut)
def strategy_runs(
    limit: int = Query(50, ge=1, le=200),
    desk_id: Optional[str] = Query(None),
) -> StrategyRunsOut:
    did = _resolve_desk_or_404(desk_id) if desk_id else None
    rows = strategy_mod.list_runs(db, limit=limit, desk_id=did)
    name_map = {d["id"]: d["name"] for d in list_desk_configs(cfg)}
    for r in rows:
        r["desk_name"] = name_map.get(r.get("desk_id", ""), r.get("desk_name") or "")
    return StrategyRunsOut(runs=[StrategyRunOut(**r) for r in rows])


@app.get("/api/strategy/runs/{run_id}", response_model=StrategyRunOut)
def strategy_run_detail(run_id: int) -> StrategyRunOut:
    row = strategy_mod.get_run(db, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"无策略记录 #{run_id}"})
    try:
        desk = get_desk(cfg, row.get("desk_id") or DESK_IDS[0])
        row["desk_name"] = desk["name"]
    except KeyError:
        pass
    return StrategyRunOut(**row)


@app.post("/api/strategy/run", response_model=StrategyRunOut)
def strategy_run(desk_id: Optional[str] = Query(None)) -> StrategyRunOut:
    did = _resolve_desk_or_404(desk_id)
    try:
        row = strategy_mod.run_strategy_round(
            db=db, market=market, engine=engine, cfg=cfg, desk_id=did
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_CONFIG", "message": str(exc)}) from exc
    except ArkError as exc:
        status = 400 if exc.code == "ARK_KEY_MISSING" else 502
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc
    return StrategyRunOut(**row)


# ——— 2026 周报 ———


@app.get("/api/weekly/weeks", response_model=WeeksOut)
def weekly_weeks() -> WeeksOut:
    year = int(cfg.get("weekly", {}).get("year", 2026))
    existing = weekly_mod.existing_week_keys(db)
    weeks = [
        WeekItem(
            week_key=w["week_key"],
            week_start=w["week_start"],
            week_end=w["week_end"],
            has_report=w["week_key"] in existing,
        )
        for w in weekly_mod.list_weeks(year)
    ]
    return WeeksOut(year=year, weeks=weeks)


@app.get("/api/weekly/reports/{week_key}", response_model=WeeklyReportOut)
def weekly_get(week_key: str) -> WeeklyReportOut:
    row = weekly_mod.get_report(db, week_key)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"尚报告：{week_key}"})
    return WeeklyReportOut(**row)


@app.post("/api/weekly/reports/{week_key}", response_model=WeeklyReportOut)
def weekly_generate(week_key: str, force: bool = Query(False)) -> WeeklyReportOut:
    try:
        row = weekly_mod.generate_or_get(db, cfg, week_key, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_WEEK", "message": str(exc)}) from exc
    except ArkError as exc:
        status = 400 if exc.code == "ARK_KEY_MISSING" else 502
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc
    return WeeklyReportOut(**row)
