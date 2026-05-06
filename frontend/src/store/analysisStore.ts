import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { InsightResponse, AnalyzeResponse, DSVizResponse, ExplainResponse, StepExplanation, FocusedExplanation, StepData, ControlEdge, LoopGroup, PatternNarrativeResponse, SubproblemGraphResponse } from '../api/analysis'

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
  const patternResult = ref<PatternNarrativeResponse | null>(null)
  const subproblemGraph = ref<SubproblemGraphResponse | null>(null)

  // Timeline state
  const currentStep = ref(0)
  const isPlaying = ref(false)
  const playSpeed = ref(500)
  const explainMode = ref(false)

  // History
  const history = ref<HistoryEntry[]>(loadHistory())

  // Computed
  const hasResults = computed(() => !!insightResult.value)
  const timeline = computed(() => {
    const raw = insightResult.value
    if (!raw) return []
    if ((raw as any).timeline?.length) return (raw as any).timeline
    if ((raw as any).steps?.length) return (raw as any).steps
    return []
  })
  const totalSteps = computed(() => timeline.value.length)
  const safeStep = computed(() => {
    const len = timeline.value.length
    if (!len) return 0
    return Math.min(Math.max(currentStep.value, 0), len - 1)
  })
  const currentStepData = computed(() => {
    const t = timeline.value
    const idx = safeStep.value
    if (!t || t.length === 0 || idx < 0 || idx >= t.length) {
      return { index: 0, file: '', line: 0, code: '', changed: [] as string[], new_vars: [] as string[], vars: {} as Record<string, any> }
    }
    return t[idx]
  })

  // DSViz: unified data source — use real heap data if available, else derive from timeline vars
  function tryParseValue(raw: string): any {
    if (!raw || typeof raw !== 'string') return raw
    // JSON arrays/objects
    if (raw.startsWith('[') || raw.startsWith('{')) {
      try { return JSON.parse(raw) } catch {}
    }
    // Python-style: {'a': 1} → {"a": 1}
    if (raw.startsWith("{'") || raw.startsWith('{"')) {
      try {
        const fixed = raw.replace(/'/g, '"')
        return JSON.parse(fixed)
      } catch {}
    }
    return raw
  }

  function buildGraphFromVars(vars: Record<string, any>, changed: string[]): { nodes: Record<string, any>, edges: any[], bindings: Record<string, number>, changedIds: number[] } {
    if (!vars || typeof vars !== 'object' || Array.isArray(vars)) {
      return { nodes: {}, edges: [], bindings: {}, changedIds: [] }
    }
    const nodes: Record<string, any> = {}
    const edges: any[] = []
    const bindings: Record<string, number> = {}
    const changedIds: number[] = []
    let nextId = 0
    const seen = new Map<any, number>() // object identity → node id

    function addNode(type: string, val: string, changed: boolean): number {
      const id = nextId++
      nodes[String(id)] = { id, type, val: val.slice(0, 60), attrs: {}, refs: {}, changed }
      if (changed) changedIds.push(id)
      return id
    }

    function build(value: any, isChanged: boolean): number {
      // Primitives
      if (value === null || value === undefined) return addNode('None', String(value), isChanged)
      if (typeof value === 'boolean') return addNode('bool', String(value), isChanged)
      if (typeof value === 'number') return addNode('number', String(value), isChanged)
      if (typeof value === 'string') {
        // Could be a repr of something complex
        const parsed = tryParseValue(value)
        if (parsed !== value) return build(parsed, isChanged)
        return addNode('str', `"${value.slice(0, 30)}"`, isChanged)
      }

      // Cycle detection
      if (seen.has(value)) return seen.get(value)!

      if (Array.isArray(value)) {
        const id = addNode('list', `[${value.length}]`, isChanged)
        seen.set(value, id)
        value.forEach((item, i) => {
          const childId = build(item, false)
          edges.push({ from: id, to: childId, label: String(i), changed: false })
          nodes[String(id)].refs[String(i)] = childId
        })
        return id
      }

      if (typeof value === 'object') {
        const keys = Object.keys(value)
        const id = addNode('dict', `{${keys.length}}`, isChanged)
        seen.set(value, id)
        for (const k of keys) {
          const childId = build(value[k], false)
          edges.push({ from: id, to: childId, label: k, changed: false })
          nodes[String(id)].refs[k] = childId
        }
        return id
      }

      return addNode(typeof value, String(value).slice(0, 40), isChanged)
    }

    for (const [name, v] of Object.entries(vars)) {
      const raw = v.value
      const parsed = tryParseValue(raw)
      const isChanged = !!v.changed
      const nodeId = build(parsed, isChanged)
      bindings[name] = nodeId
    }

    return { nodes, edges, bindings, changedIds }
  }

  const dsVizTimeline = computed(() => {
    try {
      if (dsVizResult.value?.steps?.length) return dsVizResult.value.steps
      return timeline.value.map((step: any, i: number) => {
        const { nodes, edges, bindings, changedIds } = buildGraphFromVars(step.vars || {}, step.changed || [])
        return {
          index: step.index ?? i,
          line: step.line ?? 0,
          code: step.code ?? '',
          nodes,
          edges,
          var_bindings: bindings,
          changed_objects: changedIds,
        }
      })
    } catch {
      return []
    }
  })

  // Reads/Writes: causal dependency per step
  const PYTHON_KEYWORDS = new Set([
    'if', 'else', 'elif', 'for', 'while', 'return', 'def', 'class', 'import',
    'from', 'as', 'with', 'try', 'except', 'finally', 'raise', 'pass', 'break',
    'continue', 'and', 'or', 'not', 'in', 'is', 'True', 'False', 'None',
    'range', 'len', 'int', 'str', 'float', 'list', 'dict', 'set', 'tuple',
    'print', 'append', 'extend', 'sorted', 'reversed', 'enumerate', 'zip',
    'map', 'filter', 'sum', 'min', 'max', 'abs', 'type', 'isinstance',
    'self', 'cls', 'super', 'lambda', 'yield', 'global', 'nonlocal',
    'key', 'item', 'value',
  ])

  function extractIdentifiers(code: string): string[] {
    const matches = code.match(/\b[a-zA-Z_]\w*\b/g) || []
    return [...new Set(matches.filter(m => !PYTHON_KEYWORDS.has(m)))]
  }

  const stepDependency = computed(() => {
    const deps: Record<number, { reads: string[], writes: string[] }> = {}
    const lastWriter: Record<string, number> = {} // var name → step index

    for (const step of timeline.value) {
      const idx = step.index
      const writes = [...new Set([...(step.changed || []), ...(step.new_vars || [])])]
      const writeSet = new Set(writes)
      const allVars = Object.keys(step.vars || {})
      const codeIdents = extractIdentifiers(step.code || '')
      // reads = identifiers in code that exist as vars but aren't written this step
      const reads = [...new Set(
        codeIdents.filter(id => allVars.includes(id) && !writeSet.has(id))
      )]

      deps[idx] = { reads, writes }

      // Track last writer for causal edges
      for (const w of writes) lastWriter[w] = idx
    }
    return deps
  })

  // Causal edges: data dependency graph (who writes → who reads)
  const causalEdges = computed(() => {
    const edges: { from: number, to: number, var: string }[] = []
    const lastWriter: Record<string, number> = {}

    for (const step of timeline.value) {
      const idx = step.index
      const dep = stepDependency.value[idx]
      if (!dep) continue

      // Record edges: lastWriter[var] → current step (if current reads var)
      for (const r of dep.reads) {
        if (lastWriter[r] !== undefined && lastWriter[r] !== idx) {
          edges.push({ from: lastWriter[r], to: idx, var: r })
        }
      }

      // Update last writer
      for (const w of dep.writes) lastWriter[w] = idx
    }
    return edges
  })

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
    if (totalSteps.value === 0) { currentStep.value = 0; return }
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
    patternResult.value = null
    subproblemGraph.value = null
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
    focusedExplanation, focusLoading, patternResult, subproblemGraph, explainMode,
    sessionId, showAllSteps, importantSteps,
    currentStep, isPlaying, playSpeed,
    history,
    hasResults, timeline, totalSteps, safeStep, currentStepData, currentStepExplanation, dsVizTimeline,
    stepDependency, causalEdges,
    setCode, goToStep, nextStep, prevStep, reset,
    saveToHistory, loadFromHistory, clearHistory,
  }
})
