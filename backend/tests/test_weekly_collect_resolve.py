from datetime import date

from app.weekly import stats_to_prompt_text
from app.weekly_collect import resolve_trade_week_for_iso_key


def test_resolve_trade_week_for_iso_key_with_calendar():
    # 2026-W46: Mon 2026-11-09 .. Fri 2026-11-13
    cal = [
        date(2026, 11, 9),
        date(2026, 11, 10),
        date(2026, 11, 11),
        date(2026, 11, 12),
        date(2026, 11, 13),
    ]
    monday, friday, days = resolve_trade_week_for_iso_key(
        "2026-W46", trade_dates=cal, today=date(2026, 11, 16)
    )
    assert monday == date(2026, 11, 9)
    assert friday == date(2026, 11, 13)
    assert days == cal


def test_resolve_trade_week_fallback_weekdays():
    monday, friday, days = resolve_trade_week_for_iso_key(
        "2026-W46", trade_dates=[], today=date(2026, 11, 16)
    )
    assert monday == date(2026, 11, 9)
    assert friday == date(2026, 11, 13)
    assert len(days) == 5


def test_stats_to_prompt_prefers_collected_text():
    text = stats_to_prompt_text(
        {
            "week_key": "2026-W46",
            "data_source": "akshare",
            "note": "test",
            "prompt_text": "本周周期：2026.11.09-2026.11.13\n\n指数数据：\n- 上证综指 | 周涨跌幅: 1 %",
        }
    )
    assert text.startswith("本周周期：2026.11.09-2026.11.13")
    assert "week_key=2026-W46" in text
    assert "上证综指" in text
