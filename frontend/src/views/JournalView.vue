<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useDeskStore } from '../stores/desk'
import { useJournalStore } from '../stores/journal'

const journal = useJournalStore()
const desk = useDeskStore()
/** ①–⑦ 情绪推演默认折叠 */
const analysisOpen = ref(false)

watch(
  () => journal.selectedId,
  () => {
    analysisOpen.value = false
  },
)

onMounted(async () => {
  if (!desk.desks.length) {
    try {
      await desk.refreshDesks()
    } catch {
      /* 柜台未启动时记录页仍可尝试 load */
    }
  }
  void journal.load()
})

const selectedAnalysisRows = computed(() => {
  const a = journal.selected?.analysis
  if (!a) return []
  const rows = [
    { label: '①情绪周期', text: a.emotion_cycle || '' },
    { label: '②盘口指标', text: a.tape_metrics || '' },
    { label: '③主线支线', text: a.theme || '' },
    { label: '④交易模式', text: a.mode || '' },
    { label: '⑤仓位规则', text: a.position_rule || '' },
    { label: '⑥触发条件', text: a.triggers || '' },
    { label: '⑦排雷清单', text: a.risks || '' },
  ]
  return rows.filter((r) => r.text.trim())
})

const STATUS_ZH: Record<string, string> = {
  filled: '成交',
  rejected: '拒单',
  open: '挂起',
  accepted: '已受理',
  cancelled: '已撤',
}

function statusLabel(s: string) {
  return STATUS_ZH[s] || s
}

function statusClass(s: string) {
  if (s === 'filled') return 'ok'
  if (s === 'rejected') return 'rej'
  return 'neutral'
}

function skipSymbol(sk: Record<string, unknown>) {
  const v = sk.symbol
  return typeof v === 'string' || typeof v === 'number' ? String(v) : '—'
}

function skipReason(sk: Record<string, unknown>) {
  const v = sk.reason
  return typeof v === 'string' ? v : JSON.stringify(sk)
}
</script>

