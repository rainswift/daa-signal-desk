from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

CN = ZoneInfo("Asia/Shanghai")

# 连续竞价窗（MVP 简化，不含集合竞价）
_MORNING = (time(9, 30), time(11, 30))
_AFTERNOON = (time(13, 0), time(15, 0))
# T+1：下一交易日开盘起可卖（与 TECH.md 一致；节假日暂按工作日简化）
T1_UNLOCK_TIME = time(9, 30)


def now_cn() -> datetime:
    return datetime.now(CN)


def is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5


def trade_date_key(dt: datetime | None = None) -> str:
    """交易日键 YYYY-MM-DD（上海时区；MVP=工作日）。"""
    dt = dt or now_cn()
    return dt.astimezone(CN).date().isoformat()


def t1_unlock_due(dt: datetime | None = None) -> bool:
    """当前是否已到本交易日 T+1 解锁时点（工作日 ≥ 09:30）。"""
    dt = dt or now_cn()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CN)
    else:
        dt = dt.astimezone(CN)
    if not is_weekday(dt):
        return False
    return dt.time() >= T1_UNLOCK_TIME


def in_continuous_auction(dt: datetime | None = None) -> bool:
    dt = dt or now_cn()
    if not is_weekday(dt):
        return False
    t = dt.time()
    return (_MORNING[0] <= t <= _MORNING[1]) or (_AFTERNOON[0] <= t <= _AFTERNOON[1])


def session_open(force: bool) -> bool:
    if force:
        return True
    return in_continuous_auction()
