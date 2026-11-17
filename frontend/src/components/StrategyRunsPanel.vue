<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useDeskStore } from '../stores/desk'
import type { StrategyRun } from '../api/client'

const desk = useDeskStore()
const selectedId = ref<number | null>(null)
const busy = ref(false)

const schedHint = computed(() => {
  const s = desk.scheduler
  if (!s) return ''
  if (!s.enabled) return '自动计划未启用'
  const every =
    s.interval_sec >= 60 ? `${Math.round(s.interval_sec / 60)} 分钟` : `${s.interval_sec} 秒`
  const session = s.in_session ? '开盘中' : '等待开盘'
  const next = s.next_due_at ? ` · 下次 ${s.next_due_at.replace('T', ' ').slice(5, 19)}` : ''
  return `自动 ${every} · ${session}${next}`
})

async function run() {
  busy.value = true
  desk.lastError = null
  try {
    await desk.runStrategy()
  } catch (e) {
    desk.lastError = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

watch(
  () => desk.strategyRuns.map((r) => r.id).join(','),
  () => {
    if (!desk.strategyRuns.length) {
      selectedId.value = null
      return
    }
    if (!selectedId.value || !desk.strategyRuns.some((r) => r.id === selectedId.value)) {
      selectedId.value = desk.strategyRuns[0]?.id ?? null
    }
  },
  { immediate: true },
)

const selected = computed(
  () => desk.strategyRuns.find((r) => r.id === selectedId.value) || desk.strategyRuns[0] || null,
)

const analysisRows = computed(() => {
  const a = selected.value?.analysis
  if (!a) return []
  return [
    { label: '①情绪周期', text: a.emotion_cycle || '' },
    { label: '②盘口指标', text: a.tape_metrics || '' },
    { label: '③主线支线', text: a.theme || '' },
    { label: '④交易模式', text: a.mode || '' },
    { label: '⑤仓位规则', text: a.position_rule || '' },
    { label: '⑥触发条件', text: a.triggers || '' },
    { label: '⑦排雷清单', text: a.risks || '' },
  ].filter((r) => r.text.trim())
})

function select(r: StrategyRun) {
  selectedId.value = r.id ?? null
}

function timeLabel(iso: string) {
  return iso.replace('T', ' ').slice(5, 19)
}
</script>

<template>
  <section class="panel" aria-labelledby="runs-title">
    <div class="head">
      <div class="head-text">
        <h2 id="runs-title">策略轮次</h2>
        <p v-if="schedHint" class="hint">{{ schedHint }} · 最新 {{ desk.strategyRuns.length }} 条</p>
        <p v-else class="hint">最新 {{ desk.strategyRuns.length }} 条</p>
      </div>
      <button type="button" class="exec" :disabled="busy || !desk.canTrade" @click="run">
        {{ busy ? '执行中…' : '一键执行' }}
      </button>
    </div>
    <p v-if="!desk.canTrade" class="warn">当前不可交易：{{ desk.runtime?.reason || '等待行情' }}</p>
    <p v-if="desk.scheduler?.last_error" class="warn">自动轮次错误：{{ desk.scheduler.last_error }}</p>
    <p v-if="desk.lastError" class="warn" role="alert">{{ desk.lastError }}</p>
    <p v-if="desk.lastFlash" class="flash" role="status">{{ desk.lastFlash }}</p>

    <p v-if="!desk.strategyRuns.length" class="empty">尚无策略记录。一键执行或等待自动计划。</p>

    <div v-else class="body">
      <div class="list" role="list" aria-label="最近策略轮次">
        <button
          v-for="r in desk.strategyRuns"
          :key="r.id ?? r.ran_at"
          type="button"
          class="run"
          role="listitem"
          :class="{ on: r.id === selected?.id }"
          @click="select(r)"
        >
          <span class="key">#{{ r.id ?? '—' }}</span>
          <span class="meta mono">{{ timeLabel(r.ran_at) }}</span>
          <span class="stats">
            {{ r.desk_name || r.model || desk.activeDeskId }} · 成交 {{ r.filled_count }} · 信号
            {{ r.signals.length }}
          </span>
          <span class="thesis">{{ r.thesis || '（无定调）' }}</span>
        </button>
      </div>

      <div v-if="selected" class="detail" aria-live="polite">
        <h3>详情 #{{ selected.id }}</h3>
        <p class="thesis-full">{{ selected.thesis || '（无定调）' }}</p>
        <p class="meta-line">
          {{ selected.ran_at.replace('T', ' ').slice(0, 19) }}
          · 拒单 {{ selected.rejected_count }}
          <template v-if="selected.analysis?.mode"> · {{ selected.analysis.mode }}</template>
        </p>

        <dl v-if="analysisRows.length" class="analysis">
          <div v-for="row in analysisRows" :key="row.label" class="arow">
            <dt>{{ row.label }}</dt>
            <dd>{{ row.text }}</dd>
          </div>
        </dl>

        <ul v-if="selected.signals.length" class="sigs">
          <li v-for="(s, i) in selected.signals" :key="`${s.symbol}-${i}`">
            <span class="side" :class="s.side">{{ s.side === 'buy' ? '买' : '卖' }}</span>
            <span class="name">{{ s.name }}</span>
            <span class="mono">{{ s.qty }}</span>
            <span class="why">{{ s.rationale }}</span>
          </li>
        </ul>
        <p v-else class="empty">本轮无有效信号</p>
        <p class="disc">{{ selected.disclaimer }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.panel {
  background: var(--panel);
  padding: 14px 16px;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
}

.head-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

h2 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-muted);
}

.exec {
  appearance: none;
  border: 1px solid var(--shell);
  background: var(--shell);
  color: var(--platform);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 14px;
  border-radius: 4px;
  cursor: pointer;
  flex-shrink: 0;
}

.exec:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.warn,
.flash {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  flex-shrink: 0;
}

.warn {
  color: var(--crimson);
}

.flash {
  color: var(--ink);
}

h3 {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-muted);
}

