import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { InsightResponse, AnalyzeResponse, DSVizResponse, StepData } from '../api/analysis'

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

  // Results
  const insightResult = ref<InsightResponse | null>(null)
  const analyzeResult = ref<AnalyzeResponse | null>(null)
  const dsVizResult = ref<DSVizResponse | null>(null)

  // Timeline state
  const currentStep = ref(0)
  const isPlaying = ref(false)
  const playSpeed = ref(500)

  // Computed
  const hasResults = computed(() => !!insightResult.value)
  const timeline = computed(() => insightResult.value?.timeline || [])
  const totalSteps = computed(() => timeline.value.length)
  const currentStepData = computed(() => timeline.value[currentStep.value] || null)

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
    currentStep.value = 0
    error.value = ''
  }

  return {
    code, language, funcName,
    loading, error, activeTab,
    insightResult, analyzeResult, dsVizResult,
    currentStep, isPlaying, playSpeed,
    hasResults, timeline, totalSteps, currentStepData,
    setCode, goToStep, nextStep, prevStep, reset,
  }
})
