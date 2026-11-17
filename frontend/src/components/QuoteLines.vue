<script setup lang="ts">
import { computed } from 'vue'
import { useDeskStore } from '../stores/desk'

const desk = useDeskStore()

const poolCount = computed(() => desk.quotes.length)

function formatPct(v: number) {
  const sign = v > 0 ? '+' : v < 0 ? '−' : ''
  const abs = Math.abs(v).toFixed(2)
  return `${sign}${abs}%`
}

function lampShort(state: string) {
  if (state === 'degraded') return '降'
  if (state === 'halted') return '熔'
  if (state === 'closed') return '收'
  return '正'
}

function lampTitle(state: string) {
  if (state === 'degraded') return '线路降级'
  if (state === 'halted') return '线路熔断'
  if (state === 'closed') return '收市'
  return '正常'
}
</script>

<template>
  <section class="panel" aria-labelledby="quotes-title">
    <header class="panel-head">
      <h2 id="quotes-title">热度池报价</h2>
      <span class="count mono" aria-live="polite">{{ poolCount }}</span>
    </header>

    <div class="table" role="listbox" aria-label="股票报价">
      <div class="cols-head" aria-hidden="true">
        <span class="h-name">标的</span>
        <span class="h-last">最新</span>
        <span class="h-pct">涨跌</span>
        <span class="h-lamp">态</span>
      </div>

      <div class="lines">
        <button
          v-for="q in desk.quotes"
          :key="q.symbol"
          type="button"
          role="option"
          class="line"
          :class="{ active: q.symbol === desk.selectedSymbol }"
          :aria-selected="q.symbol === desk.selectedSymbol"
          :title="`${q.name} ${q.symbol} · ${lampTitle(q.line_state)}`"
          @click="desk.selectSymbol(q.symbol)"
        >
          <span class="swatch" :style="{ background: q.color }" aria-hidden="true" />
          <span class="id">
            <span class="name">{{ q.name }}</span>
            <span class="sym mono">{{ q.symbol }}</span>
          </span>
          <span class="mono last">{{ q.last.toFixed(2) }}</span>
          <span class="mono pct" :class="q.pct_chg >= 0 ? 'up' : 'dn'">{{ formatPct(q.pct_chg) }}</span>
          <span class="lamp" :class="q.line_state" :title="lampTitle(q.line_state)">
            <span class="dot" aria-hidden="true" />
            <span class="lamp-txt">{{ lampShort(q.line_state) }}</span>
          </span>
        </button>
      </div>

      <p v-if="!desk.quotes.length" class="empty">暂无报价 · 等待行情服务</p>
    </div>
  </section>
</template>

<style scoped>
.panel {
  --row-h: 16px;
  --cols: 5px minmax(0, 1fr) 3.85em 3.55em 1.3em;
  background: var(--panel);
  padding: 8px 10px 6px;
  min-height: 0;
  flex: 1 1 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 3px;
  flex-shrink: 0;
}

h2 {
  margin: 0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-muted);
}

.count {
  font-size: 10px;
  color: var(--ink-muted);
  font-weight: 600;
}

.table {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
  overflow: hidden;
  width: 100%;
}

.cols-head {
  display: grid;
  grid-template-columns: var(--cols);
  gap: 4px;
  flex-shrink: 0;
  padding: 0 2px 2px;
  border-bottom: 1px solid var(--hairline);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--ink-muted);
}

.h-last,
.h-pct,
.h-lamp {
  text-align: right;
}

.lines {
  display: flex;
  flex-direction: column;
  overflow: auto;
  min-height: 0;
  flex: 1;
}

.line {
  display: grid;
  grid-template-columns: var(--cols);
  align-items: center;
  gap: 4px;
  width: 100%;
  height: var(--row-h);
  flex: 0 0 var(--row-h);
  padding: 0 2px;
  border: 0;
  border-bottom: 1px solid var(--hairline);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color 140ms ease-out, outline-color 140ms ease-out;
}

.line.active {
  background: var(--select-tint);
  outline: 1px solid var(--amber);
  outline-offset: -1px;
}

.line:hover:not(.active) {
  background: rgba(11, 31, 58, 0.04);
}

.swatch {
  width: 5px;
  height: 10px;
  border-radius: 1px;
  justify-self: center;
}

.id {
  display: flex;
  align-items: baseline;
  gap: 5px;
  min-width: 0;
}

.name {
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.sym {
  flex-shrink: 0;
  font-size: 9px;
  font-weight: 500;
  color: var(--ink-muted);
  letter-spacing: 0.01em;
}

.last,
.pct {
  font-size: 11px;
  text-align: right;
  font-weight: 600;
  line-height: 1;
}

.lamp {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 2px;
  min-width: 0;
}

.dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--leaf);
  flex-shrink: 0;
}

.lamp.degraded .dot {
  background: var(--amber);
}

.lamp.halted .dot {
  background: var(--crimson);
}

.lamp.closed .dot {
  background: rgba(11, 31, 58, 0.35);
}

.lamp-txt {
  font-size: 9px;
  font-weight: 600;
  color: var(--ink-muted);
  letter-spacing: 0.02em;
}

.empty {
  margin: 12px 2px 0;
  color: var(--ink-muted);
  font-size: 12px;
}

@media (max-width: 960px) {
  .panel {
    --row-h: auto;
    --cols: 5px minmax(0, 1fr) 4em 3.8em 1.5em;
    padding: 10px 12px;
  }

  .line {
    height: auto;
    flex: none;
    padding: 5px 2px;
  }

  .swatch {
    height: 14px;
  }

  .name {
    font-size: 13px;
  }

  .last,
  .pct {
    font-size: 12px;
  }
}
</style>
