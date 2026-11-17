from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from .calendar import in_continuous_auction, now_cn, session_open
from .db import Database

log = logging.getLogger("daa.market")


@dataclass
class RuntimeState:
    state: str = "closed"
    reason: str = "启动中"
    quote_age_max_sec: Optional[float] = None
    updated_at: str = ""
    consecutive_fails: int = 0
    consecutive_ok: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class MarketService:
    def __init__(
        self,
        db: Database,
        indices: list[dict[str, str]],
        *,
        poll_interval_sec: float,
        degrade_age_sec: float,
        halt_fail_count: int,
        halt_recover_success: int,
        force_session: bool,
        source: str,
        quote_kind: str = "stocks",
        poll_only_in_session: bool = True,
        on_tick: Optional[Callable[[], None]] = None,
    ) -> None:
        self.db = db
        self.indices = indices  # 交易标的池（股票或指数）
        self.poll_interval_sec = poll_interval_sec
        self.degrade_age_sec = degrade_age_sec
        self.halt_fail_count = halt_fail_count
        self.halt_recover_success = halt_recover_success
        self.force_session = force_session
        self.source = source
        self.quote_kind = quote_kind
        self.poll_only_in_session = poll_only_in_session
        self.on_tick = on_tick
        self.runtime = RuntimeState()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._mock_prices: dict[str, float] = {}
        for inst in indices:
            sym = inst["symbol"]
            seed = inst.get("seed")
            try:
                self._mock_prices[sym] = float(seed) if seed is not None else 20.0
            except (TypeError, ValueError):
                self._mock_prices[sym] = 20.0
        self._mock_prev: dict[str, float] = dict(self._mock_prices)
        # 演示降级：首轮写入后可选地「冻住」fetched_at 以制造超龄
        self.demo_stale_sec: float = 0.0

    def start(self) -> None:
        self._sync_universe()
        self._seed_missing()
        if self.poll_only_in_session and not in_continuous_auction():
            log.info("market poll deferred: outside continuous auction")
            self._recompute_runtime(True)
        else:
            self.refresh_once()
        self._thread = threading.Thread(target=self._loop, name="market-poll", daemon=True)
        self._thread.start()

    def _sync_universe(self) -> None:
        wanted = {i["symbol"] for i in self.indices}
        if not wanted:
            return
        rows = self.db.fetchall("SELECT symbol FROM quotes")
        for row in rows:
            if row["symbol"] not in wanted:
                self.db.execute("DELETE FROM quotes WHERE symbol = ?", (row["symbol"],))
        self.db.commit()

    def _seed_missing(self) -> None:
        ts = now_cn().isoformat(timespec="seconds")
        for idx in self.indices:
            sym = idx["symbol"]
            if self.db.fetchone("SELECT symbol FROM quotes WHERE symbol = ?", (sym,)):
                continue
            last = self._mock_prices.get(sym, 20.0)
            self.db.execute(
                "INSERT INTO quotes (symbol, name, last, pct_chg, fetched_at, source) VALUES (?,?,?,?,?,?)",
                (sym, idx["name"], last, 0.0, ts, "seed"),
            )
        self.db.commit()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_interval_sec):
            try:
                if self.poll_only_in_session and not in_continuous_auction():
                    # 收盘后不拉公开行情、不计连续失败；仍刷新运行态（非 force 时显示收市）
                    self._recompute_runtime(True)
                    continue
                self.refresh_once()
            except Exception:  # noqa: BLE001
                log.exception("market refresh failed")

    def refresh_once(self) -> None:
        """立即拉取一次（策略轮次/手动刷新仍可用，不受轮询时段限制）。"""
        if self.source == "akshare":
            ok = self._pull_akshare_stocks() if self.quote_kind == "stocks" else self._pull_akshare()
        else:
            ok = self._pull_mock()
        self._recompute_runtime(ok)
        if self.on_tick:
            self.on_tick()

    def _pull_mock(self) -> bool:
        ts = now_cn()
        # 若开启演示超龄，不刷新时间戳，仅轻微扰动价格（便于 UI 展示降级）
        freeze = self.demo_stale_sec > 0
        for idx in self.indices:
            sym = idx["symbol"]
            base = self._mock_prices.get(sym, 1000.0)
            if not freeze:
                shock = random.uniform(-0.0015, 0.0015)
                base = round(base * (1 + shock), 2)
                self._mock_prices[sym] = base
            prev = self._mock_prev.get(sym, base)
            pct = round((base - prev) / prev * 100, 2) if prev else 0.0
            fetched = ts.isoformat(timespec="seconds")
            if freeze:
                row = self.db.fetchone("SELECT fetched_at FROM quotes WHERE symbol = ?", (sym,))
                if row:
                    fetched = row["fetched_at"]
            self.db.execute(
                """
                INSERT INTO quotes (symbol, name, last, pct_chg, fetched_at, source)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(symbol) DO UPDATE SET
                  name=excluded.name, last=excluded.last, pct_chg=excluded.pct_chg,
                  fetched_at=excluded.fetched_at, source=excluded.source
                """,
                (sym, idx["name"], base, pct, fetched, "mock"),
            )
        self.db.commit()
        return True

    def _pull_akshare(self) -> bool:
        try:
            import akshare as ak
        except Exception as exc:  # noqa: BLE001
            log.warning("akshare import failed: %s", exc)
            return False

        wanted = {i["symbol"]: i for i in self.indices}
        frames: list[tuple[str, Any]] = []
        # akshare>=1.20.44：stock_zh_index_spot_em → index_zh_spot_em(symbol=系列)
        em_fn = getattr(ak, "index_zh_spot_em", None) or getattr(ak, "stock_zh_index_spot_em", None)
        if em_fn is not None:
            series_list = ("沪深重要指数", "上证系列指数", "深证系列指数", "中证系列指数")
            # 旧无参接口只调一次
            try_series = series_list if getattr(em_fn, "__name__", "") == "index_zh_spot_em" else (None,)
            covered: set[str] = set()
            for series in try_series:
                try:
                    df = em_fn() if series is None else em_fn(symbol=series)
                    if df is None or len(df) == 0:
                        continue
                    frames.append(("akshare-em", df))
                    for _, row in df.iterrows():
                        code = "".join(ch for ch in str(row.get("代码", "")) if ch.isdigit())[-6:].zfill(6)
                        if code in wanted:
                            covered.add(code)
                    if covered >= set(wanted):
                        break
                except Exception as exc:  # noqa: BLE001
                    log.warning("akshare EM pull failed (%s): %s", series or "default", exc)
                    break  # 东财限流时勿连环重试

        def _ingest(tag: str, df: Any) -> int:
            n = 0
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                code = "".join(ch for ch in code if ch.isdigit())[-6:].zfill(6)
                if code not in wanted or code in seen:
                    continue
                meta = wanted[code]
                try:
                    last = float(row.get("最新价") or row.get("最近价") or 0)
                    pct = float(row.get("涨跌幅") or 0)
                except (TypeError, ValueError):
                    continue
                if last <= 0:
                    continue
                self.db.execute(
                    """
                    INSERT INTO quotes (symbol, name, last, pct_chg, fetched_at, source)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      name=excluded.name, last=excluded.last, pct_chg=excluded.pct_chg,
                      fetched_at=excluded.fetched_at, source=excluded.source
                    """,
                    (code, meta["name"], last, pct, ts, tag),
                )
                seen.add(code)
                n += 1
            return n

        ts = now_cn().isoformat(timespec="seconds")
        seen: set[str] = set()
        hit = 0
        source_tag = ""
        for tag, df in frames:
            n = _ingest(tag, df)
            if n:
                hit += n
                source_tag = tag

        # 东财不全或不可用时用新浪补齐
        if len(seen) < len(wanted):
            sina_fn = getattr(ak, "index_zh_spot_sina", None)
            if sina_fn is not None:
                try:
                    df = sina_fn()
                    if df is not None and len(df) > 0:
                        n = _ingest("akshare-sina", df)
                        if n:
                            hit += n
                            source_tag = source_tag or "akshare-sina"
                except Exception as exc:  # noqa: BLE001
                    log.warning("akshare sina pull failed: %s", exc)

        if not frames and hit == 0:
            log.warning("akshare: no usable index spot API")
            return False

        self.db.commit()
        if hit:
            log.info("akshare quotes updated hit=%s/%s source=%s", hit, len(wanted), source_tag)
        return hit > 0

    def _pull_akshare_stocks(self) -> bool:
        """固定股票池：优先新浪 A 股全市场快照过滤（东财易限流）。"""
        try:
            import akshare as ak
        except Exception as exc:  # noqa: BLE001
            log.warning("akshare import failed: %s", exc)
            return False

        wanted = {i["symbol"]: i for i in self.indices}
        df = None
        tag = "akshare-sina"
        sina_fn = getattr(ak, "stock_zh_a_spot_sina", None)
        if sina_fn is not None:
            try:
                df = sina_fn()
            except Exception as exc:  # noqa: BLE001
                log.warning("akshare stock sina pull failed: %s", exc)
        if df is None or len(df) == 0:
            em_fn = getattr(ak, "stock_zh_a_spot_em", None)
            if em_fn is not None:
                try:
                    df = em_fn()
                    tag = "akshare-em"
                except Exception as exc:  # noqa: BLE001
                    log.warning("akshare stock EM pull failed: %s", exc)
                    return False
            else:
                return False

        ts = now_cn().isoformat(timespec="seconds")
        hit = 0
        for _, row in df.iterrows():
            code = "".join(ch for ch in str(row.get("代码", "")) if ch.isdigit())[-6:].zfill(6)
            if code not in wanted:
                continue
            meta = wanted[code]
            try:
                last = float(row.get("最新价") or 0)
                pct = float(row.get("涨跌幅") or 0)
            except (TypeError, ValueError):
                continue
            if last <= 0:
                continue
            self.db.execute(
                """
                INSERT INTO quotes (symbol, name, last, pct_chg, fetched_at, source)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(symbol) DO UPDATE SET
                  name=excluded.name, last=excluded.last, pct_chg=excluded.pct_chg,
                  fetched_at=excluded.fetched_at, source=excluded.source
                """,
                (code, meta["name"], last, pct, ts, tag),
            )
            self._mock_prices[code] = last
            hit += 1
        self.db.commit()
        if hit:
            log.info("akshare stock quotes updated hit=%s/%s source=%s", hit, len(wanted), tag)
        return hit > 0

    def _recompute_runtime(self, pull_ok: bool) -> None:
        with self.runtime.lock:
            if not session_open(self.force_session):
                self._set("closed", "非连续竞价时段", None)
                return

            if not pull_ok:
                self.runtime.consecutive_fails += 1
                self.runtime.consecutive_ok = 0
                if self.runtime.consecutive_fails >= self.halt_fail_count:
                    self._set("halted", f"连续拉取失败 ≥ {self.halt_fail_count}", None)
                return

            self.runtime.consecutive_fails = 0
            self.runtime.consecutive_ok += 1

            ages = self._ages()
            age_max = max(ages) if ages else None

            if self.runtime.state == "halted":
                if self.runtime.consecutive_ok >= self.halt_recover_success and (
                    age_max is None or age_max <= self.degrade_age_sec
                ):
                    pass  # fall through to normal/degraded
                else:
                    self._set("halted", "熔断恢复中（需连续成功）", age_max)
                    return

            if age_max is not None and age_max > self.degrade_age_sec:
                self._set("degraded", f"行情年龄 {age_max:.0f}s 超过 {self.degrade_age_sec:.0f}s", age_max)
                return

            self._set("normal", "连续竞价 · 行情正常", age_max)

    def _ages(self) -> list[float]:
        now = now_cn()
        ages: list[float] = []
        for row in self.db.fetchall("SELECT fetched_at FROM quotes"):
            try:
                ft = datetime.fromisoformat(row["fetched_at"])
                if ft.tzinfo is None:
                    ft = ft.replace(tzinfo=now.tzinfo)
                ages.append(max(0.0, (now - ft).total_seconds()))
            except ValueError:
                ages.append(9999.0)
        return ages

    def _set(self, state: str, reason: str, age_max: Optional[float]) -> None:
        prev = self.runtime.state
        self.runtime.state = state
        self.runtime.reason = reason
        self.runtime.quote_age_max_sec = age_max
        self.runtime.updated_at = now_cn().isoformat(timespec="seconds")
        if prev != state:
            self.db.execute(
                "INSERT INTO runtime_events (state, reason, at) VALUES (?,?,?)",
                (state, reason, self.runtime.updated_at),
            )
            self.db.commit()

    def snapshot_runtime(self) -> dict[str, Any]:
        with self.runtime.lock:
            # 每次读取时刷新年龄
            ages = self._ages()
            age_max = max(ages) if ages else None
            if session_open(self.force_session) and self.runtime.state in ("normal", "degraded"):
                if age_max is not None and age_max > self.degrade_age_sec:
                    self.runtime.state = "degraded"
                    self.runtime.reason = f"行情年龄 {age_max:.0f}s 超过 {self.degrade_age_sec:.0f}s"
                elif self.runtime.state == "degraded" and (age_max is None or age_max <= self.degrade_age_sec):
                    self.runtime.state = "normal"
                    self.runtime.reason = "连续竞价 · 行情正常"
                self.runtime.quote_age_max_sec = age_max
                self.runtime.updated_at = now_cn().isoformat(timespec="seconds")
            return {
                "state": self.runtime.state,
                "reason": self.runtime.reason,
                "quote_age_max_sec": self.runtime.quote_age_max_sec,
                "updated_at": self.runtime.updated_at,
                "force_session": self.force_session,
            }

    def list_quotes(self) -> list[dict[str, Any]]:
        rt = self.snapshot_runtime()
        color_map = {i["symbol"]: i["color"] for i in self.indices}
        name_map = {i["symbol"]: i["name"] for i in self.indices}
        now = now_cn()
        out: list[dict[str, Any]] = []
        for row in self.db.fetchall("SELECT * FROM quotes"):
            try:
                ft = datetime.fromisoformat(row["fetched_at"])
                if ft.tzinfo is None:
                    ft = ft.replace(tzinfo=now.tzinfo)
                age = max(0.0, (now - ft).total_seconds())
            except ValueError:
                age = 9999.0
            line_state = rt["state"]
            if age > self.degrade_age_sec and line_state == "normal":
                line_state = "degraded"
            out.append(
                {
                    "symbol": row["symbol"],
                    "name": name_map.get(row["symbol"], row["name"]),
                    "last": float(row["last"]),
                    "pct_chg": float(row["pct_chg"]),
                    "age_sec": round(age, 1),
                    "line_state": line_state,
                    "color": color_map.get(row["symbol"], "#607D8B"),
                    "fetched_at": row["fetched_at"],
                }
            )
        # 按配置顺序
        order = {i["symbol"]: n for n, i in enumerate(self.indices)}
        out.sort(key=lambda q: order.get(q["symbol"], 99))
        return out

    def get_last(self, symbol: str) -> Optional[float]:
        row = self.db.fetchone("SELECT last FROM quotes WHERE symbol = ?", (symbol,))
        return float(row["last"]) if row else None

    def set_demo_stale(self, seconds: float) -> None:
        """把所有报价 fetched_at 回拨，制造降级。"""
        self.demo_stale_sec = max(0.0, seconds)
        if seconds <= 0:
            self.refresh_once()
            return
        from datetime import timedelta

        stale_at = (now_cn() - timedelta(seconds=seconds)).isoformat(timespec="seconds")
        self.db.execute("UPDATE quotes SET fetched_at = ?", (stale_at,))
        self.db.commit()
        self._recompute_runtime(True)
