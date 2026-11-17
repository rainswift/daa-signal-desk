<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { client } from '../api/client'
import { useDeskStore } from '../stores/desk'

const desk = useDeskStore()

const side = ref<'buy' | 'sell'>('buy')
const qty = ref(100)
const orderType = ref<'market' | 'limit'>('limit')
const limit = ref('')
const busy = ref(false)

watch(
  () => desk.selectedQuote?.last,
  (last) => {
    if (last != null && (!limit.value || orderType.value === 'limit')) {
      limit.value = last.toFixed(2)
    }
  },
  { immediate: true },
)

const title = computed(() => `下单 · ${desk.selectedQuote?.name || '未选线路'}`)
const tradeBlocked = computed(() => !desk.canTrade)

const blockHint = computed(() => {
  const s = desk.runtime?.state
  if (s === 'degraded') return '行情降级：暂停新成交'
  if (s === 'halted') return '熔断：拒绝新单'
  if (s === 'closed') return '收市：仅可查看账本'
  return ''
})

async function submit(forcedSide: 'buy' | 'sell') {
  side.value = forcedSide
  busy.value = true
  desk.lastError = null
  try {
    await desk.placeOrder({
      side: forcedSide,
      qty: Number(qty.value),
      type: orderType.value,
      limit: orderType.value === 'limit' ? Number(limit.value) : undefined,
    })
  } catch (e) {
    desk.lastError = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

async function recoverQuotes() {
  busy.value = true
  try {
    await client.refresh()
    await desk.refreshQuotes()
  } catch (e) {
    desk.lastError = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="panel" aria-labelledby="order-title">
    <h2 id="order-title">{{ title }}</h2>

    <div class="row">
      <div>
        <label for="side">方向</label>
        <select id="side" v-model="side">
          <option value="buy">买入</option>
          <option value="sell">卖出</option>
        </select>
      </div>
      <div>
        <label for="qty">数量（手=100）</label>
        <input id="qty" v-model.number="qty" type="number" min="100" step="100" />
      </div>
    </div>

    <label for="otype">类型</label>
    <select id="otype" v-model="orderType">
      <option value="limit">限价</option>
      <option value="market">市价</option>
    </select>

    <template v-if="orderType === 'limit'">
      <label for="limit">限价</label>
      <input id="limit" v-model="limit" type="number" step="0.01" class="mono" />
    </template>

    <p v-if="blockHint" class="block">{{ blockHint }}</p>
    <p v-if="desk.lastFlash" class="flash" role="status">{{ desk.lastFlash }}</p>
    <p v-if="desk.lastError" class="err" role="alert">{{ desk.lastError }}</p>

    <button
      type="button"
      class="buy"
      :disabled="busy || tradeBlocked"
      @click="submit('buy')"
    >
      买入
    </button>

    <div class="sell-slot" aria-label="卖出隔离区">
      <button
        type="button"
        class="sell"
        :disabled="busy || tradeBlocked"
        @click="submit('sell')"
      >
        卖出
      </button>
    </div>

    <button
      v-if="tradeBlocked && desk.runtime?.state === 'degraded'"
      type="button"
      class="recover"
      :disabled="busy"
      @click="recoverQuotes"
    >
      恢复行情刷新
    </button>

    <p class="note">T+1：当日买入可卖=0。热度固定池（沪深创科）· 仅本地模拟 · 非投资建议。</p>
  </section>
</template>

<style scoped>
.panel {
  background: var(--panel);
  padding: 18px 20px;
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

label {
  display: block;
  font-size: 12px;
  color: var(--ink-muted);
  margin: 10px 0 4px;
}

.row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

input,
select {
  width: 100%;
  height: 40px;
  border: 1px solid var(--field-border);
  border-radius: 4px;
  padding: 0 10px;
  font-size: 15px;
  background: #fff;
  color: var(--ink);
}

.buy {
  margin-top: 18px;
  height: 44px;
  width: 100%;
  border: 0;
  border-radius: 4px;
  background: var(--shell);
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 160ms ease-out, transform 160ms ease-out;
}

.buy:hover:not(:disabled) {
  transform: translateY(-1px);
}

.buy:disabled,
.sell:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  transform: none;
}

.sell-slot {
  margin-top: 28px;
  padding-top: 20px;
  border-top: 1px solid var(--hairline);
}

.sell {
  height: 44px;
  width: 100%;
  border: 1px solid var(--crimson);
  border-radius: 4px;
  background: transparent;
  color: var(--crimson);
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
}

.note {
  margin-top: 16px;
  font-size: 12px;
  line-height: 1.4;
  color: var(--ink-muted);
}

.block {
  margin: 12px 0 0;
  padding: 8px 10px;
  background: rgba(245, 166, 35, 0.15);
  border: 1px solid rgba(245, 166, 35, 0.45);
  border-radius: 4px;
  font-size: 13px;
  color: var(--ink);
}

.flash {
  margin: 10px 0 0;
  font-size: 13px;
  color: var(--leaf);
}

.err {
  margin: 10px 0 0;
  font-size: 13px;
  color: var(--crimson);
}

.recover {
  margin-top: 12px;
  height: 36px;
  width: 100%;
  border: 1px solid var(--field-border);
  border-radius: 4px;
  background: #fff;
  color: var(--ink);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
</style>
