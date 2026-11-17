export type RuntimeState = 'normal' | 'degraded' | 'halted' | 'closed'

export interface Runtime {
  state: RuntimeState
  reason: string
  quote_age_max_sec: number | null
  updated_at: string
  force_session: boolean
}

export interface Quote {
  symbol: string
  name: string
  last: number
  pct_chg: number
  age_sec: number
  line_state: RuntimeState
  color: string
  fetched_at: string
}

export interface Account {
  desk_id: string
  cash: number
  market_value: number
  fees_total: number
  equity: number
  initial_cash: number
  pnl_total: number
  pnl_unrealized: number
  pnl_realized: number
  pnl_pct: number
}

export interface DeskSummary {
  id: string
  name: string
  model: string
  cash: number
  market_value: number
  equity: number
  initial_cash: number
  pnl_total: number
  pnl_pct: number
  fees_total: number
}

export interface DesksOut {
  desks: DeskSummary[]
  leader_id: string | null
}

export interface Position {
  symbol: string
  name: string
  qty: number
  qty_sellable: number
  cost: number
  avg_cost: number
  last: number
  mkt_value: number
  pnl_unrealized: number
  pnl_pct: number
}

export interface Order {
  id: number
  desk_id: string
  symbol: string
  side: 'buy' | 'sell'
  qty: number
  type: 'limit' | 'market'
  limit_price: number | null
  status: string
  reason: string | null
  fill_price: number | null
  created_at: string
  updated_at: string
}

export interface OrderCreate {
  symbol: string
  side: 'buy' | 'sell'
  qty: number
  type: 'limit' | 'market'
  limit?: number
}

export interface WeekItem {
  week_key: string
  week_start: string
  week_end: string
  has_report: boolean
}

export interface WeeksOut {
  year: number
  weeks: WeekItem[]
}

export interface WeeklyReport {
  week_key: string
  week_start: string
  week_end: string
  stats: Record<string, unknown>
  content_md: string
  model: string
  data_source: string
  created_at: string
}

export interface StrategySignal {
  symbol: string
  name: string
  side: 'buy' | 'sell'
  qty: number
  order_type: 'market' | 'limit'
  limit: number | null
  rationale: string
}

export interface StrategyOrder {
  id: number | null
  symbol: string | null
  side: string | null
  qty: number | null
  status: string | null
  reason: string | null
  fill_price: number | null
}

export interface StrategyAnalysis {
  emotion_cycle?: string
  tape_metrics?: string
  theme?: string
  mode?: string
  position_rule?: string
  triggers?: string
  risks?: string
}

export interface StrategyRun {
  id?: number | null
  desk_id?: string
  desk_name?: string
  ran_at: string
  thesis: string
  analysis?: StrategyAnalysis
  model: string
  data_source: string
  disclaimer: string
  signals: StrategySignal[]
  skipped: Record<string, unknown>[]
  orders: StrategyOrder[]
  filled_count: number
  rejected_count: number
}

export interface StrategyRunsOut {
  runs: StrategyRun[]
}

export interface StrategyScheduler {
  desk_id: string
  enabled: boolean
  only_in_session: boolean
  interval_sec: number
  running: boolean
  in_session: boolean
  busy: boolean
  last_ran_at: string | null
  last_ok: boolean | null
  last_error: string | null
  next_due_at: string | null
  last_filled: number | null
}

export interface StrategySchedulersOut {
  schedulers: StrategyScheduler[]
}

function detailMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object') return fallback
  const b = body as Record<string, unknown>
  if (typeof b.message === 'string') return b.message
  const d = b.detail
  if (typeof d === 'string') return d
  if (d && typeof d === 'object') {
    const o = d as Record<string, unknown>
    if (typeof o.message === 'string') return o.message
  }
  return fallback
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    let message = res.statusText
    try {
      const body = await res.json()
      message = detailMessage(body, message)
    } catch {
      /* ignore */
    }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

function withDesk(path: string, deskId?: string | null): string {
  if (!deskId) return path
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}desk_id=${encodeURIComponent(deskId)}`
}

export const client = {
  runtime: () => api<Runtime>('/api/runtime'),
  quotes: () => api<Quote[]>('/api/quotes'),
  desks: () => api<DesksOut>('/api/desks'),
  resetAllDesks: () => api<DesksOut>('/api/desks/reset-all', { method: 'POST' }),
  account: (deskId?: string) => api<Account>(withDesk('/api/account', deskId)),
  positions: (deskId?: string) => api<Position[]>(withDesk('/api/positions', deskId)),
  orders: (limit = 50, deskId?: string) =>
    api<Order[]>(withDesk(`/api/orders?limit=${limit}`, deskId)),
  placeOrder: (body: OrderCreate, deskId?: string) =>
    api<Order>(withDesk('/api/orders', deskId), { method: 'POST', body: JSON.stringify(body) }),
  resetAccount: (deskId?: string) =>
    api<Account>(withDesk('/api/account/reset', deskId), { method: 'POST' }),
  unlockT1: (deskId?: string) =>
    api<{ status: string }>(withDesk('/api/dev/unlock-t1', deskId), { method: 'POST' }),
  setStale: (seconds: number) =>
    api<Runtime>(`/api/dev/stale?seconds=${seconds}`, { method: 'POST' }),
  refresh: () => api<Runtime>('/api/dev/refresh', { method: 'POST' }),
  weeklyWeeks: () => api<WeeksOut>('/api/weekly/weeks'),
  weeklyReport: (weekKey: string) => api<WeeklyReport>(`/api/weekly/reports/${weekKey}`),
  generateWeeklyReport: (weekKey: string, force = false) =>
    api<WeeklyReport>(`/api/weekly/reports/${weekKey}?force=${force ? 'true' : 'false'}`, {
      method: 'POST',
    }),
  strategyLatest: (deskId?: string) =>
    api<StrategyRun>(withDesk('/api/strategy/latest', deskId)),
  strategyRuns: (limit = 50, deskId?: string) =>
    api<StrategyRunsOut>(withDesk(`/api/strategy/runs?limit=${limit}`, deskId)),
  strategyRun: (id: number) => api<StrategyRun>(`/api/strategy/runs/${id}`),
  strategyScheduler: (deskId?: string) =>
    api<StrategySchedulersOut>(withDesk('/api/strategy/scheduler', deskId)),
  runStrategy: (deskId?: string) =>
    api<StrategyRun>(withDesk('/api/strategy/run', deskId), { method: 'POST' }),
}
