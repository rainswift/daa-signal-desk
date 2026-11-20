from datetime import datetime
from pathlib import Path

import pytest
from zoneinfo import ZoneInfo

from app.calendar import t1_unlock_due, trade_date_key
from app.db import Database
from app.ledger import ensure_account, maybe_unlock_t1

CN = ZoneInfo("Asia/Shanghai")


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "t1.sqlite")


def _seed_locked(db: Database, desk_id: str = "deepseek") -> None:
    ensure_account(db, 1_000_000.0, desk_id)
    db.execute(
        "INSERT INTO positions (desk_id, symbol, qty, qty_sellable, cost_basis) VALUES (?,?,?,?,?)",
        (desk_id, "601899", 100, 0, 2445.0),
    )
    db.commit()


def test_t1_unlock_due_weekday_morning():
    assert t1_unlock_due(datetime(2026, 11, 20, 9, 30, tzinfo=CN)) is True
    assert t1_unlock_due(datetime(2026, 11, 20, 9, 29, tzinfo=CN)) is False
    assert t1_unlock_due(datetime(2026, 11, 21, 10, 0, tzinfo=CN)) is False  # Saturday


def test_maybe_unlock_skips_before_open(db: Database):
    _seed_locked(db)
    now = datetime(2026, 11, 20, 9, 0, tzinfo=CN)
    result = maybe_unlock_t1(db, now=now)
    assert result["unlocked"] is False
    assert result["reason"] == "not_due"
    row = db.fetchone("SELECT qty_sellable FROM positions WHERE symbol = ?", ("601899",))
    assert int(row["qty_sellable"]) == 0


def test_maybe_unlock_once_per_trade_day(db: Database):
    _seed_locked(db)
    now = datetime(2026, 11, 20, 10, 5, tzinfo=CN)
    first = maybe_unlock_t1(db, now=now)
    assert first["unlocked"] is True
    assert first["trade_date"] == trade_date_key(now)
    row = db.fetchone("SELECT qty_sellable FROM positions WHERE symbol = ?", ("601899",))
    assert int(row["qty_sellable"]) == 100

    # 同日再买一笔：可卖不应被同日二次解锁抬高——第二次应 already
    db.execute(
        "UPDATE positions SET qty = 200 WHERE desk_id = ? AND symbol = ?",
        ("deepseek", "601899"),
    )
    db.commit()
    second = maybe_unlock_t1(db, now=now)
    assert second["unlocked"] is False
    assert second["reason"] == "already"
    row = db.fetchone("SELECT qty_sellable FROM positions WHERE symbol = ?", ("601899",))
    assert int(row["qty_sellable"]) == 100

    # 下一交易日再解锁
    next_day = datetime(2026, 11, 21, 9, 30, tzinfo=CN)  # Saturday → not due
    assert maybe_unlock_t1(db, now=next_day)["reason"] == "not_due"
    monday = datetime(2026, 11, 23, 9, 30, tzinfo=CN)
    third = maybe_unlock_t1(db, now=monday)
    assert third["unlocked"] is True
    row = db.fetchone("SELECT qty_sellable FROM positions WHERE symbol = ?", ("601899",))
    assert int(row["qty_sellable"]) == 200
