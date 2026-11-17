from __future__ import annotations

from typing import Any, Optional

from .calendar import now_cn
from .db import Database
from .ledger import DEFAULT_DESK_ID, apply_fill, fees_for_trade, get_account, get_positions
from .market import MarketService


class Reject(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MatchingEngine:
    def __init__(self, db: Database, market: MarketService, cfg: dict[str, Any]) -> None:
        self.db = db
        self.market = market
        self.cfg = cfg
        self.symbols = {i["symbol"] for i in cfg["indices"]}

    def place(
        self,
        *,
        symbol: str,
        side: str,
        qty: int,
        order_type: str,
        limit: Optional[float],
        desk_id: str = DEFAULT_DESK_ID,
    ) -> dict[str, Any]:
        ts = now_cn().isoformat(timespec="seconds")
        rt = self.market.snapshot_runtime()

        if symbol not in self.symbols:
            return self._reject(
                desk_id, symbol, side, qty, order_type, limit, "NO_QUOTE", "标的不在指数池", ts
            )

        if rt["state"] == "closed":
            return self._reject(
                desk_id, symbol, side, qty, order_type, limit, "OUT_OF_SESSION", "非交易时段", ts
            )
        if rt["state"] == "degraded":
            return self._reject(
                desk_id, symbol, side, qty, order_type, limit, "MARKET_DEGRADED", rt["reason"], ts
            )
        if rt["state"] == "halted":
            return self._reject(
                desk_id, symbol, side, qty, order_type, limit, "MARKET_HALTED", rt["reason"], ts
            )

        lot = int(self.cfg["lot_size"])
        if qty % lot != 0:
            return self._reject(
                desk_id,
                symbol,
                side,
                qty,
                order_type,
                limit,
                "LOT_SIZE",
                f"数量须为 {lot} 的整数倍",
                ts,
            )

        last = self.market.get_last(symbol)
        if last is None or last <= 0:
            return self._reject(
                desk_id, symbol, side, qty, order_type, limit, "NO_QUOTE", "无有效报价", ts
            )

        fill_price: Optional[float] = None
        if order_type == "market":
            fill_price = last
        else:
            if limit is None:
                return self._reject(
                    desk_id, symbol, side, qty, order_type, limit, "NO_QUOTE", "限价单缺少限价", ts
                )
            if side == "buy" and last <= limit:
                fill_price = last
            elif side == "sell" and last >= limit:
                fill_price = last
            else:
                # MVP：限价未触达立即挂起（当日收盘撤为 P2）
                oid = self._insert_order(
                    desk_id, symbol, side, qty, order_type, limit, "open", None, None, ts
                )
                self.db.commit()
                return self._order_row(oid)

        assert fill_price is not None
        notional = fill_price * qty
        commission, stamp, transfer = fees_for_trade(
            side,
            notional,
            float(self.cfg["commission_rate"]),
            float(self.cfg["min_commission"]),
            float(self.cfg["stamp_tax_rate"]),
            float(self.cfg["transfer_fee_rate"]),
        )
        fee_sum = commission + stamp + transfer

        if side == "buy":
            cash = float(get_account(self.db, desk_id)["cash"])
            if cash < notional + fee_sum:
                return self._reject(
                    desk_id, symbol, side, qty, order_type, limit, "INSUFFICIENT_CASH", "资金不足", ts
                )
        else:
            pos = next((p for p in get_positions(self.db, desk_id) if p["symbol"] == symbol), None)
            if pos is None or int(pos["qty_sellable"]) < qty:
                return self._reject(
                    desk_id,
                    symbol,
                    side,
                    qty,
                    order_type,
                    limit,
                    "INSUFFICIENT_SELLABLE",
                    "可卖数量不足（T+1）",
                    ts,
                )

        oid = self._insert_order(
            desk_id, symbol, side, qty, order_type, limit, "accepted", None, None, ts
        )
        try:
            apply_fill(
                self.db,
                order_id=oid,
                desk_id=desk_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=fill_price,
                commission=commission,
                stamp_tax=stamp,
                transfer_fee=transfer,
            )
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.execute(
                "UPDATE orders SET status = 'rejected', reason = ?, updated_at = ? WHERE id = ?",
                (str(exc), ts, oid),
            )
            self.db.commit()
            raise Reject("SHORT_NOT_ALLOWED" if "SELLABLE" in str(exc) else "NO_QUOTE", str(exc)) from exc

        return self._order_row(oid)

    def _insert_order(
        self,
        desk_id: str,
        symbol: str,
        side: str,
        qty: int,
        order_type: str,
        limit: Optional[float],
        status: str,
        reason: Optional[str],
        fill_price: Optional[float],
        ts: str,
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO orders (desk_id, symbol, side, qty, type, limit_price, status, reason, fill_price, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (desk_id, symbol, side, qty, order_type, limit, status, reason, fill_price, ts, ts),
        )
        return int(cur.lastrowid)

    def _reject(
        self,
        desk_id: str,
        symbol: str,
        side: str,
        qty: int,
        order_type: str,
        limit: Optional[float],
        code: str,
        message: str,
        ts: str,
    ) -> dict[str, Any]:
        oid = self._insert_order(
            desk_id, symbol, side, qty, order_type, limit, "rejected", f"{code}: {message}", None, ts
        )
        self.db.commit()
        row = self._order_row(oid)
        row["reject_code"] = code
        return row

    def _order_row(self, oid: int) -> dict[str, Any]:
        row = self.db.fetchone("SELECT * FROM orders WHERE id = ?", (oid,))
        assert row is not None
        return {
            "id": int(row["id"]),
            "desk_id": row["desk_id"],
            "symbol": row["symbol"],
            "side": row["side"],
            "qty": int(row["qty"]),
            "type": row["type"],
            "limit_price": row["limit_price"],
            "status": row["status"],
            "reason": row["reason"],
            "fill_price": row["fill_price"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_orders(self, limit: int = 50, desk_id: str | None = None) -> list[dict[str, Any]]:
        if desk_id is None:
            rows = self.db.fetchall(
                "SELECT * FROM orders ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM orders WHERE desk_id = ? ORDER BY id DESC LIMIT ?",
                (desk_id, limit),
            )
        return [
            {
                "id": int(r["id"]),
                "desk_id": r["desk_id"],
                "symbol": r["symbol"],
                "side": r["side"],
                "qty": int(r["qty"]),
                "type": r["type"],
                "limit_price": r["limit_price"],
                "status": r["status"],
                "reason": r["reason"],
                "fill_price": r["fill_price"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
