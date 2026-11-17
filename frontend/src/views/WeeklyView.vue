<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { renderMarkdown } from '../lib/markdown'
import { useWeeklyStore } from '../stores/weekly'

const weekly = useWeeklyStore()

onMounted(() => {
  void weekly.loadWeeks()
})

const sourceBadge = computed(() => {
  const s = weekly.report?.data_source
  if (s === 'mock') return '数据：synthetic mock'
  if (s === 'akshare') return '数据：AKShare'
  return null
})

const bodyHtml = computed(() =>
  weekly.report ? renderMarkdown(weekly.report.content_md) : '',
)
</script>

<template>
  <div class="weekly">
    <header class="top">
      <h1>2026 周度复盘</h1>
      <p class="disc">仅本地模拟研究摘要 · 非投资建议 · 指数为虚拟标的</p>
    </header>

    <div class="body">
      <aside class="weeks" aria-label="周列表">
        <h2>周次</h2>
        <p v-if="weekly.loading" class="muted">加载中…</p>
        <button
          v-for="w in weekly.weeks"
          :key="w.week_key"
          type="button"
          class="week"
          :class="{ on: w.week_key === weekly.selectedKey }"
          @click="weekly.loadReport(w.week_key)"
        >
          <span class="key">{{ w.week_key }}</span>
          <span class="range mono">{{ w.week_start.slice(5) }}~{{ w.week_end.slice(5) }}</span>
          <span v-if="w.has_report" class="dot" title="已有报告" />
        </button>
      </aside>

      <section class="panel" aria-live="polite">
        <div class="toolbar">
          <div>
            <h2>{{ weekly.selectedKey || '选择一周' }}</h2>
            <p v-if="sourceBadge" class="badge">{{ sourceBadge }}</p>
          </div>
          <div class="actions">
            <button
              type="button"
              class="gen"
              :disabled="!weekly.selectedKey || weekly.generating"
              @click="weekly.generate(false)"
            >
              {{ weekly.generating ? '生成中…' : weekly.report ? '重新读取/生成' : '生成分析' }}
            </button>
            <button
              v-if="weekly.report"
              type="button"
              class="force"
              :disabled="weekly.generating"
              @click="weekly.generate(true)"
            >
              强制重生成
            </button>
          </div>
        </div>

        <p v-if="weekly.error" class="err" role="alert">{{ weekly.error }}</p>

        <article v-if="weekly.report" class="md" v-html="bodyHtml" />
        <p v-else-if="!weekly.loading && weekly.selectedKey" class="muted">
          本周尚未生成摘要。点击「生成分析」：后端将聚合五指数周行情，并调用方舟 DeepSeek 撰写（需配置
          <code>ARK_API_KEY</code>）。
        </p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.weekly {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  background: var(--platform);
}

.top {
  height: var(--header-h);
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 20px;
  background: var(--shell);
  color: var(--platform);
}

.top h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.disc {
  margin: 0 0 0 auto;
  font-size: 12px;
  opacity: 0.85;
}

.body {
  flex: 1;
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 1px;
  background: var(--seam);
  min-height: calc(100vh - var(--header-h));
}

.weeks,
.panel {
  background: var(--panel);
  padding: 16px 18px;
  min-height: 0;
}

.weeks h2,
.panel h2 {
  margin: 0 0 12px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-muted);
}

.week {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: 0;
  border-bottom: 1px solid var(--hairline);
  background: transparent;
  text-align: left;
  padding: 10px 8px;
  cursor: pointer;
  color: inherit;
  font: inherit;
}

.week.on {
  background: var(--select-tint);
  outline: 2px solid var(--amber);
  outline-offset: -2px;
}

.key {
  font-weight: 600;
  font-size: 14px;
}

.range {
  font-size: 12px;
  color: var(--ink-muted);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--leaf);
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}

.badge {
  margin: 6px 0 0;
  display: inline-block;
  font-size: 12px;
  padding: 2px 8px;
  border: 1px solid var(--field-border);
  border-radius: 4px;
  color: var(--ink-muted);
}

.actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.gen,
.force {
  height: 36px;
  padding: 0 14px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.gen {
  border: 0;
  background: var(--shell);
  color: #fff;
}

.force {
  border: 1px solid var(--field-border);
  background: #fff;
  color: var(--ink);
}

.gen:disabled,
.force:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.err {
  color: var(--crimson);
  font-size: 13px;
}

.muted {
  color: var(--ink-muted);
  font-size: 14px;
  line-height: 1.5;
}

.md {
  max-width: 72ch;
  color: var(--ink);
}

.md :deep(h1),
.md :deep(h2) {
  font-size: 18px;
  font-weight: 600;
  margin: 20px 0 8px;
  letter-spacing: 0.01em;
}

.md :deep(h3) {
  font-size: 15px;
  font-weight: 600;
  margin: 16px 0 6px;
}

.md :deep(p) {
  margin: 0 0 10px;
  line-height: 1.7;
  font-size: 15px;
}

.md :deep(ul),
.md :deep(ol) {
  margin: 0 0 12px;
  padding-left: 1.35em;
}

.md :deep(li) {
  margin: 4px 0;
  line-height: 1.6;
}

.md :deep(strong) {
  font-weight: 600;
}

.md :deep(blockquote) {
  margin: 12px 0;
  padding: 10px 14px;
  background: var(--select-tint);
  border: 1px solid rgba(245, 166, 35, 0.35);
  border-radius: 4px;
  color: var(--ink);
}

.md :deep(code) {
  font-family: var(--font-mono);
  font-size: 13px;
  background: rgba(11, 31, 58, 0.06);
  padding: 0.1em 0.35em;
  border-radius: 3px;
}

.md :deep(pre) {
  overflow: auto;
  padding: 12px 14px;
  margin: 0 0 12px;
  background: rgba(11, 31, 58, 0.06);
  border-radius: 4px;
  border: 1px solid var(--hairline);
}

.md :deep(pre code) {
  background: transparent;
  padding: 0;
}

.md :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0 0 14px;
  font-size: 14px;
}

.md :deep(th),
.md :deep(td) {
  border: 1px solid var(--hairline);
  padding: 8px 10px;
  text-align: left;
}

.md :deep(th) {
  background: rgba(11, 31, 58, 0.04);
  font-weight: 600;
}

.md :deep(a) {
  color: var(--shell);
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
}

.md :deep(hr) {
  border: 0;
  border-top: 1px solid var(--hairline);
  margin: 16px 0;
}

code {
  font-family: var(--font-mono);
  font-size: 12px;
}

@media (max-width: 960px) {
  .body {
    grid-template-columns: 1fr;
  }

  .top {
    flex-wrap: wrap;
    height: auto;
    padding: 12px 16px;
  }

  .disc {
    margin-left: 0;
    width: 100%;
  }
}
</style>
