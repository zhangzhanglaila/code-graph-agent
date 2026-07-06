<script setup lang="ts">
import { onMounted, onUnmounted, onErrorCaptured, ref } from 'vue'
import TopBar from './components/TopBar.vue'
import CodeEditor from './components/CodeEditor.vue'
import AnalysisPanel from './components/AnalysisPanel.vue'
import SemanticPanel from './components/SemanticPanel.vue'
import ReplayPanel from './components/ReplayPanel.vue'
import SemanticDiffPanel from './components/SemanticDiffPanel.vue'
import MetricsPanel from './components/MetricsPanel.vue'
import GitHubPanel from './components/GitHubPanel.vue'
import InsightPanel from './components/InsightPanel.vue'
import ErrorToast from './components/ErrorToast.vue'
// Advanced mode: individual panels
import GraphPanel from './components/GraphPanel.vue'
import DSVizPanel from './components/DSVizPanel.vue'
import TimelinePanel from './components/TimelinePanel.vue'
import StackPanel from './components/StackPanel.vue'
import AgentPanel from './components/AgentPanel.vue'
import QueryConsole from './components/QueryConsole.vue'
import SemanticExplorerPanel from './components/SemanticExplorerPanel.vue'
import RuntimeReplayPanel from './components/RuntimeReplayPanel.vue'
import SemanticCanvas from './components/SemanticCanvas.vue'
import SemanticMap from './components/SemanticMap.vue'
import { useAnalysisStore } from './store/analysisStore'
import { getInsight, analyzeCode, getDSViz, getExplain, getExplainSteps, getPatternNarrative, getSubproblemGraph, getFailureAttribution, getCausalChain } from './api/analysis'

const store = useAnalysisStore()
const componentError = ref('')

