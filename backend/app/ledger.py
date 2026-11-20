from __future__ import annotations

from datetime import datetime
from typing import Any

from .calendar import now_cn, t1_unlock_due, trade_date_key
from .db import Database

DEFAULT_DESK_ID = "deepseek"
META_T1_UNLOCKED_TRADE_DATE = "t1_unlocked_trade_date"


def _iso(dt: datetime | None = None) -> str:
    return (dt or now_cn()).isoformat(timespec="seconds")


def ensure_account(db: Database, initial_cash: float, desk_id: str = DEFAULT_DESK_ID) -> None:
    row = db.fetchone("SELECT desk_id FROM account WHERE desk_id = ?", (desk_id,))
    if row is None:
        db.execute(
            "INSERT INTO account (desk_id, cash, fees_total, updated_at) VALUES (?, ?, 0, ?)",
            (desk_id, initial_cash, _iso()),
        )
        db.commit()


def ensure_desks(db: Database, initial_cash: float, desk_ids: list[str]) -> None:
    for desk_id in desk_ids:
        ensure_account(db, initial_cash, desk_id)


def get_account(db: Database, desk_id: str = DEFAULT_DESK_ID) -> dict[str, Any]:
    row = db.fetchone(
        "SELECT desk_id, cash, fees_total, updated_at FROM account WHERE desk_id = ?",
        (desk_id,),
    )
    assert row is not None, f"account missing for desk_id={desk_id}"
    return dict(row)


def get_positions(db: Database, desk_id: str = DEFAULT_DESK_ID) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in db.fetchall(
            "SELECT desk_id, symbol, qty, qty_sellable, cost_basis FROM positions WHERE desk_id = ?",
            (desk_id,),
        )
    ]


def reset_account(db: Database, initial_cash: float, desk_id: str = DEFAULT_DESK_ID) -> None:
    """清空指定台的交易/策略记录并重置资金。"""
    order_ids = [
        int(r["id"])
        for r in db.fetchall("SELECT id FROM orders WHERE desk_id = ?", (desk_id,))
    ]
    if order_ids:
        placeholders = ",".join("?" * len(order_ids))
        db.execute(f"DELETE FROM fills WHERE order_id IN ({placeholders})", order_ids)
    db.execute("DELETE FROM orders WHERE desk_id = ?", (desk_id,))
    db.execute("DELETE FROM positions WHERE desk_id = ?", (desk_id,))
    db.execute("DELETE FROM strategy_runs WHERE desk_id = ?", (desk_id,))
    db.execute(
        "UPDATE account SET cash = ?, fees_total = 0, updated_at = ? WHERE desk_id = ?",
        (initial_cash, _iso(), desk_id),
    )
    db.commit()


def reset_all_accounts(db: Database, initial_cash: float, desk_ids: list[str]) -> None:
    for desk_id in desk_ids:
        reset_account(db, initial_cash, desk_id)


def close_orphan_positions(
    db: Database, allowed_symbols: set[str], desk_id: str | None = None
) -> list[str]:
    """交易池切换后：池外持仓按成本退回现金并删除。"""
    closed: list[str] = []
    if desk_id is None:
        desks = [str(r["desk_id"]) for r in db.fetchall("SELECT desk_id FROM account")]
    else:
        desks = [desk_id]
    for did in desks:
        acct = get_account(db, did)
        cash = float(acct["cash"])
        desk_closed: list[str] = []
        for p in get_positions(db, did):
            sym = str(p["symbol"])
            if sym in allowed_symbols:
                continue
            cash += float(p["cost_basis"])
            db.execute("DELETE FROM positions WHERE desk_id = ? AND symbol = ?", (did, sym))
            desk_closed.append(f"{did}:{sym}")
        if desk_closed:
            db.execute(
                "UPDATE account SET cash = ?, updated_at = ? WHERE desk_id = ?",
                (cash, _iso(), did),
            )
            closed.extend(desk_closed)
    if closed:
        db.commit()
    return closed


def fees_for_trade(
    side: str,
    notional: float,
    commission_rate: float,
    min_commission: float,
    stamp_tax_rate: float,
    transfer_fee_rate: float,
) -> tuple[float, float, float]:
    commission = max(notional * commission_rate, min_commission)
    stamp = notional * stamp_tax_rate if side == "sell" else 0.0
    transfer = notional * transfer_fee_rate
    return commission, stamp, transfer


