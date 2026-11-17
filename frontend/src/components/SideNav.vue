<script setup lang="ts">
export type AppView = 'desk' | 'journal' | 'weekly'

defineProps<{
  current: AppView
}>()

const emit = defineEmits<{
  navigate: [view: AppView]
}>()
</script>

<template>
  <nav class="rail" aria-label="主导航">
    <div class="rail-brand">大A</div>
    <button
      type="button"
      class="item"
      :class="{ on: current === 'desk' }"
      :aria-current="current === 'desk' ? 'page' : undefined"
      @click="emit('navigate', 'desk')"
    >
      策略台
    </button>
    <button
      type="button"
      class="item"
      :class="{ on: current === 'journal' }"
      :aria-current="current === 'journal' ? 'page' : undefined"
      @click="emit('navigate', 'journal')"
    >
      记录
    </button>
    <button
      type="button"
      class="item"
      :class="{ on: current === 'weekly' }"
      :aria-current="current === 'weekly' ? 'page' : undefined"
      @click="emit('navigate', 'weekly')"
    >
      2026 周报
    </button>
  </nav>
</template>

<style scoped>
.rail {
  width: 88px;
  flex-shrink: 0;
  background: var(--shell);
  color: var(--platform);
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  padding: 12px 8px;
  min-height: 100%;
}

.rail-brand {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-align: center;
  padding: 8px 0 16px;
  opacity: 0.95;
}

.item {
  appearance: none;
  border: 0;
  background: transparent;
  color: rgba(232, 236, 240, 0.78);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  padding: 12px 8px;
  border-radius: 4px;
  cursor: pointer;
  text-align: center;
  position: relative;
  transition: background-color 160ms ease-out, color 160ms ease-out;
}

.item:hover {
  background: rgba(232, 236, 240, 0.08);
  color: #fff;
}

.item.on {
  color: var(--shell);
  background: var(--select-tint);
  outline: 2px solid var(--amber);
  outline-offset: -2px;
}

@media (max-width: 960px) {
  .rail {
    width: 100%;
    min-height: auto;
    flex-direction: row;
    align-items: center;
    padding: 8px 12px;
    gap: 8px;
  }

  .rail-brand {
    padding: 0 8px 0 0;
    font-size: 16px;
  }

  .item {
    padding: 8px 12px;
  }
}
</style>
