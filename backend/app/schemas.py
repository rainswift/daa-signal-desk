from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str


class RuntimeOut(BaseModel):
    state: Literal["normal", "degraded", "halted", "closed"]
    reason: str
    quote_age_max_sec: Optional[float] = None
    updated_at: str
    force_session: bool = False


class QuoteOut(BaseModel):
    symbol: str
    name: str
    last: float
    pct_chg: float
    age_sec: float
    line_state: Literal["normal", "degraded", "halted", "closed"]
    color: str
    fetched_at: str


class AccountOut(BaseModel):
    desk_id: str = "deepseek"
    cash: float
    market_value: float
    fees_total: float
    equity: float
    initial_cash: float = 0.0
    pnl_total: float = 0.0
    pnl_unrealized: float = 0.0
    pnl_realized: float = 0.0
    pnl_pct: float = 0.0


class DeskSummaryOut(BaseModel):
    id: str
    name: str
    model: str
    cash: float
    market_value: float
    equity: float
    initial_cash: float
    pnl_total: float
    pnl_pct: float
    fees_total: float


class DesksOut(BaseModel):
    desks: list[DeskSummaryOut]
    leader_id: Optional[str] = None


class PositionOut(BaseModel):
    symbol: str
    name: str
    qty: int
    qty_sellable: int
    cost: float
    avg_cost: float = 0.0
    last: float = 0.0
    mkt_value: float
    pnl_unrealized: float = 0.0
    pnl_pct: float = 0.0


class OrderOut(BaseModel):
    id: int
    desk_id: str = "deepseek"
    symbol: str
    side: Literal["buy", "sell"]
    qty: int
    type: Literal["limit", "market"]
    limit_price: Optional[float] = None
    status: str
    reason: Optional[str] = None
    fill_price: Optional[float] = None
    created_at: str
    updated_at: str


class OrderCreate(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    qty: int = Field(gt=0)
    type: Literal["limit", "market"] = "market"
    limit: Optional[float] = None


class WeekItem(BaseModel):
    week_key: str
    week_start: str
    week_end: str
    has_report: bool


class WeeksOut(BaseModel):
    year: int
    weeks: list[WeekItem]


class WeeklyReportOut(BaseModel):
    week_key: str
    week_start: str
    week_end: str
    stats: dict
    content_md: str
    model: str
    data_source: str
    created_at: str


class StrategySignalOut(BaseModel):
    symbol: str
    name: str
    side: Literal["buy", "sell"]
    qty: int
    order_type: Literal["market", "limit"]
    limit: Optional[float] = None
    rationale: str = ""


class StrategyAnalysisOut(BaseModel):
    emotion_cycle: str = ""
    tape_metrics: str = ""
    theme: str = ""
    mode: str = ""
    position_rule: str = ""
    triggers: str = ""
    risks: str = ""


class StrategyOrderOut(BaseModel):
    id: Optional[int] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    qty: Optional[int] = None
    status: Optional[str] = None
    reason: Optional[str] = None
    fill_price: Optional[float] = None


class StrategyRunOut(BaseModel):
    id: Optional[int] = None
    desk_id: str = "deepseek"
    desk_name: str = ""
    ran_at: str
    thesis: str = ""
    analysis: StrategyAnalysisOut = Field(default_factory=StrategyAnalysisOut)
    model: str = ""
    data_source: str = ""
    disclaimer: str = "【仅思路推演，不构成投资建议】· 仅本地模拟"
    signals: list[StrategySignalOut] = []
    skipped: list[dict] = []
    orders: list[StrategyOrderOut] = []
    filled_count: int = 0
    rejected_count: int = 0


class StrategyRunsOut(BaseModel):
    runs: list[StrategyRunOut]


class StrategySchedulerOut(BaseModel):
    desk_id: str = "deepseek"
    enabled: bool
    only_in_session: bool
    interval_sec: int
    running: bool
    in_session: bool
    busy: bool
    last_ran_at: Optional[str] = None
    last_ok: Optional[bool] = None
    last_error: Optional[str] = None
    next_due_at: Optional[str] = None
    last_filled: Optional[int] = None


class StrategySchedulersOut(BaseModel):
    schedulers: list[StrategySchedulerOut]

