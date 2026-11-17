import { defineStore } from 'pinia'
import { ref } from 'vue'
import { client, type WeekItem, type WeeklyReport } from '../api/client'

export const useWeeklyStore = defineStore('weekly', () => {
  const year = ref(2026)
  const weeks = ref<WeekItem[]>([])
  const selectedKey = ref<string | null>(null)
  const report = ref<WeeklyReport | null>(null)
  const loading = ref(false)
  const generating = ref(false)
  const error = ref<string | null>(null)

  async function loadWeeks() {
    loading.value = true
    error.value = null
    try {
      const res = await client.weeklyWeeks()
      year.value = res.year
      weeks.value = res.weeks
      if (!selectedKey.value && res.weeks.length) {
        selectedKey.value = res.weeks[0].week_key
      }
      if (selectedKey.value) {
        await loadReport(selectedKey.value)
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function loadReport(weekKey: string) {
    selectedKey.value = weekKey
    report.value = null
    error.value = null
    try {
      report.value = await client.weeklyReport(weekKey)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      // 404 表示尚未生成，不算致命
      if (!/404|无报告|NOT_FOUND/i.test(msg)) {
        error.value = msg
      }
    }
  }

  async function generate(force = false) {
    if (!selectedKey.value) return
    generating.value = true
    error.value = null
    try {
      report.value = await client.generateWeeklyReport(selectedKey.value, force)
      const w = weeks.value.find((x) => x.week_key === selectedKey.value)
      if (w) w.has_report = true
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      generating.value = false
    }
  }

  return {
    year,
    weeks,
    selectedKey,
    report,
    loading,
    generating,
    error,
    loadWeeks,
    loadReport,
    generate,
  }
})
