<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import StatusBar from '../components/StatusBar.vue'
import QuoteLines from '../components/QuoteLines.vue'
import OrderForm from '../components/OrderForm.vue'
import LedgerHub from '../components/LedgerHub.vue'
import StrategyRunsPanel from '../components/StrategyRunsPanel.vue'
import { inContinuousAuction } from '../lib/session'
import { useDeskStore } from '../stores/desk'

const desk = useDeskStore()
let timer: number | undefined

onMounted(async () => {
  await desk.bootstrap()
  timer = window.setInterval(() => {
    // 仅连续竞价轮询本地柜台；收盘停止打 /api/*
    if (inContinuousAuction()) {
      void desk.refreshQuotes()
    }
  }, 30_000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="desk">
    <StatusBar />
    <main class="grid">
      <div class="col-quotes">
        <QuoteLines />
      </div>
      <StrategyRunsPanel />
      <aside class="col-right">
        <LedgerHub />
        <div class="order-dock">
          <button
            type="button"
            class="order-toggle"
            :aria-expanded="desk.orderFormOpen"
            @click="desk.toggleOrderForm()"
          >
            {{ desk.orderFormOpen ? '收起手动下单' : '手动下单' }}
          </button>
          <div v-show="desk.orderFormOpen" class="order-slot">
            <OrderForm />
          </div>
        </div>
      </aside>
    </main>
    <p v-if="desk.lastError && !desk.account" class="boot-err" role="alert">
      无法连接柜台：{{ desk.lastError }}（请确认后端 :8000 已启动）
    </p>
  </div>
</template>

<style scoped>
.desk {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--platform);
  overflow: hidden;
}

.grid {
  flex: 1 1 0;
  min-height: 0;
  display: grid;
  /* 报价轨密；策略详情主阅读面加宽；账本缩成窄对账轨 */
  grid-template-columns: minmax(248px, 18.5rem) minmax(0, 1.9fr) minmax(220px, 0.72fr);
  gap: 1px;
  background: var(--seam);
  overflow: hidden;
}

.col-quotes,
.col-right {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--panel);
  overflow: hidden;
}

.col-right {
  overflow: auto;
}

.grid > :nth-child(2) {
  min-height: 0;
  overflow: auto;
}

.order-dock {
  border-top: 1px solid var(--seam);
  background: var(--panel);
}

.order-toggle {
  width: 100%;
  appearance: none;
  border: 0;
  border-bottom: 1px solid var(--hairline, var(--seam));
  background: transparent;
  color: var(--ink-muted);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 12px 20px;
  cursor: pointer;
  text-align: left;
}

.order-toggle:hover {
  color: var(--ink);
}

.order-slot :deep(.panel) {
  border-top: 0;
}

.boot-err {
  position: fixed;
  left: 24px;
  bottom: 24px;
  margin: 0;
  padding: 10px 14px;
  background: #fff;
  border: 1px solid var(--crimson);
  color: var(--crimson);
  border-radius: 4px;
  font-size: 13px;
  max-width: min(480px, calc(100vw - 48px));
  z-index: 20;
}

@media (max-width: 960px) {
  .desk {
    height: auto;
    overflow: visible;
  }

  .grid {
    grid-template-columns: 1fr;
    flex: none;
    min-height: auto;
    overflow: visible;
  }

  .col-quotes,
  .col-right,
  .grid > :nth-child(2) {
    overflow: visible;
  }
}
</style>
