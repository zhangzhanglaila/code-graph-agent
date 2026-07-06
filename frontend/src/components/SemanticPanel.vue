<script setup lang="ts">
import { ref } from 'vue'
import SemanticCanvas from './SemanticCanvas.vue'
import SemanticMap from './SemanticMap.vue'

const activeSubTab = ref('canvas')
const subTabs = [
  { id: 'canvas', label: '语义画布' },
  { id: 'map', label: '语义地图' },
]
</script>

<template>
  <div class="semantic-panel">
    <div class="sub-tab-bar">
      <button
        v-for="tab in subTabs"
        :key="tab.id"
        :class="['sub-tab-btn', { active: activeSubTab === tab.id }]"
        @click="activeSubTab = tab.id"
      >{{ tab.label }}</button>
    </div>
    <div class="sub-tab-content">
      <div v-show="activeSubTab === 'canvas'"><SemanticCanvas /></div>
      <div v-show="activeSubTab === 'map'"><SemanticMap /></div>
    </div>
  </div>
</template>

<style scoped>
.semantic-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.sub-tab-bar {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border);
  padding: 0 4px;
  flex-shrink: 0;
}

.sub-tab-btn {
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-dim);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}

.sub-tab-btn:hover {
  color: var(--text);
}

.sub-tab-btn.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
}

.sub-tab-content {
  flex: 1;
  overflow-y: auto;
}

.sub-tab-content > div {
  height: 100%;
}
</style>
