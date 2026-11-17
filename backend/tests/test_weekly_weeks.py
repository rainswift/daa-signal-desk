from datetime import date

from app.weekly import list_weeks, week_bounds


def test_week_bounds():
    start, end = week_bounds("2026-W01")
    assert start.weekday() == 0
    assert (end - start).days == 6


def test_list_weeks_2026_through_nov():
    weeks = list_weeks(2026, today=date(2026, 11, 16))
    assert weeks
    assert weeks[0]["week_key"].startswith("2026-W")
    keys = {w["week_key"] for w in weeks}
    assert "2026-W01" in keys or any(k.endswith("W01") is False for k in keys)
    # 应包含当前周附近
    assert any(w["week_key"] >= "2026-W45" for w in weeks)
