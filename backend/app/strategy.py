from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from .calendar import now_cn
from .db import Database
from .desks import get_desk, list_desk_configs, resolve_desk_id
from .ledger import DEFAULT_DESK_ID, get_account, get_positions
from .llm_ark import ArkError, generate_strategy_signals
from .market import MarketService
from .matching import MatchingEngine

log = logging.getLogger("daa.strategy")


def _trading_instruments(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    kind = str(cfg.get("trading_universe", "stocks"))
    if kind == "stocks":
        return list(cfg.get("stocks") or [])
    return list(cfg.get("indices") or [])


def _desk_equity_snapshot(
    db: Database,
    desk_id: str,
    quote_map: dict[str, Any],
    initial_cash: float,
) -> dict[str, Any]:
    acct = get_account(db, desk_id)
    positions = get_positions(db, desk_id)
    cash = float(acct["cash"])
    mkt = 0.0
    for p in positions:
        last = quote_map.get(p["symbol"], {}).get("last")
        if last is not None:
            mkt += float(last) * int(p["qty"])
    equity = cash + mkt
    pnl_total = equity - initial_cash
    pnl_pct = (pnl_total / initial_cash * 100.0) if initial_cash else 0.0
    return {
        "desk_id": desk_id,
        "cash": cash,
        "market_value": mkt,
        "equity": equity,
        "pnl_total": pnl_total,
        "pnl_pct": pnl_pct,
        "position_count": len(positions),
    }


def _competition_text(
    *,
    cfg: dict[str, Any],
    db: Database,
    quote_map: dict[str, Any],
    self_desk_id: str,
) -> str:
    """生成各策略台收益进度文案，供提示词注入竞争意识。"""
    initial = float(cfg.get("initial_cash") or 0.0)
    rows: list[dict[str, Any]] = []
    for d in list_desk_configs(cfg):
        snap = _desk_equity_snapshot(db, d["id"], quote_map, initial)
        snap["name"] = d["name"]
        snap["model"] = d["model"]
        snap["is_self"] = d["id"] == self_desk_id
        rows.append(snap)
    if not rows:
        return ""
    rows.sort(key=lambda r: (r["pnl_pct"], r["equity"]), reverse=True)
    leader_pct = float(rows[0]["pnl_pct"])
    lines: list[str] = []
    for i, r in enumerate(rows, start=1):
        tag = "【你方】" if r["is_self"] else "【对手】"
        gap = float(r["pnl_pct"]) - leader_pct
        if i == 1 and (len(rows) == 1 or float(rows[1]["pnl_pct"]) < leader_pct):
            rank = "领先"
        elif abs(gap) < 1e-9:
            rank = "并列领先" if i == 1 else "胶着"
        else:
            rank = f"落后 {abs(gap):.2f}pct"
        lines.append(
            f"{i}. {tag}{r['name']}({r['model']}) "
            f"equity={r['equity']:.2f} cash={r['cash']:.2f} mkt={r['market_value']:.2f} "
            f"pnl={r['pnl_total']:+.2f} ({r['pnl_pct']:+.2f}%) "
            f"持仓数={r['position_count']} · {rank}"
        )
    self_row = next((r for r in rows if r["is_self"]), rows[0])
    if len(rows) >= 2:
        leader = rows[0]
        if self_row["desk_id"] == leader["desk_id"] and float(rows[1]["pnl_pct"]) < float(
            leader["pnl_pct"]
        ):
            stance = (
                f"你方当前领先，对第二名优势 "
                f"{float(leader['pnl_pct']) - float(rows[1]['pnl_pct']):.2f}pct；"
                "本轮优先守优，避免无谓回撤。"
            )
        elif abs(float(self_row["pnl_pct"]) - float(leader["pnl_pct"])) < 1e-9:
            stance = "你方与对手收益胶着；本轮在规则内争取微小优势，勿情绪化加仓。"
        else:
            stance = (
                f"你方落后领先方 "
                f"{float(leader['pnl_pct']) - float(self_row['pnl_pct']):.2f}pct；"
                "在非退潮前提下积极寻找高质量机会，禁止违规追赶。"
            )
        lines.append(f"竞赛结论：{stance}")
    return "\n".join(lines)


def _parse_json_payload(text: str) -> dict[str, Any]:
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ArkError("ARK_BAD_JSON", "模型未返回可解析 JSON") from None
        data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ArkError("ARK_BAD_JSON", "模型 JSON 根节点须为对象")
    return data


def run_strategy_round(
    *,
    db: Database,
    market: MarketService,
    engine: MatchingEngine,
    cfg: dict[str, Any],
    desk_id: str | None = None,
) -> dict[str, Any]:
    """一键：刷新行情 → LLM 结构化信号 → 校验 → 模拟下单。仅本地模拟。"""
    ts = now_cn().isoformat(timespec="seconds")
    did = resolve_desk_id(cfg, desk_id)
    desk = get_desk(cfg, did)
    instruments = _trading_instruments(cfg)
    if not instruments:
        raise ValueError("交易池为空：请在 config.yaml 配置 stocks")

    market.refresh_once()
    quotes = market.list_quotes()
    quote_map = {q["symbol"]: q for q in quotes}
    acct = get_account(db, did)
    positions = get_positions(db, did)
    pos_map = {p["symbol"]: p for p in positions}

    cash = float(acct["cash"])
    mkt = 0.0
    for p in positions:
        last = quote_map.get(p["symbol"], {}).get("last")
        if last is not None:
            mkt += float(last) * int(p["qty"])
    equity = cash + mkt

    strat = cfg.get("strategy") or {}
    max_signals = int(strat.get("max_signals", 5))
    max_buy_pct = float(strat.get("max_buy_pct_equity", 0.15))
    lot = int(cfg["lot_size"])
    model = str(desk["model"])
    base_url = str(desk["base_url"])
    timeout_sec = float(desk["timeout_sec"])

    pool_text = "\n".join(
        f"- {i['symbol']} {i['name']} last={quote_map.get(i['symbol'], {}).get('last', 'N/A')} "
        f"pct={quote_map.get(i['symbol'], {}).get('pct_chg', 'N/A')}"
        for i in instruments
    )
    pos_text = (
        "\n".join(
            (
                f"- {p['symbol']} qty={p['qty']} sellable={p['qty_sellable']} "
                f"cost={p['cost_basis']}"
                + (
                    "（可卖，空仓观望时必须 sell）"
                    if int(p["qty_sellable"]) >= lot
                    else "（T+1 不可卖）"
                )
            )
            for p in positions
        )
        or "（空仓）"
    )
    competition_text = _competition_text(
        cfg=cfg, db=db, quote_map=quote_map, self_desk_id=did
    )

    rules_profile = str(desk.get("rules_profile") or "strategist")
    llm_raw = generate_strategy_signals(
        base_url=base_url,
        model=model,
        timeout_sec=timeout_sec,
        temperature=float(strat.get("temperature", 0.2)),
        pool_text=pool_text,
        cash=cash,
        equity=equity,
        positions_text=pos_text,
        lot_size=lot,
        max_signals=max_signals,
        desk_name=str(desk["name"]),
        competition_text=competition_text,
        rules_profile=rules_profile,
    )
    # LLM 耗时可能让行情超龄；下单前再刷一次，避免误入降级拒单
    market.refresh_once()
    quotes = market.list_quotes()
    quote_map = {q["symbol"]: q for q in quotes}

    payload = _parse_json_payload(llm_raw)
    thesis = str(payload.get("thesis") or "").strip()
    analysis_raw = payload.get("analysis")
    analysis: dict[str, str] = {}
    analysis_keys = (
        "emotion_cycle",
        "tape_metrics",
        "theme",
        "mode",
        "position_rule",
        "triggers",
        "risks",
    )
    if isinstance(analysis_raw, dict):
        for key in analysis_keys:
            analysis[key] = str(analysis_raw.get(key) or "").strip()
    else:
        for key in analysis_keys:
            analysis[key] = ""
    if not thesis and analysis.get("emotion_cycle"):
        thesis = analysis["emotion_cycle"]
    disclaimer = str(payload.get("disclaimer") or "").strip()
    if "仅思路推演" not in disclaimer:
        disclaimer = "【仅思路推演，不构成投资建议】· 仅本地模拟 · 非投资建议"
    # 买入拦截：策略师沿用「空仓观望或退潮」；角色台只拦 mode=空仓观望（哲学差异交给各自规则）
    mode = analysis.get("mode", "")
    cycle = analysis.get("emotion_cycle", "")
    if rules_profile == "strategist":
        block_new_buys = mode == "空仓观望" or "退潮" in cycle
    else:
        block_new_buys = mode == "空仓观望"
    raw_signals = payload.get("signals") or []
    if not isinstance(raw_signals, list):
        raise ArkError("ARK_BAD_JSON", "signals 须为数组")
    if block_new_buys:
        raw_signals = [
            s
            for s in raw_signals
            if isinstance(s, dict) and str(s.get("side", "")).lower() != "buy"
        ]
        # 空仓观望/退潮兜底：模型若未出 sell，对可卖持仓自动补清仓卖单
        covered: set[str] = set()
        for s in raw_signals:
            if not isinstance(s, dict):
                continue
            if str(s.get("side", "")).lower() != "sell":
                continue
            covered.add(str(s.get("symbol", "")).zfill(6)[-6:])
        for p in positions:
            sym = str(p["symbol"]).zfill(6)[-6:]
            sellable = int(p["qty_sellable"])
            if sellable < lot or sym in covered:
                continue
            qty = (sellable // lot) * lot
            if qty < lot:
                continue
            raw_signals.append(
                {
                    "symbol": sym,
                    "side": "sell",
                    "qty": qty,
                    "order_type": "market",
                    "limit": None,
                    "rationale": "空仓观望/退潮：系统补卖可卖持仓",
                }
            )
            covered.add(sym)

    allowed = {i["symbol"]: i for i in instruments}
    accepted_signals: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    orders_out: list[dict[str, Any]] = []

    for item in raw_signals[: max_signals * 2]:
        if len(accepted_signals) >= max_signals:
            break
        if not isinstance(item, dict):
            skipped.append({"reason": "信号非对象", "raw": item})
            continue
        symbol = str(item.get("symbol", "")).zfill(6)[-6:]
        side = str(item.get("side", "")).lower()
        order_type = str(item.get("order_type") or "market").lower()
        rationale = str(item.get("rationale") or "").strip()
        try:
            qty = int(item.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0

        if symbol not in allowed:
            skipped.append({"symbol": symbol, "reason": "不在固定股票池"})
            continue
        if side not in ("buy", "sell"):
            skipped.append({"symbol": symbol, "reason": "side 非法"})
            continue
        if order_type not in ("market", "limit"):
            order_type = "market"
        if qty <= 0 or qty % lot != 0:
            skipped.append({"symbol": symbol, "reason": f"数量须为 {lot} 的正整数倍"})
            continue

        last = quote_map.get(symbol, {}).get("last")
        if last is None or float(last) <= 0:
            skipped.append({"symbol": symbol, "reason": "无有效报价"})
            continue
        last_f = float(last)
        notional = last_f * qty

        if side == "buy":
            if notional > equity * max_buy_pct + 1e-6:
                # 下调到上限整手
                max_qty = int((equity * max_buy_pct) // last_f // lot) * lot
                if max_qty < lot:
                    skipped.append({"symbol": symbol, "reason": "单笔买入超过权益上限且无法下调"})
                    continue
                qty = max_qty
                notional = last_f * qty
            if cash < notional:
                max_qty = int(cash // last_f // lot) * lot
                if max_qty < lot:
                    skipped.append({"symbol": symbol, "reason": "现金不足"})
                    continue
                qty = max_qty
        else:
            pos = pos_map.get(symbol)
            sellable = int(pos["qty_sellable"]) if pos else 0
            if sellable < lot:
                skipped.append({"symbol": symbol, "reason": "可卖不足（T+1）"})
                continue
            if qty > sellable:
                qty = (sellable // lot) * lot

        limit: Optional[float] = None
        if order_type == "limit":
            try:
                limit = float(item.get("limit")) if item.get("limit") is not None else last_f
            except (TypeError, ValueError):
                limit = last_f

        sig = {
            "symbol": symbol,
            "name": allowed[symbol]["name"],
            "side": side,
            "qty": qty,
            "order_type": order_type,
            "limit": limit,
            "rationale": rationale,
        }
        accepted_signals.append(sig)

        row = engine.place(
            symbol=symbol,
            side=side,
            qty=qty,
            order_type=order_type,
            limit=limit,
            desk_id=did,
        )
        orders_out.append(row)
        # 更新本地现金/可卖粗估，避免同轮超额
        if row.get("status") == "filled" and side == "buy":
            fill = float(row.get("fill_price") or last_f)
            cash -= fill * qty
            # 新买入当日不可卖，不写入 pos_map sellable
        elif row.get("status") == "filled" and side == "sell":
            if symbol in pos_map:
                pos_map[symbol] = {
                    **dict(pos_map[symbol]),
                    "qty_sellable": int(pos_map[symbol]["qty_sellable"]) - qty,
                }

    result = {
        "id": None,
        "desk_id": did,
        "desk_name": desk["name"],
        "ran_at": ts,
        "thesis": thesis,
        "analysis": analysis,
        "model": model,
        "data_source": "akshare+llm",
        "disclaimer": disclaimer,
        "signals": accepted_signals,
        "skipped": skipped,
        "orders": [
            {
                "id": o.get("id"),
                "symbol": o.get("symbol"),
                "side": o.get("side"),
                "qty": o.get("qty"),
                "status": o.get("status"),
                "reason": o.get("reason"),
                "fill_price": o.get("fill_price"),
            }
            for o in orders_out
        ],
        "filled_count": sum(1 for o in orders_out if o.get("status") == "filled"),
        "rejected_count": sum(1 for o in orders_out if o.get("status") == "rejected"),
    }

    cur = db.execute(
        """
        INSERT INTO strategy_runs (desk_id, ran_at, thesis, payload_json, model)
        VALUES (?,?,?,?,?)
        """,
        (did, ts, thesis, "{}", model),
    )
    run_id = int(cur.lastrowid)
    result["id"] = run_id
    db.execute(
        "UPDATE strategy_runs SET payload_json = ? WHERE id = ?",
        (json.dumps(result, ensure_ascii=False), run_id),
    )
    db.commit()
    log.info(
        "strategy round done desk=%s id=%s signals=%s filled=%s skipped=%s",
        did,
        run_id,
        len(accepted_signals),
        result["filled_count"],
        len(skipped),
    )
    return result


def _row_to_run(row: Any, desk_name: str = "") -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    analysis_payload = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    analysis = {
        "emotion_cycle": str(analysis_payload.get("emotion_cycle") or ""),
        "tape_metrics": str(analysis_payload.get("tape_metrics") or ""),
        "theme": str(analysis_payload.get("theme") or ""),
        "mode": str(analysis_payload.get("mode") or ""),
        "position_rule": str(analysis_payload.get("position_rule") or ""),
        "triggers": str(analysis_payload.get("triggers") or ""),
        "risks": str(analysis_payload.get("risks") or ""),
    }
    desk_id = str(row["desk_id"] if "desk_id" in row.keys() else payload.get("desk_id") or DEFAULT_DESK_ID)
    out = {
        "id": int(row["id"]),
        "desk_id": desk_id,
        "desk_name": str(payload.get("desk_name") or desk_name or desk_id),
        "ran_at": row["ran_at"],
        "thesis": row["thesis"] or payload.get("thesis") or "",
        "analysis": analysis,
        "model": row["model"] or payload.get("model") or "",
        "data_source": str(payload.get("data_source") or ""),
        "disclaimer": str(payload.get("disclaimer") or "【仅思路推演，不构成投资建议】· 仅本地模拟"),
        "signals": payload.get("signals") or [],
        "skipped": payload.get("skipped") or [],
        "orders": payload.get("orders") or [],
        "filled_count": int(payload.get("filled_count") or 0),
        "rejected_count": int(payload.get("rejected_count") or 0),
    }
    return out


def latest_run(db: Database, desk_id: str | None = None) -> Optional[dict[str, Any]]:
    if desk_id:
        row = db.fetchone(
            "SELECT id, desk_id, ran_at, thesis, payload_json, model FROM strategy_runs "
            "WHERE desk_id = ? ORDER BY id DESC LIMIT 1",
            (desk_id,),
        )
    else:
        row = db.fetchone(
            "SELECT id, desk_id, ran_at, thesis, payload_json, model FROM strategy_runs "
            "ORDER BY id DESC LIMIT 1"
        )
    if not row:
        return None
    return _row_to_run(row)


def list_runs(
    db: Database, *, limit: int = 50, desk_id: str | None = None
) -> list[dict[str, Any]]:
    lim = max(1, min(limit, 200))
    if desk_id:
        rows = db.fetchall(
            "SELECT id, desk_id, ran_at, thesis, payload_json, model FROM strategy_runs "
            "WHERE desk_id = ? ORDER BY id DESC LIMIT ?",
            (desk_id, lim),
        )
    else:
        rows = db.fetchall(
            "SELECT id, desk_id, ran_at, thesis, payload_json, model FROM strategy_runs "
            "ORDER BY id DESC LIMIT ?",
            (lim,),
        )
    return [_row_to_run(r) for r in rows]


def get_run(db: Database, run_id: int) -> Optional[dict[str, Any]]:
    row = db.fetchone(
        "SELECT id, desk_id, ran_at, thesis, payload_json, model FROM strategy_runs WHERE id = ?",
        (run_id,),
    )
    if not row:
        return None
    return _row_to_run(row)
