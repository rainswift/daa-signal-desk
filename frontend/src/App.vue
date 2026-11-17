<script setup lang="ts">
import { ref } from 'vue'
import SideNav, { type AppView } from './components/SideNav.vue'
import DeskView from './views/DeskView.vue'
import JournalView from './views/JournalView.vue'
import WeeklyView from './views/WeeklyView.vue'

const view = ref<AppView>('desk')

function navigate(next: AppView) {
  view.value = next
}
</script>

<template>
  <div class="shell">
    <SideNav :current="view" @navigate="navigate" />
    <div class="main">
      <DeskView v-if="view === 'desk'" />
      <JournalView v-else-if="view === 'journal'" />
      <WeeklyView v-else />
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100%;
  height: 100%;
  background: var(--platform);
}

.main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

@media (max-width: 960px) {
  .shell {
    flex-direction: column;
  }
}
</style>