.hint,
.empty,
.meta-line,
.disc {
  margin: 0;
  font-size: 12px;
  color: var(--ink-muted);
  line-height: 1.45;
}

.body {
  flex: 1 1 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
}

.list {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  max-height: min(22vh, 168px);
  min-height: 5.5rem;
  overflow: auto;
  border: 1px solid var(--hairline, var(--seam));
  border-radius: 4px;
  background: rgba(11, 31, 58, 0.02);
}

.run {
  display: grid;
  grid-template-columns: 3.2em 7.5em minmax(0, 1fr);
  align-items: baseline;
  column-gap: 8px;
  row-gap: 0;
  width: 100%;
  text-align: left;
  appearance: none;
  border: 0;
  border-bottom: 1px solid var(--hairline, var(--seam));
  background: transparent;
  color: inherit;
  font: inherit;
  padding: 6px 8px;
  cursor: pointer;
  flex-shrink: 0;
}

.run:last-child {
  border-bottom: 0;
}

.run.on {
  background: var(--select-tint, rgba(0, 0, 0, 0.04));
  outline: 1px solid var(--amber, #f5a623);
  outline-offset: -1px;
}

.key {
  font-weight: 700;
  font-size: 12px;
}

.meta {
  font-size: 11px;
  color: var(--ink-muted);
  font-variant-numeric: tabular-nums;
}

.stats {
  font-size: 11px;
  color: var(--ink-muted);
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thesis {
  grid-column: 1 / -1;
  font-size: 11px;
  color: var(--ink);
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.detail {
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
  padding: 14px 16px 16px;
  background: #fff;
  border: 1px solid var(--seam);
  border-radius: 4px;
  outline: 1px solid rgba(245, 166, 35, 0.35);
  outline-offset: -1px;
}

.thesis-full {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.45;
  color: var(--ink);
  letter-spacing: 0.01em;
}

.meta-line {
  margin-bottom: 10px;
  font-size: 12px;
}

.analysis {
  margin: 10px 0 4px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 0;
  border-top: 1px solid var(--hairline);
  border-bottom: 1px solid var(--hairline);
}

.arow {
  display: grid;
  grid-template-columns: 5.5em minmax(0, 1fr);
  gap: 4px 12px;
  font-size: 13px;
  line-height: 1.5;
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

.sigs {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sigs li {
  display: grid;
  grid-template-columns: 28px 1fr auto;
  grid-template-rows: auto auto;
  gap: 2px 8px;
  font-size: 13px;
  padding: 8px 0;
  border-bottom: 1px solid var(--hairline);
}

.side {
  grid-row: 1 / span 2;
  align-self: center;
  font-weight: 700;
  font-size: 12px;
}

.side.buy {
  color: var(--crimson);
}

.side.sell {
  color: var(--leaf, #2e7d32);
}

.name {
  font-weight: 600;
}

.mono {
  font-variant-numeric: tabular-nums;
  color: var(--ink-muted);
}

.why {
  grid-column: 2 / span 2;
  font-size: 12px;
  color: var(--ink-muted);
}

.disc {
  margin-top: 8px;
}
</style>
