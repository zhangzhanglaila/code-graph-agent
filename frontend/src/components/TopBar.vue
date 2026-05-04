<script setup lang="ts">
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()
const emit = defineEmits<{
  analyze: []
  demo: [name: string]
}>()
</script>

<template>
  <div class="topbar">
    <div class="logo">
      <span class="logo-icon">&#x1F9E0;</span>
      <span class="logo-text">Why-Code-Agent</span>
      <span class="logo-tag">Program Understanding Engine</span>
    </div>

    <div class="actions">
      <div class="demo-group">
        <span class="demo-label">Try:</span>
        <button class="btn btn-secondary btn-sm" @click="emit('demo', 'fibonacci')">Fibonacci</button>
        <button class="btn btn-secondary btn-sm" @click="emit('demo', 'linked_list')">Linked List</button>
        <button class="btn btn-secondary btn-sm" @click="emit('demo', 'filter_sort')">Filter+Sort</button>
      </div>

      <button
        class="btn btn-primary"
        :disabled="store.loading || !store.code.trim()"
        title="Ctrl+Enter"
        @click="emit('analyze')"
      >
        <span v-if="store.loading" class="animate-pulse">Analyzing...</span>
        <span v-else>Analyze</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo-icon {
  font-size: 24px;
}

.logo-text {
  font-size: 18px;
  font-weight: 700;
  background: linear-gradient(135deg, var(--primary), var(--highlight));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.logo-tag {
  font-size: 11px;
  color: var(--text-muted);
  margin-left: 4px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.demo-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.demo-label {
  font-size: 12px;
  color: var(--text-muted);
}

.btn-sm {
  padding: 4px 12px;
  font-size: 12px;
}
</style>
