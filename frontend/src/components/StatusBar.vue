<script setup lang="ts">
import { computed } from 'vue'
import { useDeskStore } from '../stores/desk'

const desk = useDeskStore()

const lampClass = computed(() => {
  const s = desk.runtime?.state
  if (s === 'degraded') return 'lamp amber'
  if (s === 'halted') return 'lamp crimson'
  if (s === 'closed') return 'lamp dim'
  return 'lamp leaf'
})

const statusText = computed(() => {
  const rt = desk.runtime
  if (!rt) return '运营状态 · 连接中'
  const age = rt.quote_age_max_sec != null ? ` · 报价年龄 ${Math.round(rt.quote_age_max_sec)}s` : ''
  const label =
    rt.state === 'degraded'
      ? '行情降级'
      : rt.state === 'halted'
        ? '熔断'
        : rt.state === 'closed'
          ? '收市'
          : '正常'
  return `运营状态 · ${label}${age}`
})

function signedPct(n: number) {
  const sign = n > 0 ? '+' : n < 0 ? '−' : ''
  return `${sign}${Math.abs(n).toFixed(2)}%`
}

function signedMoney(n: number) {
  const sign = n > 0 ? '+' : n < 0 ? '−' : ''
  return `${sign}${Math.abs(n).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function tone(n: number) {
  if (n > 0) return 'up'
  if (n < 0) return 'dn'
  return 'flat'
}

const leaderName = computed(() => {
  if (!desk.leaderId) return null
  return desk.desks.find((d) => d.id === desk.leaderId)?.name || desk.leaderId
})
</script>

<template>
  <header class="bar">
    <div class="row-main">
      <div class="brand">大A 上证LLM模拟台</div>
      <div
        class="svc"
        :aria-live="desk.runtime?.state === 'degraded' || desk.runtime?.state === 'halted' ? 'polite' : undefined"
      >
        <span :class="lampClass" aria-hidden="true" />
        <span>{{ statusText }}</span>
      </div>
      <div class="badge">仅本地模拟 · 非投资建议</div>
    </div>

    <div v-if="desk.desks.length" class="row-compete" aria-label="双模型收益竞争">
      <div class="switch" role="tablist" aria-label="策略台">
        <button
          v-for="d in desk.desks"
          :key="d.id"
          type="button"
          role="tab"
          class="tab"
          :class="{ on: d.id === desk.activeDeskId }"
          :aria-selected="d.id === desk.activeDeskId"
          @click="desk.selectDesk(d.id)"
        >
          {{ d.name }}
        </button>
      </div>
      <div class="race">
        <div
          v-for="d in desk.desks"
          :key="`race-${d.id}`"
          class="racer"
          :class="[tone(d.pnl_pct), { lead: d.id === desk.leaderId, active: d.id === desk.activeDeskId }]"
        >
          <span class="r-name">{{ d.name }}</span>
          <span class="r-pct mono">{{ signedPct(d.pnl_pct) }}</span>
          <span class="r-pnl mono">{{ signedMoney(d.pnl_total) }}</span>
          <span class="r-eq mono">权益 {{ d.equity.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }}</span>
        </div>
        <p v-if="leaderName" class="lead-note">领先：{{ leaderName }}</p>
        <p v-else class="lead-note">收益持平</p>
      </div>
    </div>
  </header>
</template>

<style scoped>
.bar {
  display: flex;
  flex-direction: column;
  gap: 0;
  background: var(--shell);
  color: var(--platform);
}

.row-main {
  display: flex;
  align-items: center;
  gap: 20px;
  height: var(--header-h);
  padding: 0 24px;
}

.brand {
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 0.02em;
  flex-shrink: 0;
}

.svc {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 500;
}

.lamp {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  transition: background-color 180ms ease-out, box-shadow 180ms ease-out;
}

.lamp.amber {
  background: var(--amber);
  box-shadow: 0 0 0 2px rgba(245, 166, 35, 0.35);
}

.lamp.crimson {
  background: var(--crimson);
  box-shadow: 0 0 0 2px rgba(198, 40, 40, 0.35);
}

.lamp.leaf {
  background: var(--leaf);
}

.lamp.dim {
  background: rgba(232, 236, 240, 0.35);
}

.badge {
  margin-left: auto;
  font-size: 12px;
  opacity: 0.85;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: min(42ch, 40vw);
}

.row-compete {
  display: flex;
  align-items: stretch;
  gap: 16px;
  padding: 8px 24px 12px;
  border-top: 1px solid rgba(232, 236, 240, 0.12);
  background: rgba(0, 0, 0, 0.18);
}

.switch {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
  align-items: center;
}

.tab {
  appearance: none;
  border: 1px solid rgba(232, 236, 240, 0.22);
  background: transparent;
  color: rgba(232, 236, 240, 0.78);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  padding: 7px 12px;
  border-radius: 4px;
  cursor: pointer;
}

.tab:hover {
  color: #fff;
  border-color: rgba(232, 236, 240, 0.4);
}

.tab.on {
  background: var(--select-tint);
  color: var(--shell);
  border-color: var(--amber);
  outline: 1px solid var(--amber);
}

.race {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
}

.racer {
  display: grid;
  grid-template-columns: auto auto auto auto;
  gap: 6px 10px;
  align-items: baseline;
  padding: 4px 10px;
  border-radius: 4px;
  border: 1px solid transparent;
  font-size: 12px;
}

.racer.active {
  border-color: rgba(232, 236, 240, 0.28);
  background: rgba(232, 236, 240, 0.06);
}

.racer.lead {
  outline: 1px solid var(--amber);
}

.r-name {
  font-weight: 600;
  opacity: 0.92;
}

.mono {
  font-variant-numeric: tabular-nums;
}

.r-pct {
  font-weight: 700;
  min-width: 4.5em;
}

.r-pnl,
.r-eq {
  opacity: 0.85;
}

.racer.up .r-pct,
.racer.up .r-pnl {
  color: #ff8a80;
}

.racer.dn .r-pct,
.racer.dn .r-pnl {
  color: #a5d6a7;
}

.lead-note {
  margin: 0 0 0 auto;
  font-size: 11px;
  opacity: 0.75;
  white-space: nowrap;
}

@media (max-width: 900px) {
  .row-main {
    flex-wrap: wrap;
    height: auto;
    padding: 12px 16px;
    gap: 10px;
  }

  .badge {
    margin-left: 0;
    width: 100%;
  }

  .row-compete {
    flex-direction: column;
    padding: 10px 16px 12px;
  }

  .lead-note {
    margin-left: 0;
  }

  .racer {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
