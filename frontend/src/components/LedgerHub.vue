<script setup lang="ts">
import { computed } from 'vue'
import { useDeskStore } from '../stores/desk'

const desk = useDeskStore()

function money(n: number | undefined | null) {
  if (n == null) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function price(n: number | undefined | null) {
  if (n == null || Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 3 })
}

function signedMoney(n: number | undefined | null) {
  if (n == null) return '—'
  const sign = n > 0 ? '+' : n < 0 ? '−' : ''
  return `${sign}${Math.abs(n).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function signedPct(n: number | undefined | null) {
  if (n == null) return ''
  const sign = n > 0 ? '+' : n < 0 ? '−' : ''
  return `${sign}${Math.abs(n).toFixed(2)}%`
}

function pnlClass(n: number | undefined | null) {
  if (n == null || n === 0) return 'flat'
  return n > 0 ? 'up' : 'dn'
}

const focusPos = computed(() =>
  desk.positions.find((p) => p.symbol === desk.selectedSymbol) || null,
)

const focusName = computed(() => desk.selectedQuote?.name || focusPos.value?.name || '标的')

const openPositions = computed(() =>
  [...desk.positions].sort((a, b) => Math.abs(b.pnl_unrealized) - Math.abs(a.pnl_unrealized)),
)

const STATUS_ZH: Record<string, string> = {
  filled: '成交',
  rejected: '拒单',
  open: '挂起',
  accepted: '已受理',
  cancelled: '已撤',
}

function statusLabel(status: string) {
  return STATUS_ZH[status] || status
}

function statusClass(status: string) {
  return status === 'rejected' ? 'rej' : status === 'filled' ? 'ok' : 'neutral'
}
</script>

<template>
  <section class="panel" aria-labelledby="ledger-title">
    <h2 id="ledger-title">账本枢纽</h2>

    <div class="pnl-hero">
      <span>总盈亏</span>
      <b class="mono" :class="pnlClass(desk.account?.pnl_total)">
        {{ signedMoney(desk.account?.pnl_total) }}
        <small v-if="desk.account">{{ signedPct(desk.account.pnl_pct) }}</small>
      </b>
    </div>

    <div class="grid-stats">
      <div class="stat">
        <span>浮动</span>
        <b class="mono" :class="pnlClass(desk.account?.pnl_unrealized)">{{
          signedMoney(desk.account?.pnl_unrealized)
        }}</b>
      </div>
      <div class="stat">
        <span>已实现</span>
        <b class="mono" :class="pnlClass(desk.account?.pnl_realized)">{{
          signedMoney(desk.account?.pnl_realized)
        }}</b>
      </div>
      <div class="stat">
        <span>权益</span>
        <b class="mono">{{ money(desk.account?.equity) }}</b>
      </div>
      <div class="stat">
        <span>现金</span>
        <b class="mono">{{ money(desk.account?.cash) }}</b>
      </div>
      <div class="stat">
        <span>市值</span>
        <b class="mono">{{ money(desk.account?.market_value) }}</b>
      </div>
      <div class="stat">
        <span>费用</span>
        <b class="mono">{{ money(desk.account?.fees_total) }}</b>
      </div>
    </div>

    <div class="focus">
      <div class="stat wide">
        <span>{{ focusName }} · 仓/可卖</span>
        <b class="mono">{{ focusPos ? focusPos.qty : 0 }}/{{ focusPos ? focusPos.qty_sellable : 0 }}</b>
      </div>
      <template v-if="focusPos">
        <div class="stat">
          <span>成本</span>
          <b class="mono">{{ price(focusPos.avg_cost) }}</b>
        </div>
        <div class="stat">
          <span>现价</span>
          <b class="mono">{{ price(focusPos.last) }}</b>
        </div>
        <div class="stat wide">
          <span>浮动</span>
          <b class="mono" :class="pnlClass(focusPos.pnl_unrealized)">
            {{ signedMoney(focusPos.pnl_unrealized) }}
            <small>{{ signedPct(focusPos.pnl_pct) }}</small>
          </b>
        </div>
      </template>
    </div>

    <div v-if="openPositions.length" class="pos">
      <h3>持仓</h3>
      <ul>
        <li v-for="p in openPositions" :key="p.symbol">
          <button type="button" class="pos-row" @click="desk.selectSymbol(p.symbol)">
            <span class="name">{{ p.name }}</span>
            <span class="mono qty">{{ p.qty }}/{{ p.qty_sellable }}</span>
            <span class="mono pnl" :class="pnlClass(p.pnl_unrealized)">{{
              signedMoney(p.pnl_unrealized)
            }}</span>
          </button>
        </li>
      </ul>
    </div>

    <div v-if="desk.orders.length" class="orders">
      <h3>近单</h3>
      <ul>
        <li v-for="o in desk.orders.slice(0, 5)" :key="o.id">
          <span class="mono">#{{ o.id }}</span>
          {{ o.side === 'buy' ? '买' : '卖' }}
          {{ o.qty }}
          <span :class="statusClass(o.status)">{{ statusLabel(o.status) }}</span>
        </li>
      </ul>
    </div>

    <p class="note">仅本地模拟 · 总盈亏=权益−初始</p>
  </section>
</template>

<style scoped>
.panel {
  background: var(--panel);
  padding: 10px 12px;
  min-height: 0;
  overflow: auto;
}

h2 {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-muted);
}

h3 {
  margin: 10px 0 4px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-muted);
}

.pnl-hero {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  padding: 6px 0 8px;
  border-bottom: 1px solid var(--seam);
  font-size: 11px;
  color: var(--ink-muted);
}

.pnl-hero b {
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
  white-space: nowrap;
}

.pnl-hero small {
  margin-left: 4px;
  font-size: 11px;
  font-weight: 600;
  opacity: 0.9;
}

.grid-stats,
.focus {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
}

.stat {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 6px;
  padding: 5px 0;
  border-bottom: 1px solid var(--hairline);
  font-size: 11px;
  color: var(--ink-muted);
}

.stat.wide {
  grid-column: 1 / -1;
}

.stat b {
  font-weight: 600;
  font-size: 11px;
  color: var(--ink);
  white-space: nowrap;
}

.stat b small {
  margin-left: 4px;
  font-size: 10px;
  opacity: 0.9;
}

.focus {
  margin-top: 2px;
  padding-top: 2px;
}

.up {
  color: var(--crimson) !important;
}

.dn {
  color: var(--leaf) !important;
}

.flat {
  color: var(--ink) !important;
}

.pos ul,
.orders ul {
  list-style: none;
  margin: 0;
  padding: 0;
}

.pos-row {
  appearance: none;
  border: 0;
  border-bottom: 1px solid var(--hairline);
  background: transparent;
  color: inherit;
  font: inherit;
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 6px;
  align-items: baseline;
  padding: 5px 0;
  cursor: pointer;
  text-align: left;
  font-size: 11px;
}

.pos-row .name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pos-row .qty {
  color: var(--ink-muted);
}

.pos-row .pnl {
  font-weight: 600;
  text-align: right;
  min-width: 4.5em;
}

.orders li {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 11px;
  padding: 4px 0;
  border-bottom: 1px solid var(--hairline);
  color: var(--ink);
}

.rej,
.ok,
.neutral {
  margin-left: auto;
}

.rej {
  color: var(--crimson);
}

.ok {
  color: var(--leaf);
}

.neutral {
  color: var(--ink-muted);
}

.note {
  margin-top: 8px;
  font-size: 10px;
  line-height: 1.35;
  color: var(--ink-muted);
}

.mono {
  font-variant-numeric: tabular-nums;
}
</style>
