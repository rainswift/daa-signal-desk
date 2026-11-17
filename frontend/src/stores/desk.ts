import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  client,
  type Account,
  type DeskSummary,
  type Order,
  type Position,
  type Quote,
  type Runtime,
  type StrategyRun,
  type StrategyScheduler,
} from '../api/client'

const DESK_STORAGE_KEY = 'daa.activeDeskId'

export const useDeskStore = defineStore('desk', () => {
  const runtime = ref<Runtime | null>(null)
  const quotes = ref<Quote[]>([])
  const desks = ref<DeskSummary[]>([])
  const leaderId = ref<string | null>(null)
  const activeDeskId = ref<string>(localStorage.getItem(DESK_STORAGE_KEY) || 'deepseek')
  const account = ref<Account | null>(null)
  const positions = ref<Position[]>([])
  const orders = ref<Order[]>([])
  const strategyRun = ref<StrategyRun | null>(null)
  const strategyRuns = ref<StrategyRun[]>([])
  const schedulers = ref<StrategyScheduler[]>([])
  const orderFormOpen = ref(false)
  const selectedSymbol = ref('300308')
  const lastError = ref<string | null>(null)
  const lastFlash = ref<string | null>(null)
  const loading = ref(false)

  const selectedQuote = computed(() => quotes.value.find((q) => q.symbol === selectedSymbol.value) || null)
  const canTrade = computed(() => runtime.value?.state === 'normal')
  const activeDesk = computed(
    () => desks.value.find((d) => d.id === activeDeskId.value) || desks.value[0] || null,
  )
  const scheduler = computed(
    () => schedulers.value.find((s) => s.desk_id === activeDeskId.value) || schedulers.value[0] || null,
  )

  function persistDesk(id: string) {
    activeDeskId.value = id
    localStorage.setItem(DESK_STORAGE_KEY, id)
  }

  async function refreshDesks() {
    const out = await client.desks()
    desks.value = out.desks || []
    leaderId.value = out.leader_id
    if (desks.value.length && !desks.value.some((d) => d.id === activeDeskId.value)) {
      persistDesk(desks.value[0].id)
    }
  }

  async function refreshQuotes() {
    const [rt, qs, deskOut, schedOut] = await Promise.all([
      client.runtime(),
      client.quotes(),
      client.desks(),
      client.strategyScheduler().catch(() => null),
    ])
    runtime.value = rt
    quotes.value = qs
    desks.value = deskOut.desks || []
    leaderId.value = deskOut.leader_id
    if (desks.value.length && !desks.value.some((d) => d.id === activeDeskId.value)) {
      persistDesk(desks.value[0].id)
    }
    if (schedOut) schedulers.value = schedOut.schedulers || []

    const [acct, pos] = await Promise.all([
      client.account(activeDeskId.value),
      client.positions(activeDeskId.value),
    ])
    account.value = acct
    positions.value = pos

    const sched = scheduler.value
    if (sched?.last_ran_at && (!strategyRun.value || strategyRun.value.ran_at !== sched.last_ran_at)) {
      try {
        strategyRun.value = await client.strategyLatest(activeDeskId.value)
        await refreshStrategyRuns()
        await refreshLedger()
      } catch {
        /* 尚无记录时忽略 */
      }
    }
  }

  async function refreshStrategyRuns() {
    try {
      const out = await client.strategyRuns(10, activeDeskId.value)
      strategyRuns.value = out.runs || []
      if (strategyRuns.value[0]) {
        strategyRun.value = strategyRuns.value[0]
      }
    } catch {
      strategyRuns.value = []
    }
  }

  async function refreshLedger() {
    const [acct, pos, ords] = await Promise.all([
      client.account(activeDeskId.value),
      client.positions(activeDeskId.value),
      client.orders(50, activeDeskId.value),
    ])
    account.value = acct
    positions.value = pos
    orders.value = ords
  }

  async function selectDesk(id: string) {
    if (id === activeDeskId.value) return
    persistDesk(id)
    lastError.value = null
    lastFlash.value = null
    strategyRun.value = null
    strategyRuns.value = []
    await Promise.all([refreshLedger(), refreshStrategyRuns(), refreshDesks()])
    if (!strategyRuns.value.length) {
      strategyRun.value = null
    }
  }

  async function bootstrap() {
    loading.value = true
    lastError.value = null
    try {
      await Promise.all([refreshQuotes(), refreshLedger()])
      if (quotes.value.length && !quotes.value.some((q) => q.symbol === selectedSymbol.value)) {
        selectedSymbol.value = quotes.value[0].symbol
      }
      await refreshStrategyRuns()
      if (!strategyRuns.value.length) {
        strategyRun.value = null
      }
    } catch (e) {
      lastError.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function runStrategy() {
    lastError.value = null
    lastFlash.value = null
    const result = await client.runStrategy(activeDeskId.value)
    strategyRun.value = result
    await refreshStrategyRuns()
    await refreshLedger()
    await refreshDesks()
    await refreshQuotes()
    lastFlash.value = `策略轮次完成：成交 ${result.filled_count}，拒单 ${result.rejected_count}`
    return result
  }

  function toggleOrderForm(open?: boolean) {
    orderFormOpen.value = open ?? !orderFormOpen.value
  }

  async function placeOrder(payload: {
    side: 'buy' | 'sell'
    qty: number
    type: 'limit' | 'market'
    limit?: number
  }) {
    lastError.value = null
    lastFlash.value = null
    const order = await client.placeOrder(
      {
        symbol: selectedSymbol.value,
        ...payload,
      },
      activeDeskId.value,
    )
    await refreshLedger()
    await refreshDesks()
    await refreshQuotes()
    if (order.status === 'rejected') {
      lastError.value = order.reason || '拒单'
    } else if (order.status === 'filled') {
      lastFlash.value = `成交 ${order.side === 'buy' ? '买入' : '卖出'} ${order.qty} @ ${order.fill_price}`
    } else if (order.status === 'open') {
      lastFlash.value = '限价单已挂起，等待触达'
    }
    return order
  }

  function selectSymbol(symbol: string) {
    selectedSymbol.value = symbol
  }

  return {
    runtime,
    quotes,
    desks,
    leaderId,
    activeDeskId,
    activeDesk,
    account,
    positions,
    orders,
    strategyRun,
    strategyRuns,
    schedulers,
    scheduler,
    orderFormOpen,
    selectedSymbol,
    selectedQuote,
    canTrade,
    lastError,
    lastFlash,
    loading,
    bootstrap,
    refreshQuotes,
    refreshLedger,
    refreshStrategyRuns,
    refreshDesks,
    selectDesk,
    placeOrder,
    runStrategy,
    selectSymbol,
    toggleOrderForm,
  }
})
