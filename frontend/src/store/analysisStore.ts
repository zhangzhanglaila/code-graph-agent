import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { InsightResponse, AnalyzeResponse, DSVizResponse, ExplainResponse, StepExplanation, FocusedExplanation, StepData, ControlEdge, LoopGroup } from '../api/analysis'

interface HistoryEntry {
  id: string
  code: string
  funcName: string
  timestamp: number
  oneLiner: string
  algorithmType: string
  resultPreview: string
}

const HISTORY_KEY = 'why-code-history'
const MAX_HISTORY = 20

function loadHistory(): HistoryEntry[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  } catch { return [] }
}

function saveHistory(entries: HistoryEntry[]) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, MAX_HISTORY)))
}

export const useAnalysisStore = defineStore('analysis', () => {
  // Input
  const code = ref(`def fibonacci(n=8):
    memo = {}
    a, b = 0, 1
    for i in range(n):
        memo[i] = a
        a, b = b, a + b
    return memo`)
  const language = ref('python')
  const funcName = ref('')

  // State
  const loading = ref(false)
  const error = ref('')
  const activeTab = ref<'insight' | 'timeline' | 'graph' | 'dsviz'>('insight')
  const sessionId = ref('')
  const showAllSteps = ref(false)

  // Results
  const insightResult = ref<InsightResponse | null>(null)
  const analyzeResult = ref<AnalyzeResponse | null>(null)
  const dsVizResult = ref<DSVizResponse | null>(null)
  const explainResult = ref<ExplainResponse | null>(null)
  const stepExplanations = ref<StepExplanation[]>([])
  const controlEdges = ref<ControlEdge[]>([])
  const loopGroups = ref<LoopGroup[]>([])
  const focusedExplanation = ref<FocusedExplanation | null>(null)
  const focusLoading = ref(false)

  // Timeline state
  const currentStep = ref(0)
  const isPlaying = ref(false)
  const playSpeed = ref(500)
  const explainMode = ref(false)

  // History
  const history = ref<HistoryEntry[]>(loadHistory())

  // Computed
  const hasResults = computed(() => !!insightResult.value)
  const timeline = computed(() => insightResult.value?.timeline || [])
  const totalSteps = computed(() => timeline.value.length)
  const currentStepData = computed(() => timeline.value[currentStep.value] || null)
  const currentStepExplanation = computed(() =>
    stepExplanations.value.find(e => e.step === currentStep.value) || null
  )
  const importantSteps = computed(() =>
    stepExplanations.value.filter(e => (e.importance_score || 0) >= 0.30).map(e => e.step)
  )

  // Actions
  function setCode(newCode: string) {
    code.value = newCode
  }

  function goToStep(idx: number) {
    currentStep.value = Math.max(0, Math.min(idx, totalSteps.value - 1))
  }

  function nextStep() { goToStep(currentStep.value + 1) }
  function prevStep() { goToStep(currentStep.value - 1) }

  function reset() {
    insightResult.value = null
    analyzeResult.value = null
    dsVizResult.value = null
    explainResult.value = null
    stepExplanations.value = []
    controlEdges.value = []
    loopGroups.value = []
    focusedExplanation.value = null
    sessionId.value = ''
    currentStep.value = 0
    explainMode.value = false
    isPlaying.value = false
    showAllSteps.value = false
    error.value = ''
  }

  function saveToHistory() {
    if (!insightResult.value) return
    const entry: HistoryEntry = {
      id: Date.now().toString(36),
      code: code.value.slice(0, 500),
      funcName: funcName.value || insightResult.value.func_name,
      timestamp: Date.now(),
      oneLiner: insightResult.value.insight?.one_liner || '',
      algorithmType: insightResult.value.insight?.algorithm_type || '',
      resultPreview: String(insightResult.value.result).slice(0, 80),
    }
    // Dedupe by code
    history.value = [entry, ...history.value.filter(h => h.code !== entry.code)]
    saveHistory(history.value)
  }

  function loadFromHistory(entry: HistoryEntry) {
    code.value = entry.code
    funcName.value = entry.funcName
  }

  function clearHistory() {
    history.value = []
    saveHistory([])
  }

  return {
    code, language, funcName,
    loading, error, activeTab,
    insightResult, analyzeResult, dsVizResult, explainResult,
    stepExplanations, controlEdges, loopGroups,
    focusedExplanation, focusLoading, explainMode,
    sessionId, showAllSteps, importantSteps,
    currentStep, isPlaying, playSpeed,
    history,
    hasResults, timeline, totalSteps, currentStepData, currentStepExplanation,
    setCode, goToStep, nextStep, prevStep, reset,
    saveToHistory, loadFromHistory, clearHistory,
  }
})
