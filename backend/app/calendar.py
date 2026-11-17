from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

CN = ZoneInfo("Asia/Shanghai")

# 连续竞价窗（MVP 简化，不含集合竞价）
_MORNING = (time(9, 30), time(11, 30))
_AFTERNOON = (time(13, 0), time(15, 0))


def now_cn() -> datetime:
    return datetime.now(CN)


def is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5


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
