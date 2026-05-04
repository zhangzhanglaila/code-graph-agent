<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()
const dsUrl = computed(() => store.dsVizResult?.ds_viz_url || '')
</script>

<template>
  <div class="ds-panel animate-slide-up">
    <div v-if="dsUrl" class="ds-content">
      <iframe :src="dsUrl" class="ds-iframe" />
    </div>
    <div v-else class="ds-empty">
      <p>No data structure visualization available</p>
    </div>
  </div>
</template>

<style scoped>
.ds-panel { height: 100%; }

.ds-content { height: 100%; }

.ds-iframe {
  width: 100%;
  height: 100%;
  border: none;
  border-radius: 8px;
}

.ds-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
}
</style>
