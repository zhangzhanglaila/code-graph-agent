<script setup lang="ts">
import { onMounted, onUnmounted, onErrorCaptured, ref } from 'vue'
import TopBar from './components/TopBar.vue'
import CodeEditor from './components/CodeEditor.vue'
import InsightPanel from './components/InsightPanel.vue'
import TimelinePanel from './components/TimelinePanel.vue'
import GraphPanel from './components/GraphPanel.vue'
import DSVizPanel from './components/DSVizPanel.vue'
import StackPanel from './components/StackPanel.vue'
import GitHubPanel from './components/GitHubPanel.vue'
import RuntimeReplayPanel from './components/RuntimeReplayPanel.vue'
import SemanticExplorerPanel from './components/SemanticExplorerPanel.vue'
import QueryConsole from './components/QueryConsole.vue'
import SemanticDiffPanel from './components/SemanticDiffPanel.vue'
import SemanticMap from './components/SemanticMap.vue'
import SemanticCanvas from './components/SemanticCanvas.vue'
import AgentPanel from './components/AgentPanel.vue'
import MetricsPanel from './components/MetricsPanel.vue'
import ErrorToast from './components/ErrorToast.vue'
import { useAnalysisStore } from './store/analysisStore'
import { getInsight, analyzeCode, getDSViz, getExplain, getExplainSteps, getPatternNarrative, getSubproblemGraph, getFailureAttribution, getCausalChain } from './api/analysis'

const store = useAnalysisStore()
const componentError = ref('')

onErrorCaptured((err, instance, info) => {
  const stack = (err as Error)?.stack || String(err)
  // Show first 2 lines (message + first frame) to keep debug bar readable
  const short = stack.split('\n').slice(0, 3).join(' | ')
  componentError.value = short
  console.error('[Vue Error Captured]', err, '\nComponent:', instance?.$options?.name || instance?.type?.name || 'unknown', '\nInfo:', info, '\nStack:', stack)
  return false // prevent propagation
})

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
    // Phase 1: independent calls
    const results = await Promise.allSettled([
      getInsight(store.code, store.funcName, store.language),
      analyzeCode(store.code, store.language),
      getDSViz(store.code, store.funcName, store.language),
      getExplain(store.code, store.funcName, store.language),
    ])

    const errors: string[] = []

    if (results[0].status === 'fulfilled') {
      store.insightResult = results[0].value
      store.sessionId = results[0].value.session_id || ''
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

    // Phase 2: step explanations + pattern recognition + subproblem graph + failure attribution
    if (store.sessionId) {
      const [stepsRes, patternRes, subgraphRes, failureRes, causalRes] = await Promise.allSettled([
        getExplainSteps(store.code, store.funcName, store.language, 'mock', '', store.sessionId),
        getPatternNarrative(store.code, store.funcName, store.language, store.sessionId),
        getSubproblemGraph(store.code, store.funcName, store.language),
        getFailureAttribution(store.code, store.funcName, store.language),
        getCausalChain(store.code, store.funcName, store.language),
      ])

      if (stepsRes.status === 'fulfilled') {
        store.stepExplanations = stepsRes.value.explanations
        store.controlEdges = stepsRes.value.control_edges || []
        store.loopGroups = stepsRes.value.loop_groups || []
      }

      if (patternRes.status === 'fulfilled' && patternRes.value) {
        store.patternResult = patternRes.value
      }

      if (subgraphRes.status === 'fulfilled' && subgraphRes.value) {
        store.subproblemGraph = subgraphRes.value
      }

      if (failureRes.status === 'fulfilled' && failureRes.value?.success) {
        store.failureAttribution = failureRes.value.attribution
      }

      if (causalRes.status === 'fulfilled' && causalRes.value?.success) {
        store.causalChain = causalRes.value.causal_chain
      }
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
      <!-- Debug info (temporary) -->
      <div class="debug-bar" v-if="store.hasResults || componentError">
        Tab: {{ store.activeTab }} |
        Timeline: {{ store?.timeline?.length ?? 0 }} steps |
        Graph: {{ store.analyzeResult ? 'yes' : 'no' }} |
        DSViz(raw): {{ store.dsVizResult?.steps?.length ?? 'null' }} | DSViz(eff): {{ store.dsVizTimeline?.length ?? 0 }} |
        ExplainSteps: {{ store.stepExplanations.length }} |
        Subproblem: {{ store.subproblemGraph ? 'yes' : 'no' }}
        <span v-if="componentError" style="color:var(--error)"> | ERROR: {{ componentError }}</span>
      </div>

      <!-- Loading -->
      <div v-if="store.loading" class="loading-overlay">
        <div class="loading-spinner"></div>
        <div class="loading-text">正在分析代码...</div>
      </div>

      <!-- Tab bar -->
      <div class="tab-bar" v-if="store.hasResults || store.githubResult">
        <button
          v-for="tab in (['insight', 'canvas', 'replay', 'console', 'semantics', 'map', 'diff', 'stack', 'dsviz', 'graph', 'timeline', 'github', 'agent', 'metrics'] as const)"
          :key="tab"
          :class="['tab-btn', { active: store.activeTab === tab }]"
          @click="store.activeTab = tab"
        >
          {{ tab === 'insight' ? '分析洞察' : tab === 'canvas' ? '语义画布' : tab === 'replay' ? '执行回放' : tab === 'console' ? '语义控制台' : tab === 'semantics' ? '语义推理' : tab === 'map' ? '语义地图' : tab === 'diff' ? '语义对比' : tab === 'stack' ? '执行栈' : tab === 'dsviz' ? '数据结构' : tab === 'graph' ? '执行图' : tab === 'timeline' ? '时间线' : tab === 'agent' ? '智能体' : tab === 'metrics' ? '系统指标' : 'GitHub' }}
        </button>
      </div>

      <!-- Panels -->
      <div class="panels">
        <InsightPanel v-if="!store.hasResults && !store.loading && !store.githubResult" />
        <InsightPanel v-if="store.activeTab === 'insight' && store.hasResults" />
        <SemanticCanvas v-if="store.activeTab === 'canvas' && store.hasResults" />
        <RuntimeReplayPanel v-if="store.activeTab === 'replay' && store.hasResults" />
        <QueryConsole v-if="store.activeTab === 'console' && store.hasResults" />
        <SemanticExplorerPanel v-if="store.activeTab === 'semantics' && store.hasResults" />
        <SemanticMap v-if="store.activeTab === 'map' && store.hasResults" />
        <SemanticDiffPanel v-if="store.activeTab === 'diff'" />
        <StackPanel v-if="store.activeTab === 'stack' && store.hasResults" />
        <GraphPanel v-if="store.activeTab === 'graph' && store.hasResults" />
        <DSVizPanel v-if="store.activeTab === 'dsviz' && store.hasResults" />
        <TimelinePanel v-if="store.activeTab === 'timeline' && store.hasResults" />
        <GitHubPanel v-if="store.activeTab === 'github' && store.githubResult" />
        <AgentPanel v-if="store.activeTab === 'agent'" />
        <MetricsPanel v-if="store.activeTab === 'metrics'" />
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
  background: rgba(240,242,245,0.92);
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

.debug-bar {
  font-size: 11px;
  font-family: monospace;
  color: var(--warning);
  background: rgba(251,191,36,0.08);
  border-bottom: 1px solid rgba(251,191,36,0.2);
  padding: 4px 12px;
  flex-shrink: 0;
}
</style>