<template>
  <div class="journal">
    <header class="top">
      <h1>交易与策略记录</h1>
      <p class="disc">本地账本流水 · 双模型可追溯 · 非投资建议</p>
      <div class="filters" role="tablist" aria-label="按策略台筛选">
        <button
          type="button"
          class="chip"
          :class="{ on: journal.filterDeskId === 'all' }"
          @click="journal.setFilterDesk('all')"
        >
          全部
        </button>
        <button
          v-for="d in desk.desks"
          :key="d.id"
          type="button"
          class="chip"
          :class="{ on: journal.filterDeskId === d.id }"
          @click="journal.setFilterDesk(d.id)"
        >
          {{ d.name }}
        </button>
      </div>
      <button type="button" class="refresh" :disabled="journal.loading" @click="journal.load()">
        {{ journal.loading ? '刷新中…' : '刷新' }}
      </button>
    </header>

    <p v-if="journal.error" class="err" role="alert">{{ journal.error }}</p>

    <div class="body">
      <aside class="runs" aria-label="策略轮次">
        <h2>策略轮次</h2>
        <p v-if="journal.loading && !journal.runs.length" class="muted">加载中…</p>
        <p v-else-if="!journal.runs.length" class="muted">尚无策略记录。请先在策略台一键执行。</p>
        <button
          v-for="r in journal.runs"
          :key="r.id ?? r.ran_at"
          type="button"
          class="run"
          :class="{ on: r.id === journal.selectedId }"
          @click="journal.selectRun(r.id ?? null)"
        >
          <span class="key">#{{ r.id ?? '—' }}</span>
          <span class="desk-tag">{{ r.desk_name || r.desk_id || '—' }}</span>
          <span class="meta mono">{{ r.ran_at.replace('T', ' ').slice(0, 16) }}</span>
          <span class="stats">成交 {{ r.filled_count }} · 信号 {{ r.signals.length }}</span>
          <span class="thesis">{{ r.thesis || '（无定调）' }}</span>
        </button>
      </aside>

      <section class="detail" aria-live="polite">
        <template v-if="journal.selected">
          <h2>策略详情 #{{ journal.selected.id }}</h2>
          <p class="thesis">{{ journal.selected.thesis || '（无定调）' }}</p>
          <p class="muted">
            {{ journal.selected.desk_name || journal.selected.desk_id }} ·
            {{ journal.selected.ran_at }} · {{ journal.selected.model }} · 成交
            {{ journal.selected.filled_count }} / 拒单 {{ journal.selected.rejected_count }}
          </p>

          <div v-if="selectedAnalysisRows.length" class="analysis-wrap">
            <button
              type="button"
              class="analysis-toggle"
              :aria-expanded="analysisOpen"
              @click="analysisOpen = !analysisOpen"
            >
              {{ analysisOpen ? '收起情绪推演' : '展开情绪推演' }}
              <span class="chev" aria-hidden="true">{{ analysisOpen ? '▴' : '▾' }}</span>
            </button>
            <dl v-show="analysisOpen" class="analysis">
              <div v-for="row in selectedAnalysisRows" :key="row.label" class="arow">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.text }}</dd>
              </div>
            </dl>
          </div>

          <h3>信号</h3>
          <ul v-if="journal.selected.signals.length" class="list">
            <li v-for="(s, i) in journal.selected.signals" :key="`${s.symbol}-${i}`">
              <span class="side" :class="s.side">{{ s.side === 'buy' ? '买' : '卖' }}</span>
              <span class="name">{{ s.name }} {{ s.symbol }}</span>
              <span class="mono">{{ s.qty }}</span>
              <span class="why">{{ s.rationale }}</span>
            </li>
          </ul>
          <p v-else class="muted">本轮无信号</p>

          <h3>本轮订单</h3>
          <ul v-if="journal.selected.orders.length" class="list">
            <li v-for="o in journal.selected.orders" :key="o.id ?? `${o.symbol}-${o.qty}`">
              <span class="mono">#{{ o.id }}</span>
              <span>{{ o.side === 'buy' ? '买' : '卖' }} {{ o.symbol }} × {{ o.qty }}</span>
              <span :class="statusClass(o.status || '')">{{ statusLabel(o.status || '') }}</span>
              <span class="mono" v-if="o.fill_price != null">@ {{ o.fill_price }}</span>
              <span class="why" v-if="o.reason">{{ o.reason }}</span>
            </li>
          </ul>
          <p v-else class="muted">本轮无订单</p>

          <template v-if="journal.selected.skipped.length">
            <h3>跳过</h3>
            <ul class="list">
              <li v-for="(sk, i) in journal.selected.skipped" :key="i">
                <span class="mono">{{ skipSymbol(sk) }}</span>
                <span class="why">{{ skipReason(sk) }}</span>
              </li>
            </ul>
          </template>

          <p class="disc-foot">{{ journal.selected.disclaimer }}</p>
        </template>
        <p v-else class="muted">选择左侧策略轮次查看详情</p>
      </section>

      <section class="trades" aria-label="全部交易">
        <h2>全部交易</h2>
        <p v-if="!journal.orders.length" class="muted">暂无订单流水</p>
        <table v-else>
          <thead>
            <tr>
              <th>单号</th>
              <th>策略台</th>
              <th>时间</th>
              <th>方向</th>
              <th>代码</th>
              <th>数量</th>
              <th>状态</th>
              <th>成交价</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in journal.orders" :key="o.id">
              <td class="mono">#{{ o.id }}</td>
              <td>{{ o.desk_id }}</td>
              <td class="mono">{{ o.created_at.replace('T', ' ').slice(5, 16) }}</td>
              <td :class="o.side">{{ o.side === 'buy' ? '买' : '卖' }}</td>
              <td class="mono">{{ o.symbol }}</td>
              <td class="mono">{{ o.qty }}</td>
              <td :class="statusClass(o.status)">{{ statusLabel(o.status) }}</td>
              <td class="mono">{{ o.fill_price != null ? o.fill_price.toFixed(2) : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  </div>
</template>

<style scoped>
.journal {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  background: var(--platform);
}

.top {
  min-height: var(--header-h);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px 16px;
  padding: 10px 24px;
  background: var(--shell);
  color: var(--platform);
}

h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.disc {
  margin: 0;
  font-size: 12px;
  opacity: 0.75;
}

.filters {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

.chip {
  appearance: none;
  border: 1px solid rgba(232, 236, 240, 0.28);
  background: transparent;
  color: rgba(232, 236, 240, 0.8);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 10px;
  border-radius: 4px;
  cursor: pointer;
}

.chip.on {
  background: var(--select-tint);
  color: var(--shell);
  border-color: var(--amber);
}

.refresh {
  appearance: none;
  border: 1px solid rgba(232, 236, 240, 0.35);
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
}

.refresh:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.err {
  margin: 12px 24px 0;
  color: var(--crimson);
  font-size: 13px;
}

.body {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(200px, 0.9fr) minmax(260px, 1.2fr) minmax(280px, 1.1fr);
  gap: 1px;
  background: var(--seam);
  min-height: calc(100vh - var(--header-h));
}

.runs,
.detail,
.trades {
  background: var(--panel);
  padding: 18px 20px;
  overflow: auto;
  min-height: 0;
}

h2 {
  margin: 0 0 12px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-muted);
}

h3 {
  margin: 16px 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}

.muted {
  margin: 0;
  font-size: 13px;
  color: var(--ink-muted);
  line-height: 1.45;
}

.run {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 2px 8px;
  width: 100%;
  text-align: left;
  appearance: none;
  border: 0;
  border-bottom: 1px solid var(--hairline, var(--seam));
  background: transparent;
  color: inherit;
  font: inherit;
  padding: 10px 8px;
  cursor: pointer;
}

.run.on {
  background: var(--select-tint, rgba(0, 0, 0, 0.04));
  outline: 2px solid var(--amber);
  outline-offset: -2px;
}

.key {
  font-weight: 700;
  font-size: 13px;
}

.desk-tag {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-muted);
  letter-spacing: 0.02em;
}

.meta,
.stats {
  font-size: 11px;
  color: var(--ink-muted);
}

.meta {
  grid-column: 3;
}

.stats {
  grid-column: 2 / -1;
}

.thesis {
  grid-column: 1 / -1;
  font-size: 12px;
  color: var(--ink);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.detail .thesis {
  margin: 0 0 6px;
  font-size: 15px;
  display: block;
  -webkit-line-clamp: unset;
}

.analysis-wrap {
  margin: 0 0 12px;
}

.analysis-toggle {
  appearance: none;
  border: 0;
  background: transparent;
  color: var(--ink-muted);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 4px 0 8px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.analysis-toggle:hover {
  color: var(--ink);
}

.chev {
  font-size: 10px;
  opacity: 0.7;
}

.analysis {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.arow {
  display: grid;
  grid-template-columns: 5.5em 1fr;
  gap: 4px 10px;
  font-size: 12px;
  line-height: 1.45;
}

.arow dt {
  margin: 0;
  color: var(--ink-muted);
  font-weight: 600;
}

.arow dd {
  margin: 0;
  color: var(--ink);
  white-space: pre-wrap;
}

.list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.list li {
  display: grid;
  grid-template-columns: 28px 1fr auto;
  gap: 2px 8px;
  padding: 8px 0;
  border-bottom: 1px solid var(--seam);
  font-size: 13px;
}

.side.buy,
td.buy {
  color: var(--crimson);
  font-weight: 700;
}

.side.sell,
td.sell {
  color: var(--leaf, #2e7d32);
  font-weight: 700;
}

.why {
  grid-column: 2 / -1;
  font-size: 12px;
  color: var(--ink-muted);
}

.ok {
  color: var(--leaf, #2e7d32);
}

.rej {
  color: var(--crimson);
}

.neutral {
  color: var(--ink-muted);
}

.mono {
  font-variant-numeric: tabular-nums;
}

.disc-foot {
  margin-top: 16px;
  font-size: 12px;
  color: var(--ink-muted);
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

th,
td {
  text-align: left;
  padding: 8px 6px;
  border-bottom: 1px solid var(--seam);
}

th {
  color: var(--ink-muted);
  font-weight: 600;
  letter-spacing: 0.04em;
}

@media (max-width: 1100px) {
  .body {
    grid-template-columns: 1fr;
  }

  .top {
    flex-wrap: wrap;
    height: auto;
    padding: 12px 16px;
  }
}
</style>
