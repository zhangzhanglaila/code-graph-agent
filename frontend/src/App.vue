<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import TopBar from './components/TopBar.vue'
import CodeEditor from './components/CodeEditor.vue'
import InsightPanel from './components/InsightPanel.vue'
import TimelinePanel from './components/TimelinePanel.vue'
import GraphPanel from './components/GraphPanel.vue'
import DSVizPanel from './components/DSVizPanel.vue'
import ErrorToast from './components/ErrorToast.vue'
import { useAnalysisStore } from './store/analysisStore'
import { getInsight, analyzeCode, getDSViz, getExplain, getExplainSteps } from './api/analysis'

const store = useAnalysisStore()

const DEMOS: Record<string, string> = {
  fibonacci: `def fibonacci(n=8):
    memo = {}
    a, b = 0, 1
    for i in range(n):
        memo[i] = a
        a, b = b, a + b
    return memo`,

  linked_list: `class Node:
    def __init__(self, val):
        self.val = val
        self.next = None

def build_and_traverse():
    n1 = Node(3)
    n2 = Node(7)
    n3 = Node(1)
    n1.next = n2
    n2.next = n3
    current = n1
    total = 0
    while current is not None:
        total += current.val
        current = current.next
    return total`,

  filter_sort: `def process_data():
    arr = [3, 1, 4, 1, 5, 9, 2, 6]
    result = []
    for item in arr:
        if item > 3:
            result.append(item)
    sorted_result = sorted(result)
    return sum(sorted_result)`,
}

async function runAnalysis() {
  store.loading = true
  store.error = ''
  store.reset()
  try {
    const results = await Promise.allSettled([
      getInsight(store.code, store.funcName, store.language),
      analyzeCode(store.code, store.language),
      getDSViz(store.code, store.funcName, store.language),
      getExplain(store.code, store.funcName, store.language),
      getExplainSteps(store.code, store.funcName, store.language),
    ])

    const errors: string[] = []

    if (results[0].status === 'fulfilled') {
      store.insightResult = results[0].value
    } else {
      errors.push(`Insight: ${results[0].reason?.message || 'failed'}`)
    }

    if (results[1].status === 'fulfilled') {
      store.analyzeResult = results[1].value
    } else {
      errors.push(`Graph: ${results[1].reason?.message || 'failed'}`)
    }

    if (results[2].status === 'fulfilled') {
      store.dsVizResult = results[2].value
    } else {
      errors.push(`DS Viz: ${results[2].reason?.message || 'failed'}`)
    }

    if (results[3].status === 'fulfilled') {
      store.explainResult = results[3].value
    }

    if (results[4].status === 'fulfilled') {
      store.stepExplanations = results[4].value
    }

    if (errors.length === 3) {
      store.error = errors.join('; ')
    } else if (errors.length > 0) {
      store.error = 'Partial failure: ' + errors.join('; ')
    }

    if (store.hasResults) store.saveToHistory()
  } catch (e: any) {
    store.error = e.message
  } finally {
    store.loading = false
  }
}

function loadDemo(name: string) {
  store.setCode(DEMOS[name] || '')
}

function onKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    if (!store.loading && store.code.trim()) runAnalysis()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <TopBar @analyze="runAnalysis" @demo="loadDemo" />
  <ErrorToast />

  <div class="main-layout">
    <!-- Left: Code Editor -->
    <div class="left-panel">
      <CodeEditor />
    </div>

    <!-- Right: Results -->
    <div class="right-panel">
      <!-- Loading -->
      <div v-if="store.loading" class="loading-overlay">
        <div class="loading-spinner"></div>
        <div class="loading-text">Analyzing code...</div>
      </div>

      <!-- Tab bar -->
      <div class="tab-bar" v-if="store.hasResults">
        <button
          v-for="tab in (['insight', 'timeline', 'graph', 'dsviz'] as const)"
          :key="tab"
          :class="['tab-btn', { active: store.activeTab === tab }]"
          @click="store.activeTab = tab"
        >
          {{ tab === 'dsviz' ? 'Data Structure' : tab.charAt(0).toUpperCase() + tab.slice(1) }}
        </button>
      </div>

      <!-- Panels -->
      <div class="panels">
        <InsightPanel v-if="!store.hasResults && !store.loading" />
        <InsightPanel v-if="store.activeTab === 'insight' && store.hasResults" />
        <TimelinePanel v-if="store.activeTab === 'timeline' && store.hasResults" />
        <GraphPanel v-if="store.activeTab === 'graph' && store.hasResults" />
        <DSVizPanel v-if="store.activeTab === 'dsviz' && store.hasResults" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.main-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.left-panel {
  width: 45%;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}

.right-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(15,23,42,0.9);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 10;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.loading-text {
  margin-top: 12px;
  color: var(--text-dim);
  font-size: 14px;
}

.tab-bar {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border);
  padding: 0 12px;
  flex-shrink: 0;
}

.tab-btn {
  padding: 10px 18px;
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.tab-btn:hover {
  color: var(--text);
}

.tab-btn.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
}

.panels {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
</style>
