from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
  symbol TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  last REAL NOT NULL,
  pct_chg REAL NOT NULL,
  fetched_at TEXT NOT NULL,
  source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  desk_id TEXT NOT NULL DEFAULT 'deepseek',
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty INTEGER NOT NULL,
  type TEXT NOT NULL,
  limit_price REAL,
  status TEXT NOT NULL,
  reason TEXT,
  fill_price REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL,
  price REAL NOT NULL,
  qty INTEGER NOT NULL,
  commission REAL NOT NULL,
  stamp_tax REAL NOT NULL,
  transfer_fee REAL NOT NULL,
  traded_at TEXT NOT NULL,
  FOREIGN KEY(order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS positions (
  desk_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  qty INTEGER NOT NULL,
  qty_sellable INTEGER NOT NULL,
  cost_basis REAL NOT NULL,
  PRIMARY KEY (desk_id, symbol)
);

CREATE TABLE IF NOT EXISTS account (
  desk_id TEXT PRIMARY KEY,
  cash REAL NOT NULL,
  fees_total REAL NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  state TEXT NOT NULL,
  reason TEXT NOT NULL,
  at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_reports (
  week_key TEXT PRIMARY KEY,
  week_start TEXT NOT NULL,
  week_end TEXT NOT NULL,
  stats_json TEXT NOT NULL,
  content_md TEXT NOT NULL,
  model TEXT NOT NULL,
  data_source TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  desk_id TEXT NOT NULL DEFAULT 'deepseek',
  ran_at TEXT NOT NULL,
  thesis TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  model TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _table_columns(self, table: str) -> set[str]:
        rows = self.fetchall(f"PRAGMA table_info({table})")
        return {str(r["name"]) for r in rows}

    def _migrate(self) -> None:
        """把旧单账户 schema 迁到 desk_id 隔离；幂等。"""
        # —— account：旧版 id=1 → desk_id ——
        acct_cols = self._table_columns("account")
        if "desk_id" not in acct_cols and "id" in acct_cols:
            self.execute(
                """
                CREATE TABLE account_new (
                  desk_id TEXT PRIMARY KEY,
                  cash REAL NOT NULL,
                  fees_total REAL NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            self.execute(
                """
                INSERT INTO account_new (desk_id, cash, fees_total, updated_at)
                SELECT 'deepseek', cash, fees_total, updated_at FROM account WHERE id = 1
                """
            )
            self.execute("DROP TABLE account")
            self.execute("ALTER TABLE account_new RENAME TO account")
        elif "desk_id" not in acct_cols:
            # 空库但建表已是新 schema；无动作
            pass

        # —— positions：旧版 symbol PK → (desk_id, symbol) ——
        pos_cols = self._table_columns("positions")
        if "desk_id" not in pos_cols:
            self.execute(
                """
                CREATE TABLE positions_new (
                  desk_id TEXT NOT NULL,
                  symbol TEXT NOT NULL,
                  qty INTEGER NOT NULL,
                  qty_sellable INTEGER NOT NULL,
                  cost_basis REAL NOT NULL,
                  PRIMARY KEY (desk_id, symbol)
                )
                """
            )
            self.execute(
                """
                INSERT INTO positions_new (desk_id, symbol, qty, qty_sellable, cost_basis)
                SELECT 'deepseek', symbol, qty, qty_sellable, cost_basis FROM positions
                """
            )
            self.execute("DROP TABLE positions")
            self.execute("ALTER TABLE positions_new RENAME TO positions")

        # —— orders：补 desk_id ——
        order_cols = self._table_columns("orders")
        if "desk_id" not in order_cols:
            self.execute("ALTER TABLE orders ADD COLUMN desk_id TEXT NOT NULL DEFAULT 'deepseek'")

        # —— strategy_runs：补 desk_id ——
        run_cols = self._table_columns("strategy_runs")
        if "desk_id" not in run_cols:
            self.execute(
                "ALTER TABLE strategy_runs ADD COLUMN desk_id TEXT NOT NULL DEFAULT 'deepseek'"
            )

        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, tuple(params))

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        return self._conn.executemany(sql, list(seq))

    def commit(self) -> None:
        self._conn.commit()

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return list(self.execute(sql, params).fetchall())