onErrorCaptured((err, instance, info) => {
  const stack = (err as Error)?.stack || String(err)
  const short = stack.split('\n').slice(0, 3).join(' | ')
  componentError.value = short
  console.error('[Vue Error Captured]', err, '\nComponent:', instance?.$options?.name || (instance as any)?.type?.name || 'unknown', '\nInfo:', info, '\nStack:', stack)
  return false
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
  const requestCode = store.code
  const requestFuncName = store.funcName
  const requestLanguage = store.language
  store.loading = true
  store.error = ''
  store.reset()
  try {
    const results = await Promise.allSettled([
      getInsight(requestCode, requestFuncName, requestLanguage),
      analyzeCode(requestCode, requestLanguage),
      getDSViz(requestCode, requestFuncName, requestLanguage),
      getExplain(requestCode, requestFuncName, requestLanguage),
    ])

    if (store.code !== requestCode || store.funcName !== requestFuncName || store.language !== requestLanguage) {
      store.error = '代码已变更，请重新分析。'
      return
    }

    const errors: string[] = []

    if (results[0].status === 'fulfilled') {
      store.insightResult = results[0].value
      store.sessionId = results[0].value.session_id || ''
      if (results[0].value.success) {
        store.analysisCode = requestCode
        store.analysisFuncName = requestFuncName
        store.analysisLanguage = requestLanguage
      } else {
        errors.push(`Insight: ${results[0].value.error || 'failed'}`)
      }
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

    if (store.sessionId) {
      const [stepsRes, patternRes, subgraphRes, failureRes, causalRes] = await Promise.allSettled([
        getExplainSteps(requestCode, requestFuncName, requestLanguage, 'mock', '', store.sessionId),
        getPatternNarrative(requestCode, requestFuncName, requestLanguage, store.sessionId),
        getSubproblemGraph(requestCode, requestFuncName, requestLanguage),
        getFailureAttribution(requestCode, requestFuncName, requestLanguage),
        getCausalChain(requestCode, requestFuncName, requestLanguage),
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
        ExplainSteps: {{ store.stepExplanations.length }}
        <span v-if="componentError" style="color:var(--error)"> | ERROR: {{ componentError }}</span>
      </div>

      <!-- Loading -->
      <div v-if="store.loading" class="loading-overlay">
        <div class="loading-spinner"></div>
        <div class="loading-text">正在分析代码...</div>
      </div>

      <!-- Tab bar -->
      <div class="tab-bar" v-if="store.hasResults || store.githubResult">
        <!-- Normal mode: 5 core tabs -->
        <template v-if="!store.advancedMode">
          <button
            v-for="tab in (['analysis', 'semantic', 'replay', 'diff', 'metrics'] as const)"
            :key="tab"
            :class="['tab-btn', { active: store.activeTab === tab }]"
            @click="store.activeTab = tab"
          >
            {{ tab === 'analysis' ? '智能分析' : tab === 'semantic' ? '语义视图' : tab === 'replay' ? '执行回放' : tab === 'diff' ? '语义对比' : '系统指标' }}
          </button>
          <button
            v-if="store.githubResult"
            :class="['tab-btn', { active: store.activeTab === 'github' }]"
            @click="store.activeTab = 'github'"
          >
            GitHub
          </button>
        </template>

        <!-- Advanced mode: all granular tabs -->
        <template v-else>
          <button
            v-for="tab in (['insight', 'agent', 'semantics', 'console', 'graph', 'canvas', 'map', 'dsviz', 'replay', 'stack', 'timeline', 'diff', 'metrics'] as const)"
            :key="tab"
            :class="['tab-btn', { active: store.activeTab === tab }]"
            @click="store.activeTab = tab"
          >
            {{ tab === 'insight' ? '洞察' : tab === 'agent' ? '智能体' : tab === 'semantics' ? '语义推理' : tab === 'console' ? '查询控制台' : tab === 'graph' ? '因果图' : tab === 'canvas' ? '语义画布' : tab === 'map' ? '语义地图' : tab === 'dsviz' ? '数据结构' : tab === 'replay' ? '执行回放' : tab === 'stack' ? '执行栈' : tab === 'timeline' ? '时间线' : tab === 'diff' ? '语义对比' : '系统指标' }}
          </button>
          <button
            v-if="store.githubResult"
            :class="['tab-btn', { active: store.activeTab === 'github' }]"
            @click="store.activeTab = 'github'"
          >
            GitHub
          </button>
        </template>

        <!-- Advanced mode toggle -->
        <div class="tab-spacer"></div>
        <button
          class="mode-toggle"
          :class="{ active: store.advancedMode }"
          @click="store.advancedMode = !store.advancedMode"
          title="切换高级模式"
        >
          {{ store.advancedMode ? '简洁' : '高级' }}
        </button>
      </div>

      <!-- Panels -->
      <div class="panels">
        <!-- Welcome state -->
        <InsightPanel v-if="!store.hasResults && !store.loading && !store.githubResult" />

        <!-- Normal mode: consolidated panels -->
        <template v-if="!store.advancedMode">
          <AnalysisPanel v-if="store.activeTab === 'analysis' && store.hasResults" />
          <SemanticPanel v-if="store.activeTab === 'semantic' && store.hasResults" />
          <ReplayPanel v-if="store.activeTab === 'replay' && store.hasResults" />
          <SemanticDiffPanel v-if="store.activeTab === 'diff'" />
          <MetricsPanel v-if="store.activeTab === 'metrics'" />
          <GitHubPanel v-if="store.activeTab === 'github' && store.githubResult" />
        </template>

        <!-- Advanced mode: granular panels -->
        <template v-else>
          <InsightPanel v-if="store.activeTab === 'insight' && store.hasResults" />
          <AgentPanel v-if="store.activeTab === 'agent'" />
          <SemanticExplorerPanel v-if="store.activeTab === 'semantics'" />
          <QueryConsole v-if="store.activeTab === 'console'" />
          <GraphPanel v-if="store.activeTab === 'graph' && store.analyzeResult" />
          <SemanticCanvas v-if="store.activeTab === 'canvas' && store.hasResults" />
          <SemanticMap v-if="store.activeTab === 'map' && store.hasResults" />
          <DSVizPanel v-if="store.activeTab === 'dsviz' && store.dsVizResult" />
          <RuntimeReplayPanel v-if="store.activeTab === 'replay' && store.hasResults" />
          <StackPanel v-if="store.activeTab === 'stack' && store.hasResults" />
          <TimelinePanel v-if="store.activeTab === 'timeline' && store.hasResults" />
          <SemanticDiffPanel v-if="store.activeTab === 'diff'" />
          <MetricsPanel v-if="store.activeTab === 'metrics'" />
          <GitHubPanel v-if="store.activeTab === 'github' && store.githubResult" />
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.main-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
  min-width: 0;
}

.left-panel {
  width: 42%;
  min-width: 420px;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
}

.right-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  min-width: 0;
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
  align-items: center;
  gap: 6px;
  border-bottom: 1px solid var(--border);
  padding: 8px 12px 0;
  flex-shrink: 0;
  background: var(--bg-card);
  overflow-x: auto;
  overflow-y: hidden;
}

.tab-btn {
  padding: 9px 14px;
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  border-radius: 6px 6px 0 0;
  transition: all 0.2s;
  white-space: nowrap;
}

.tab-btn:hover {
  color: var(--text);
  background: var(--bg-card-hover);
}

.tab-btn.active {
  color: var(--primary);
  background: var(--primary-soft);
  border-bottom-color: var(--primary);
}

.tab-spacer { flex: 1; }

.mode-toggle {
  padding: 7px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-dim);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  margin: auto 0;
  transition: all 0.2s;
  white-space: nowrap;
}
.mode-toggle:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.mode-toggle.active {
  background: var(--primary-soft);
  border-color: var(--primary);
  color: var(--primary);
}

.panels {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  min-height: 0;
}

.debug-bar {
  font-size: 14px;
  font-family: monospace;
  color: #92400e;
  background: #fffbeb;
  border-bottom: 1px solid #fbbf24;
  padding: 6px 12px;
  flex-shrink: 0;
}

@media (max-width: 1100px) {
  .main-layout {
    flex-direction: column;
  }

  .left-panel {
    width: 100%;
    min-width: 0;
    min-height: 320px;
    border-right: none;
    border-bottom: 1px solid var(--border);
  }
}
</style>
