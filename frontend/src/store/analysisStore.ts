import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type { InsightResponse, AnalyzeResponse, DSVizResponse, ExplainResponse, StepExplanation, FocusedExplanation, StepData, ControlEdge, LoopGroup, PatternNarrativeResponse, SubproblemGraphResponse, DetectedPattern, GitHubAnalyzeResponse } from '../api/analysis'

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
  const activeTab = ref<'insight' | 'replay' | 'stack' | 'dsviz' | 'graph' | 'timeline' | 'github'>('insight')
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
  const githubResult = ref<GitHubAnalyzeResponse | null>(null)
  const failureAttribution = ref<any>(null)
  const importGraph = ref<any>(null)

  // Timeline state
  const currentStep = ref(0)
  const isPlaying = ref(false)
  const playSpeed = ref(500)
  const explainMode = ref(false)
  const highlightedLine = ref(0)

  // Clear editor highlight when leaving timeline/dsviz/replay tabs
  watch(activeTab, (tab) => {
    if (tab !== 'timeline' && tab !== 'dsviz' && tab !== 'replay') {
      highlightedLine.value = 0
    }
  })

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

  // ========== Execution Semantics Layer ==========

  // Call Stack: reconstruct frames from timeline depth/call_id
  interface CallFrame {
    call_id: number
    depth: number
    func_name: string
    args: Record<string, string>
    start_step: number
    end_step: number | null
    is_current: boolean
  }

  const callStack = computed<CallFrame[]>(() => {
    const steps = timeline.value
    if (!steps.length) return []
    const curIdx = safeStep.value
    const frames: CallFrame[] = []
    const frameMap = new Map<number, CallFrame>() // call_id → frame

    for (let i = 0; i <= curIdx; i++) {
      const s = steps[i]
      const cid = s.call_id || 0
      const depth = s.depth || 0
      const funcName = s.func || s.code?.match(/def\s+(\w+)/)?.[1] || 'main'

      if (!frameMap.has(cid)) {
        // Extract args from vars at call point
        const args: Record<string, string> = {}
        for (const [k, v] of Object.entries(s.vars || {})) {
          if (!k.startsWith('_') && k !== 'self') {
            args[k] = String((v as any).value ?? '').slice(0, 30)
          }
        }
        const frame: CallFrame = {
          call_id: cid, depth, func_name: funcName,
          args, start_step: i, end_step: null, is_current: false,
        }
        frameMap.set(cid, frame)
        frames.push(frame)
      }
    }

    // Mark current frame
    const curStep = steps[curIdx]
    const curCid = curStep?.call_id || 0
    const activeFrame = frameMap.get(curCid)
    if (activeFrame) {
      activeFrame.is_current = true
      // Update args with latest values
      for (const [k, v] of Object.entries(curStep?.vars || {})) {
        if (!k.startsWith('_') && k !== 'self') {
          activeFrame.args[k] = String((v as any).value ?? '').slice(0, 30)
        }
      }
    }

    // Mark ended frames
    for (const f of frames) {
      if (!f.is_current) {
        for (let i = f.start_step + 1; i <= curIdx; i++) {
          if ((steps[i].depth || 0) < f.depth) {
            f.end_step = i - 1
            break
          }
        }
      }
    }

    return frames
  })

  // Semantic Narrator: rule-based code → human explanation
  function narrateStep(code: string, vars: Record<string, any>): string {
    const c = (code || '').trim()

    // Assignment: x = expr
    const assignMatch = c.match(/^(\w+)\s*=\s*(.+)$/)
    if (assignMatch) {
      const [, name, expr] = assignMatch
      const val = vars[name]?.value
      if (expr === 'None') return `初始化 ${name} 为空`
      if (expr === '{}') return `创建空字典 ${name}`
      if (expr === '[]') return `创建空列表 ${name}`
      if (expr === '0' || expr === '0, 1' || expr === '0,1') return `初始化 ${name} = ${expr}`
      if (expr.startsWith('Node(')) return `创建节点 ${name} = ${val ?? expr}`
      if (expr.startsWith('range(')) return `设置循环范围: ${expr}`
      if (expr.startsWith('sorted(')) return `对数据排序 → ${name}`
      if (expr.startsWith('[') && expr.includes('for')) return `列表推导 → ${name}`
      return `${name} = ${val ?? expr}`
    }

    // Augmented assignment: x += expr
    const augMatch = c.match(/^(\w+)\s*(\+=|-=|\*=|\/=)\s*(.+)$/)
    if (augMatch) {
      const [, name, op, expr] = augMatch
      const val = vars[name]?.value
      return `${name} ${op} ${expr} → ${val ?? '?'}`
    }

    // Tuple assignment: a, b = expr
    const tupleMatch = c.match(/^(\w+),\s*(\w+)\s*=\s*(.+)$/)
    if (tupleMatch) {
      const [, a, b, expr] = tupleMatch
      const va = vars[a]?.value, vb = vars[b]?.value
      return `${a}=${va ?? '?'}, ${b}=${vb ?? '?'} (交换/更新)`
    }

    // Attribute assignment: x.next = y
    const attrAssign = c.match(/^(\w+)\.(\w+)\s*=\s*(.+)$/)
    if (attrAssign) {
      const [, obj, attr, val] = attrAssign
      return `设置 ${obj}.${attr} = ${val}`
    }

    // Return
    if (c.startsWith('return ')) {
      const expr = c.slice(7).trim()
      const val = vars[expr]?.value
      return `返回 ${val ?? expr}`
    }
    if (c === 'return') return `返回`

    // If/elif
    const ifMatch = c.match(/^(if|elif)\s+(.+):$/)
    if (ifMatch) {
      const [, kw, cond] = ifMatch
      const condClean = cond.replace(/\s*is not None\s*/, '').replace(/\s*is None\s*/, '')
      const val = vars[condClean]?.value
      if (cond.includes('is not None')) return `检查 ${condClean} 是否有值 (=${val ?? '?'})`
      if (cond.includes('is None')) return `检查 ${condClean} 是否为空 (=${val ?? '?'})`
      if (cond.includes('not ')) return `检查条件: ${cond}`
      return `判断: ${cond} (=${val ?? '?'})`
    }

    // For loop
    if (c.startsWith('for ')) {
      const forMatch = c.match(/^for\s+(\w+)\s+in\s+(.+):$/)
      if (forMatch) {
        const [, varName, iterable] = forMatch
        const val = vars[varName]?.value
        return `循环: ${varName} = ${val ?? '?'} (遍历 ${iterable})`
      }
      return `循环: ${c}`
    }

    // While
    if (c.startsWith('while ')) {
      return `循环条件: ${c.replace(/:$/, '')}`
    }

    // Method calls
    const methodMatch = c.match(/^(\w+)\.(\w+)\((.*)\)$/)
    if (methodMatch) {
      const [, obj, method, args] = methodMatch
      if (method === 'append') return `${obj}.append(${args}) → 长度 ${vars[obj]?.value ? JSON.parse(vars[obj].value.replace(/'/g, '"')).length : '?'}`
      if (method === 'extend') return `${obj}.extend(${args})`
      return `${obj}.${method}(${args})`
    }

    // Function calls
    const funcCallMatch = c.match(/^(\w+)\((.*)\)$/)
    if (funcCallMatch) {
      const [, fname, args] = funcCallMatch
      if (fname === 'print') return `输出: ${args}`
      return `调用 ${fname}(${args})`
    }

    // Pass/break/continue
    if (c === 'pass') return `跳过`
    if (c === 'break') return `跳出循环`
    if (c === 'continue') return `继续下一次循环`

    // Class def / function def
    if (c.startsWith('class ')) return `定义类 ${c.replace(/[:\(].*/, '').replace('class ', '')}`
    if (c.startsWith('def ')) return `定义函数 ${c.match(/def\s+(\w+)/)?.[1] || '?'}`

    return c
  }

  // Precompute narrations — prefer backend AST narration, fallback to frontend regex
  const semanticNarrations = computed(() => {
    const steps = timeline.value
    if (!steps.length) return [] as string[]
    return steps.map(s => {
      // Backend AST narration (preferred)
      if (s.narration) return s.narration
      // Frontend regex fallback
      return narrateStep(s.code || '', s.vars || {})
    })
  })

  // Event types — prefer backend, fallback to frontend detection
  const semanticEventTypes = computed(() => {
    const steps = timeline.value
    if (!steps.length) return [] as string[]
    return steps.map(s => s.event_type || 'unknown')
  })

  // Pointer transitions: track pointer moves across steps (with object identity)
  const pointerTransitions = computed(() => {
    const steps = timeline.value
    if (!steps.length) return [] as { step: number; pointer: string; from_object?: string; to_object?: string; via: string }[]
    const transitions: { step: number; pointer: string; from_object?: string; to_object?: string; via: string }[] = []
    for (let i = 0; i < steps.length; i++) {
      const s = steps[i]
      if (s.pointer_move) {
        transitions.push({ step: i, ...s.pointer_move })
      }
    }
    return transitions
  })

  // Frame lifecycle: track call suspend/resume events
  interface FrameEvent {
    step: number
    type: 'CALL_ENTER' | 'CALL_SUSPEND' | 'CALL_RESUME' | 'CALL_RETURN'
    depth: number
    call_id: number
    func_name: string
  }

  const frameLifecycle = computed<FrameEvent[]>(() => {
    const steps = timeline.value
    if (!steps.length) return []
    const events: FrameEvent[] = []
    let prevDepth = 0

    for (let i = 0; i < steps.length; i++) {
      const s = steps[i]
      const depth = s.depth || 0
      const delta = depth - prevDepth

      if (delta > 0) {
        // Entering a new frame
        events.push({ step: i, type: 'CALL_ENTER', depth, call_id: s.call_id || 0, func_name: s.func || '?' })
      } else if (delta < 0) {
        // Returning from frame(s)
        for (let d = 0; d < Math.abs(delta); d++) {
          events.push({ step: i, type: 'CALL_RETURN', depth: prevDepth - d - 1, call_id: 0, func_name: '?' })
        }
      }

      // Detect suspend (call to recursive function without depth increase = same-level call)
      if (delta === 0 && s.event_type === 'recursive_call') {
        events.push({ step: i, type: 'CALL_SUSPEND', depth, call_id: s.call_id || 0, func_name: s.func || '?' })
      }

      prevDepth = depth
    }
    return events
  })

  // Heap object tracking: extract object graph from timeline vars
  interface HeapObject {
    id: string
    type: string
    val: string
    fields: Record<string, string>  // field_name → object_id
    changed: boolean
  }

  const currentHeapSnapshot = computed(() => {
    const step = timeline.value[safeStep.value]
    if (!step) return { objects: [] as HeapObject[], bindings: {} as Record<string, string> }

    const objects: HeapObject[] = []
    const bindings: Record<string, string> = {}
    let nextId = 0
    const seen = new Map<string, string>() // value repr → object_id

    for (const [name, v] of Object.entries(step.vars || {})) {
      const val = v.value || ''
      const isChanged = v.changed || false

      // Detect linked list / tree nodes from repr pattern
      const nodeMatch = val.match(/^Node\((\d+)\)$/) || val.match(/^TreeNode\((\d+)\)$/)
      if (nodeMatch) {
        const objId = `obj_${nextId++}`
        objects.push({
          id: objId, type: 'Node', val: nodeMatch[1],
          fields: {}, changed: isChanged,
        })
        bindings[name] = objId
        seen.set(val, objId)
        continue
      }

      // Detect lists
      if (val.startsWith('[') && val.endsWith(']')) {
        const objId = `obj_${nextId++}`
        objects.push({
          id: objId, type: 'list', val: val.slice(0, 30),
          fields: {}, changed: isChanged,
        })
        bindings[name] = objId
        continue
      }

      // Detect dicts
      if (val.startsWith('{') && val.endsWith('}')) {
        const objId = `obj_${nextId++}`
        objects.push({
          id: objId, type: 'dict', val: val.slice(0, 30),
          fields: {}, changed: isChanged,
        })
        bindings[name] = objId
        continue
      }

      // Primitives
      if (v.type === 'int' || v.type === 'float' || v.type === 'str' || v.type === 'bool' || v.type === 'NoneType') {
        // Don't create heap objects for primitives
        continue
      }
    }

    // Second pass: link references (x.next → y)
    for (const obj of objects) {
      // Look for other vars that reference this object's fields
      // This is a heuristic — real object identity would need backend support
    }

    return { objects, bindings }
  })

  // Detected algorithmic patterns (from Pattern Combinator)
  const detectedPatterns = computed<DetectedPattern[]>(() => {
    const raw = insightResult.value as any
    return raw?.detected_patterns || []
  })

  // Current pattern: which detected pattern covers the current step
  const currentPattern = computed(() => {
    const step = safeStep.value
    return detectedPatterns.value.find(p => step >= p.start_step && step <= p.end_step) || null
  })

  const currentNarration = computed(() =>
    semanticNarrations.value[safeStep.value] || ''
  )

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
    failureAttribution.value = null
    importGraph.value = null
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
    githubResult, failureAttribution, importGraph,
    sessionId, showAllSteps, importantSteps,
    currentStep, isPlaying, playSpeed,
    highlightedLine,
    history,
    hasResults, timeline, totalSteps, safeStep, currentStepData, currentStepExplanation, dsVizTimeline,
    stepDependency, causalEdges,
    callStack, semanticNarrations, currentNarration,
    semanticEventTypes, pointerTransitions,
    frameLifecycle, currentHeapSnapshot,
    detectedPatterns, currentPattern,
    setCode, goToStep, nextStep, prevStep, reset,
    saveToHistory, loadFromHistory, clearHistory,
  }
})
