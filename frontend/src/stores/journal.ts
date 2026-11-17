import { defineStore } from 'pinia'
import { ref } from 'vue'
import { client, type Order, type StrategyRun } from '../api/client'

const DESK_STORAGE_KEY = 'daa.activeDeskId'

export const useJournalStore = defineStore('journal', () => {
  const runs = ref<StrategyRun[]>([])
  const selectedId = ref<number | null>(null)
  const selected = ref<StrategyRun | null>(null)
  const orders = ref<Order[]>([])
  const filterDeskId = ref<string | 'all'>(localStorage.getItem(DESK_STORAGE_KEY) || 'all')
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function load() {
    loading.value = true
    error.value = null
    try {
      const deskParam = filterDeskId.value === 'all' ? undefined : filterDeskId.value
      const [runsOut, ords] = await Promise.all([
        client.strategyRuns(100, deskParam),
        client.orders(200, deskParam),
      ])
      runs.value = runsOut.runs
      orders.value = ords
      if (selectedId.value == null && runs.value.length) {
        await selectRun(runs.value[0].id ?? null)
      } else if (selectedId.value != null) {
        const still = runs.value.find((r) => r.id === selectedId.value)
        selected.value = still || null
        if (!still) selectedId.value = null
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function setFilterDesk(id: string | 'all') {
    filterDeskId.value = id
    selectedId.value = null
    selected.value = null
    await load()
  }

  async function selectRun(id: number | null) {
    selectedId.value = id
    if (id == null) {
      selected.value = null
      return
    }
    const cached = runs.value.find((r) => r.id === id)
    if (cached) {
      selected.value = cached
      return
    }
    try {
      selected.value = await client.strategyRun(id)
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      selected.value = null
    }
  }

  return {
    runs,
    selectedId,
    selected,
    orders,
    filterDeskId,
    loading,
    error,
    load,
    setFilterDesk,
    selectRun,
  }
})
