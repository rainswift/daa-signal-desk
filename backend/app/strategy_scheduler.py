from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Optional

from .calendar import in_continuous_auction, now_cn

log = logging.getLogger("daa.strategy_scheduler")


@dataclass
class SchedulerStatus:
    desk_id: str
    enabled: bool
    only_in_session: bool
    interval_sec: int
    running: bool
    in_session: bool
    busy: bool
    last_ran_at: Optional[str]
    last_ok: Optional[bool]
    last_error: Optional[str]
    next_due_at: Optional[str]
    last_filled: Optional[int]


class StrategyScheduler:
    """连续竞价时段按间隔自动跑策略一轮；同轮互斥，避免 LLM 重叠。"""

    def __init__(
        self,
        *,
        desk_id: str,
        enabled: bool,
        interval_sec: int,
        only_in_session: bool,
        run_fn: Callable[[], dict[str, Any]],
    ) -> None:
        self.desk_id = desk_id
        self.enabled = enabled
        self.interval_sec = max(30, int(interval_sec))
        self.only_in_session = only_in_session
        self._run_fn = run_fn
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.busy = False
        self.last_ran_at: Optional[str] = None
        self.last_ok: Optional[bool] = None
        self.last_error: Optional[str] = None
        self.last_filled: Optional[int] = None
        self.next_due_at: Optional[str] = None

    def start(self) -> None:
        if not self.enabled:
            log.info("strategy scheduler disabled desk=%s", self.desk_id)
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name=f"strategy-scheduler-{self.desk_id}", daemon=True
        )
        self._thread.start()
        log.info(
            "strategy scheduler started desk=%s interval=%ss only_in_session=%s",
            self.desk_id,
            self.interval_sec,
            self.only_in_session,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def status(self) -> SchedulerStatus:
        return SchedulerStatus(
            desk_id=self.desk_id,
            enabled=self.enabled,
            only_in_session=self.only_in_session,
            interval_sec=self.interval_sec,
            running=bool(self._thread and self._thread.is_alive()),
            in_session=in_continuous_auction(),
            busy=self.busy,
            last_ran_at=self.last_ran_at,
            last_ok=self.last_ok,
            last_error=self.last_error,
            next_due_at=self.next_due_at,
            last_filled=self.last_filled,
        )

    def _loop(self) -> None:
        # 对齐到下一整点间隔，避免启动瞬间连环打满
        self._sleep_until(self._next_due())
        while not self._stop.is_set():
            due = self._next_due()
            self.next_due_at = due.isoformat(timespec="seconds")
            self._sleep_until(due)
            if self._stop.is_set():
                break
            if self.only_in_session and not in_continuous_auction():
                log.info("strategy scheduler skip desk=%s: outside continuous auction", self.desk_id)
                continue
            self._execute_once()

    def _execute_once(self) -> None:
        if not self._lock.acquire(blocking=False):
            log.warning(
                "strategy scheduler skip desk=%s: previous round still running", self.desk_id
            )
            return
        self.busy = True
        ts = now_cn().isoformat(timespec="seconds")
        try:
            result = self._run_fn()
            self.last_ran_at = str(result.get("ran_at") or ts)
            self.last_ok = True
            self.last_error = None
            self.last_filled = int(result.get("filled_count") or 0)
            log.info(
                "strategy scheduler ok desk=%s filled=%s signals=%s",
                self.desk_id,
                self.last_filled,
                len(result.get("signals") or []),
            )
        except Exception as exc:  # noqa: BLE001
            self.last_ran_at = ts
            self.last_ok = False
            self.last_error = str(exc)
            self.last_filled = None
            log.exception("strategy scheduler failed desk=%s: %s", self.desk_id, exc)
        finally:
            self.busy = False
            self._lock.release()

    def _next_due(self):
        now = now_cn()
        # 对齐到 interval 边界（按当日秒数）
        day_sec = now.hour * 3600 + now.minute * 60 + now.second
        slot = (day_sec // self.interval_sec + 1) * self.interval_sec
        # 过午夜则落到次日 0 点附近的第一个 slot
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if slot >= 24 * 3600:
            return base + timedelta(days=1, seconds=self.interval_sec)
        return base + timedelta(seconds=slot)

    def _sleep_until(self, due) -> None:
        while not self._stop.is_set():
            now = now_cn()
            remain = (due - now).total_seconds()
            if remain <= 0:
                return
            self.next_due_at = due.isoformat(timespec="seconds")
            self._stop.wait(min(remain, 5.0))