def apply_fill(
    db: Database,
    *,
    order_id: int,
    desk_id: str,
    symbol: str,
    side: str,
    qty: int,
    price: float,
    commission: float,
    stamp_tax: float,
    transfer_fee: float,
) -> None:
    fee_sum = commission + stamp_tax + transfer_fee
    notional = price * qty
    acct = get_account(db, desk_id)
    cash = float(acct["cash"])
    fees_total = float(acct["fees_total"]) + fee_sum

    if side == "buy":
        cash -= notional + fee_sum
        pos = db.fetchone(
            "SELECT qty, qty_sellable, cost_basis FROM positions WHERE desk_id = ? AND symbol = ?",
            (desk_id, symbol),
        )
        if pos is None:
            db.execute(
                "INSERT INTO positions (desk_id, symbol, qty, qty_sellable, cost_basis) VALUES (?, ?, ?, 0, ?)",
                (desk_id, symbol, qty, notional),
            )
        else:
            new_qty = int(pos["qty"]) + qty
            new_cost = float(pos["cost_basis"]) + notional
            db.execute(
                "UPDATE positions SET qty = ?, cost_basis = ? WHERE desk_id = ? AND symbol = ?",
                (new_qty, new_cost, desk_id, symbol),
            )
    else:
        cash += notional - fee_sum
        pos = db.fetchone(
            "SELECT qty, qty_sellable, cost_basis FROM positions WHERE desk_id = ? AND symbol = ?",
            (desk_id, symbol),
        )
        if pos is None or int(pos["qty_sellable"]) < qty:
            raise RuntimeError("INSUFFICIENT_SELLABLE")
        old_qty = int(pos["qty"])
        old_cost = float(pos["cost_basis"])
        avg = old_cost / old_qty if old_qty else 0.0
        new_qty = old_qty - qty
        new_sellable = int(pos["qty_sellable"]) - qty
        new_cost = avg * new_qty
        if new_qty == 0:
            db.execute(
                "DELETE FROM positions WHERE desk_id = ? AND symbol = ?",
                (desk_id, symbol),
            )
        else:
            db.execute(
                "UPDATE positions SET qty = ?, qty_sellable = ?, cost_basis = ? WHERE desk_id = ? AND symbol = ?",
                (new_qty, new_sellable, new_cost, desk_id, symbol),
            )

    ts = _iso()
    db.execute(
        "INSERT INTO fills (order_id, price, qty, commission, stamp_tax, transfer_fee, traded_at) VALUES (?,?,?,?,?,?,?)",
        (order_id, price, qty, commission, stamp_tax, transfer_fee, ts),
    )
    db.execute(
        "UPDATE orders SET status = 'filled', fill_price = ?, reason = NULL, updated_at = ? WHERE id = ?",
        (price, ts, order_id),
    )
    db.execute(
        "UPDATE account SET cash = ?, fees_total = ?, updated_at = ? WHERE desk_id = ?",
        (cash, fees_total, ts, desk_id),
    )


def unlock_t1(db: Database, desk_id: str | None = None) -> None:
    """将持仓可卖数量对齐为持仓量（当日买入的份额在下次加仓前仍靠「买入不增可卖」约束）。"""
    if desk_id is None:
        db.execute("UPDATE positions SET qty_sellable = qty")
    else:
        db.execute("UPDATE positions SET qty_sellable = qty WHERE desk_id = ?", (desk_id,))
    db.commit()


def maybe_unlock_t1(db: Database, now: datetime | None = None) -> dict[str, Any]:
    """
    每个交易日 ≥09:30 自动解锁一次：qty_sellable = qty。
    幂等：同一 trade_date 只执行一次；周末/09:30 前跳过。
    """
    now = now or now_cn()
    if not t1_unlock_due(now):
        return {"unlocked": False, "reason": "not_due"}
    trade_date = trade_date_key(now)
    row = db.fetchone(
        "SELECT value FROM meta WHERE key = ?",
        (META_T1_UNLOCKED_TRADE_DATE,),
    )
    if row is not None and str(row["value"]) == trade_date:
        return {"unlocked": False, "reason": "already", "trade_date": trade_date}

    unlock_t1(db)
    db.execute(
        """
        INSERT INTO meta (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (META_T1_UNLOCKED_TRADE_DATE, trade_date),
    )
    db.commit()
    return {"unlocked": True, "reason": "ok", "trade_date": trade_date}