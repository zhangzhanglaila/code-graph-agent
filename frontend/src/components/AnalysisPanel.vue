<script setup lang="ts">
import { ref } from 'vue'
import InsightPanel from './InsightPanel.vue'
import AgentPanel from './AgentPanel.vue'
import SemanticExplorerPanel from './SemanticExplorerPanel.vue'
import QueryConsole from './QueryConsole.vue'

const activeSubTab = ref('insight')
const subTabs = [
  { id: 'insight', label: '洞察' },
  { id: 'agent', label: '智能体' },
  { id: 'semantics', label: '语义推理' },
  { id: 'console', label: '查询控制台' },
]
</script>

<template>
  <div class="analysis-panel">
    <div class="sub-tab-bar">
      <button
        v-for="tab in subTabs"
        :key="tab.id"
        :class="['sub-tab-btn', { active: activeSubTab === tab.id }]"
        @click="activeSubTab = tab.id"
      >{{ tab.label }}</button>
    </div>
    <div class="sub-tab-content">
      <div v-show="activeSubTab === 'insight'"><InsightPanel /></div>
      <div v-show="activeSubTab === 'agent'"><AgentPanel /></div>
      <div v-show="activeSubTab === 'semantics'"><SemanticExplorerPanel /></div>
      <div v-show="activeSubTab === 'console'"><QueryConsole /></div>
    </div>
  </div>
</template>

<style scoped>
.analysis-panel {
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
