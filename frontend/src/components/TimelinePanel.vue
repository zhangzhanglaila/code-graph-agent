<script setup lang="ts">
import { ref, computed, onUnmounted, watch } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { getExplainStepFocus } from '../api/analysis'

const store = useAnalysisStore()

const playTimer = ref<number | null>(null)
const explainPlaying = ref(false)
const causalSource = ref<number | null>(null)  // step whose causal links are shown
const hoveredStep = ref<number | null>(null)    // step hovered in timeline

// Execution path: steps visited up to current position
const executedSteps = computed(() => {
  const set = new Set<number>()
  for (let i = 0; i <= (store?.currentStep ?? 0); i++) {
    set.add(i)
  }
  return set
})

// Edge selection for WHY explanation
const selectedEdge = ref<{ from: number; to: number } | null>(null)

const edgeExplanation = computed(() => {
  if (!selectedEdge.value) return null
  const { from, to } = selectedEdge.value
  const fromExp = store.stepExplanations.find(e => e.step === from)
  const toExp = store.stepExplanations.find(e => e.step === to)
  const fromStep = store.timeline.find(s => s.index === from)
  const toStep = store.timeline.find(s => s.index === to)
  if (!fromStep || !toStep) return null

  // Find shared variables
  const fromChanged = new Set(fromStep.changed || [])
  const toChanged = new Set(toStep.changed || [])
  const toCode = toStep.code || ''
  const shared = [...fromChanged].filter(v => toChanged.has(v) || toCode.includes(v))

  // Check edge type
  const isControl = store.controlEdges.some(e => e.from === from && e.to === to)

  // Generate causal sentence
  let causalSentence = ''

  if (isControl) {
    // Control edge: "because [condition] determines whether this executes"
    const condCode = fromStep.code?.replace(/^(if |elif |for |while )/, '').replace(/:$/, '') || ''
    causalSentence = `Because "${condCode}" determines whether step ${to} executes`
  } else if (shared.length > 0) {
    // Data edge: "because [var] flows from [source action] to [target purpose]"
    const varStr = shared.join(', ')
    const fromAction = _describeAction(fromStep.code || '')
    const toPurpose = _describeAction(toStep.code || '')
    causalSentence = `Because ${varStr} produced by "${fromAction}" is needed for "${toPurpose}"`
  } else {
    causalSentence = `Step ${from} influences step ${to}`
  }

  // Build full explanation
  const parts: string[] = [causalSentence]
  if (fromExp?.importance === 'high') {
    parts.push(`This step is critical: ${fromExp.importance_explanation || ''}`)
  }

  return {
    from, to,
    sharedVars: shared,
    isControl,
    text: parts.join('. '),
  }
})

function _describeAction(code: string): string {
  const c = code.trim()
  if (c.startsWith('return ')) return 'returns result'
  if (c.startsWith('if ') || c.startsWith('elif ')) return 'checks condition'
  if (c.startsWith('for ')) return 'iterates'
  if (c.startsWith('while ')) return 'loops'
  if (c.includes('= [')) return 'builds collection'
  if (c.includes('.append(')) return 'adds to collection'
  if (c.includes('.add(')) return 'adds to set'
  if (c.match(/^\w+\s*=\s*/)) {
    const varName = c.split('=')[0].trim()
    return `computes ${varName}`
  }
  if (c.includes('(') && c.includes(')')) return 'calls function'
  return c.length > 20 ? c.slice(0, 20) + '…' : c
}

// Critical path: backward slice from return node
// Walk reverse edges picking highest causal contribution parent at each step
const criticalPath = computed(() => {
  if (!store.stepExplanations.length) return new Set<number>()

  // Build reverse adjacency: target → [sources that affect it]
  const reverseMap = new Map<number, number[]>()
  for (const exp of store.stepExplanations) {
    for (const target of (exp.affects || [])) {
      if (!reverseMap.has(target)) reverseMap.set(target, [])
      reverseMap.get(target)!.push(exp.step)
    }
  }

  // Also add control edges as reverse dependencies
  for (const ce of store.controlEdges) {
    if (!reverseMap.has(ce.to)) reverseMap.set(ce.to, [])
    reverseMap.get(ce.to)!.push(ce.from)
  }

  // Find the return/last step (highest index with "return" reason, or just highest index)
  const returnStep = store.stepExplanations
    .filter(e => e.importance_reasons?.includes('return'))
    .sort((a, b) => b.step - a.step)[0]

  const endStep = returnStep?.step ?? store.stepExplanations[store.stepExplanations.length - 1]?.step ?? 0

  // Backward slice: walk from end to start, picking highest importance parent
  const path: number[] = [endStep]
  const visited = new Set<number>([endStep])
  let current = endStep
  const maxDepth = 10

  for (let depth = 0; depth < maxDepth; depth++) {
    const parents = reverseMap.get(current) || []
    if (parents.length === 0) break

    // Pick parent with highest importance_score
    let bestParent = -1
    let bestScore = -1
    for (const p of parents) {
      if (visited.has(p)) continue
      const exp = store.stepExplanations.find(e => e.step === p)
      const score = exp?.importance_score || 0
      if (score > bestScore) {
        bestScore = score
        bestParent = p
      }
    }

    if (bestParent === -1) break
    path.push(bestParent)
    visited.add(bestParent)
    current = bestParent
  }

  // Reverse to get init → return order
  path.reverse()
  return new Set(path)
})

// Ordered critical path for narrative generation
const criticalPathOrdered = computed(() => {
  if (!store.stepExplanations.length) return []

  const reverseMap = new Map<number, number[]>()
  for (const exp of store.stepExplanations) {
    for (const target of (exp.affects || [])) {
      if (!reverseMap.has(target)) reverseMap.set(target, [])
      reverseMap.get(target)!.push(exp.step)
    }
  }
  for (const ce of store.controlEdges) {
    if (!reverseMap.has(ce.to)) reverseMap.set(ce.to, [])
    reverseMap.get(ce.to)!.push(ce.from)
  }

  const returnStep = store.stepExplanations
    .filter(e => e.importance_reasons?.includes('return'))
    .sort((a, b) => b.step - a.step)[0]
  const endStep = returnStep?.step ?? store.stepExplanations[store.stepExplanations.length - 1]?.step ?? 0

  const path: number[] = [endStep]
  const visited = new Set<number>([endStep])
  let current = endStep
  const maxDepth = 10

  for (let depth = 0; depth < maxDepth; depth++) {
    const parents = reverseMap.get(current) || []
    if (parents.length === 0) break
    let bestParent = -1
    let bestScore = -1
    for (const p of parents) {
      if (visited.has(p)) continue
      const exp = store.stepExplanations.find(e => e.step === p)
      const score = exp?.importance_score || 0
      if (score > bestScore) { bestScore = score; bestParent = p }
    }
    if (bestParent === -1) break
    path.push(bestParent)
    visited.add(bestParent)
    current = bestParent
  }

  path.reverse()
  return path
})

const maxCostPerLevel = computed(() => {
  const levels = store?.subproblemGraph?.layout?.level_info
  if (!levels?.length) return 1
  const costs = levels.map(l => l.level_cost ?? l.node_count)
  return Math.max(1, ...costs)
})

const levelCosts = computed(() => {
  const levels = store?.subproblemGraph?.layout?.level_info
  if (!levels) return []
  return levels.filter(l => l.level_cost != null).map(l => l.level_cost!)
})

const isCostBalanced = computed(() => {
  if (levelCosts.value.length < 2) return false
  const avg = levelCosts.value.reduce((a, b) => a + b, 0) / levelCosts.value.length
  return levelCosts.value.every(c => Math.abs(c - avg) / avg < 0.15)
})

const isCostDecreasing = computed(() => {
  if (levelCosts.value.length < 2) return false
  // Check if each level is <= previous level (with some tolerance)
  for (let i = 1; i < levelCosts.value.length; i++) {
    if (levelCosts.value[i] > levelCosts.value[i - 1] * 1.1) return false
  }
  return true
})

const avgLevelCost = computed(() => {
  if (!levelCosts.value.length) return '?'
  const avg = levelCosts.value.reduce((a, b) => a + b, 0) / levelCosts.value.length
  return Math.round(avg)
})

const levelCostSummary = computed(() => {
  if (!levelCosts.value.length) return ''
  const first = levelCosts.value[0]
  const last = levelCosts.value[levelCosts.value.length - 1]
  return `${first} → ... → ${last}`
})

// Pattern Sandbox
const sandboxPatterns = [
  { key: 'balanced', label: 'Balanced (merge sort)' },
  { key: 'decreasing', label: 'Decreasing (binary search)' },
  { key: 'tree', label: 'Tree (fibonacci)' },
]
const sandboxPattern = ref('balanced')
const sandboxBranching = ref(2)
const sandboxDepth = ref(4)

const sandboxLevels = computed(() => {
  const levels = []
  const n = Math.pow(sandboxBranching.value, sandboxDepth.value) // root problem size
  for (let d = 0; d <= sandboxDepth.value; d++) {
    let nodes, size, cost
    if (sandboxPattern.value === 'balanced') {
      nodes = Math.pow(sandboxBranching.value, d)
      size = Math.max(1, Math.round(n / nodes))
      cost = nodes * size
    } else if (sandboxPattern.value === 'decreasing') {
      nodes = Math.min(Math.pow(2, d), sandboxBranching.value)
      size = Math.max(1, Math.round(n / Math.pow(sandboxBranching.value, d)))
      cost = Math.max(1, Math.round(n / Math.pow(sandboxBranching.value, d)))
    } else { // tree
      nodes = Math.pow(sandboxBranching.value, d)
      size = Math.max(1, sandboxDepth.value - d)
      cost = nodes
    }
    levels.push({ depth: d, nodes, size, cost })
  }
  const maxCost = Math.max(1, ...levels.map(l => l.cost))
  return levels.map(l => ({ ...l, barWidth: Math.max(8, (l.cost / maxCost) * 100) }))
})

const sandboxCalculation = computed(() => {
  const levels = sandboxLevels.value
  if (!levels.length) return ''
  if (sandboxPattern.value === 'balanced') {
    const cost = levels[0].cost || 1
    return `${cost} × ${sandboxDepth.value} levels`
  }
  if (sandboxPattern.value === 'decreasing') {
    return `1 + ${sandboxBranching.value} + ${sandboxBranching.value}² + ... ÷ ${sandboxBranching.value}`
  }
  // tree
  const b = sandboxBranching.value
  return `${b}⁰ + ${b}¹ + ${b}² + ... + ${b}^${sandboxDepth.value}`
})

const sandboxComplexity = computed(() => {
  if (sandboxPattern.value === 'balanced') return 'O(n log n)'
  if (sandboxPattern.value === 'decreasing') return 'O(log n)'
  const b = sandboxBranching.value
  return `O(${b}^n)`
})

const sandboxHint = computed(() => {
  const p = sandboxPattern.value
  const b = sandboxBranching.value
  const d = sandboxDepth.value

  // Questions only — never answers
  if (p === 'balanced' && b === 2) {
    return 'What happens to the bars if you increase branching to 3?'
  }
  if (p === 'balanced' && b >= 3) {
    return 'The bars stay equal. What does this tell you about the cost at each level?'
  }
  if (p === 'tree' && b === 2) {
    return 'Switch to Balanced with the same settings. What\'s different?'
  }
  if (p === 'tree' && b >= 3) {
    return 'What does the shape of these bars suggest about total work?'
  }
  if (p === 'decreasing' && d <= 2) {
    return 'Increase depth to 5. How much does total work change?'
  }
  if (p === 'decreasing' && d >= 4) {
    return 'Compare this to Tree mode with the same depth. Which grows faster?'
  }
  return null
})

const sandboxExplainPrompt = computed(() => {
  const p = sandboxPattern.value
  const b = sandboxBranching.value
  if (p === 'balanced' && b >= 2) return 'Can you explain in one sentence why branching doesn\'t change complexity here?'
  if (p === 'tree') return 'Why does this pattern produce exponential complexity?'
  if (p === 'decreasing') return 'Why is this O(log n) regardless of how large n is?'
  return null
})

const sandboxStep = computed(() => {
  if (sandboxPattern.value !== 'balanced') return 2
  if (sandboxBranching.value !== 2 || sandboxDepth.value !== 4) return 1
  return 1
})

const sandboxUserAnswer = ref('')
const sandboxFeedback = ref<{ type: string; message: string } | null>(null)
const showSandboxAnswer = ref(false)
const showMemoMode = ref(false)

// Reset feedback when pattern changes
// Reset execStep when memo mode changes (trace length changes)
watch(showMemoMode, () => {
  execStep.value = 0
})

watch(sandboxPattern, () => {
  sandboxFeedback.value = null
  sandboxUserAnswer.value = ''
  showSandboxAnswer.value = false
})

const sandboxSampleAnswer = computed(() => {
  const p = sandboxPattern.value
  if (p === 'balanced') return 'Each level does the same amount of work (n). With log n levels, total = n × log n.'
  if (p === 'tree') return 'Each level multiplies the number of nodes by the branching factor. The total grows exponentially.'
  if (p === 'decreasing') return 'Each level does a fraction of the previous level\'s work. The total is dominated by the first level.'
  return ''
})

function submitSandboxAnswer() {
  const answer = sandboxUserAnswer.value.toLowerCase().trim()
  if (!answer) return

  const p = sandboxPattern.value
  let feedback: { type: string; message: string }

  if (p === 'balanced') {
    const hasConstantCost = /constant|same|equal|uniform|n/.test(answer)
    const hasLogN = /log|level|depth/.test(answer)
    if (hasConstantCost && hasLogN) {
      feedback = { type: 'correct', message: 'Exactly. Constant cost per level × log n levels = O(n log n). You nailed the key insight.' }
    } else if (hasConstantCost || hasLogN) {
      feedback = { type: 'partial', message: 'Close. You got one part — now think about the other dimension (levels vs cost).' }
    } else {
      feedback = { type: 'hint', message: 'Focus on two things: what happens at EACH level, and how MANY levels there are.' }
    }
  } else if (p === 'tree') {
    const hasExponential = /exponential|grow|multiply|branch|2\^|explos/.test(answer)
    const hasBranching = /branch|split|each node|each call/.test(answer)
    if (hasExponential && hasBranching) {
      feedback = { type: 'correct', message: 'Right. Each node spawns b children, so total = b^depth. That\'s exponential growth.' }
    } else if (hasExponential || hasBranching) {
      feedback = { type: 'partial', message: 'You\'re on the right track. Now connect it: how does each node\'s branching affect total count?' }
    } else {
      feedback = { type: 'hint', message: 'Think about what each node does: it creates more nodes. What happens to the total?' }
    }
  } else {
    const hasDecrease = /shrink|decrease|smaller|half|fraction|divide/.test(answer)
    const hasDominant = /first|top|dominate|constant|log/.test(answer)
    if (hasDecrease && hasDominant) {
      feedback = { type: 'correct', message: 'Yes. The geometric shrink means total ≈ first term. That\'s why it\'s O(log n).' }
    } else if (hasDecrease || hasDominant) {
      feedback = { type: 'partial', message: 'Good instinct. Now ask yourself: which level contributes the most to total work?' }
    } else {
      feedback = { type: 'hint', message: 'Look at the bar sizes. What pattern do you see? Where is most of the work?' }
    }
  }

  sandboxFeedback.value = feedback
}

// --- Execution Mode: step through recursive calls ---
const subMode = ref<'execution' | 'analysis'>('execution')
const execStep = ref(0)
const execPlaying = ref(false)
let execPlayTimer: number | null = null

interface ReadyNodeAnalysis {
  id: string
  label: string
  unlockCount: number        // how many nodes become ready if we pick this one
  unlockTargets: string[]    // which specific nodes get unlocked (level 1)
  cascadeTargets: string[]   // level 2: nodes unlocked after level 1 is processed
  isPicked: boolean
}

interface ExecEvent {
  nodeId: string
  type: 'call' | 'return'
  name: string
  args: string
  returnValue?: string
  composition?: string       // e.g. "1 + 1 = 2"
  childResults?: string[]    // child return values used
  isBase: boolean
  depth: number
  parent?: string            // parent node id (for return flow)
  readyQueue?: string[]      // scheduler: all nodes ready at this moment (call events only)
  pickedFromReady?: boolean  // scheduler: this node was chosen from a non-trivial ready set
  readyAnalysis?: ReadyNodeAnalysis[]  // scheduler: per-node unlock analysis
}

// ── DAG execution trace: scheduler-aware topological order (Kahn's algorithm) ──
// Tracks the READY QUEUE at each step — shows why this node was picked
const dagExecTrace = computed<ExecEvent[]>(() => {
  try {
  const serverTree = store?.subproblemGraph?.call_tree
  const dag = store?.subproblemGraph?.dag
  if (!serverTree || !dag) return []

  const op = store?.subproblemGraph?.complexity?.combine_operation || 'unknown'

  // Collect unique nodes from the call tree
  const uniqueNodes = new Map<string, { id: string; args: string[]; result?: any; children: string[] }>()
  function collectUnique(node: { id: string; args: string[]; result?: any; children: any[] }) {
    if (!uniqueNodes.has(node.id)) {
      uniqueNodes.set(node.id, {
        id: node.id,
        args: node.args || [],
        result: node.result,
        children: (node.children || []).map((c: any) => c.id),
      })
    }
    for (const child of node.children || []) collectUnique(child)
  }
  collectUnique(serverTree)

  // Kahn's algorithm with ready queue tracking
  const inDegree = new Map<string, number>()
  const parentsOf = new Map<string, string[]>()
  for (const [id, node] of uniqueNodes) {
    if (!inDegree.has(id)) inDegree.set(id, 0)
    for (const childId of node.children) {
      if (!uniqueNodes.has(childId)) continue
      if (!parentsOf.has(childId)) parentsOf.set(childId, [])
      parentsOf.get(childId)!.push(id)
      inDegree.set(id, (inDegree.get(id) || 0) + 1)
    }
  }

  // Initial ready set: base cases (in-degree 0)
  const ready: string[] = []
  for (const [id, deg] of inDegree) {
    if (deg === 0) ready.push(id)
  }

  // Scheduler loop: pick from ready, record queue, unlock parents
  const processed = new Set<string>()
  const events: ExecEvent[] = []

  while (ready.length > 0) {
    const nodeId = ready.shift()!
    if (processed.has(nodeId)) continue
    processed.add(nodeId)

    const node = uniqueNodes.get(nodeId)
    if (!node) continue
    const isBase = node.children.length === 0
    const name = nodeId.split('(')[0]
    const argsStr = node.args.join(', ')

    // Snapshot: ALL nodes currently ready (including the one we just picked)
    const readySnapshot = [nodeId, ...ready.filter(id => !processed.has(id))]

    // Strategy analysis: for each ready node, compute what it would unlock (level 1 + cascade level 2)
    const readySet = new Set(readySnapshot)
    const analysis: ReadyNodeAnalysis[] = readySnapshot.map(rid => {
      // Level 1: simulate processing rid, which parents get unlocked?
      const unlocks: string[] = []
      const simDeg1 = new Map(inDegree) // copy for simulation
      for (const parentId of (parentsOf.get(rid) || [])) {
        if (processed.has(parentId)) continue
        const cur = simDeg1.get(parentId) || 1
        simDeg1.set(parentId, cur - 1)
        if (cur - 1 === 0) unlocks.push(parentId)
      }

      // Level 2: simulate processing each level-1 unlock, cascade further
      const cascade: string[] = []
      const simDeg2 = new Map(simDeg1) // copy after level-1 simulation
      for (const l1Id of unlocks) {
        for (const parentId of (parentsOf.get(l1Id) || [])) {
          if (processed.has(parentId) || readySet.has(parentId)) continue
          const cur = simDeg2.get(parentId) || 1
          simDeg2.set(parentId, cur - 1)
          if (cur - 1 === 0) cascade.push(parentId)
        }
      }

      return {
        id: rid,
        label: rid.split('(')[0],
        unlockCount: unlocks.length,
        unlockTargets: unlocks,
        cascadeTargets: cascade,
        isPicked: rid === nodeId,
      }
    })

    // Call event — scheduler picked this node from the ready queue
    events.push({
      nodeId,
      type: 'call',
      name,
      args: argsStr,
      isBase,
      depth: 0,
      readyQueue: readySnapshot,
      pickedFromReady: readySnapshot.length > 1,
      readyAnalysis: analysis,
    })

    // Return event — compute result
    const childResults = node.children
      .map((cid: string) => uniqueNodes.get(cid)?.result)
      .filter((r: any) => r != null)
      .map((r: any) => String(r))

    let composition: string | undefined
    if (childResults.length >= 2) {
      if (op === 'add') composition = childResults.join(' + ') + ' = ' + node.result
      else if (op === 'max') composition = 'max(' + childResults.join(', ') + ') = ' + node.result
      else if (op === 'min') composition = 'min(' + childResults.join(', ') + ') = ' + node.result
      else composition = childResults.join(' + ') + ' = ' + node.result
    }

    events.push({
      nodeId,
      type: 'return',
      name,
      args: argsStr,
      returnValue: node.result != null ? String(node.result) : undefined,
      composition,
      childResults: childResults.length > 0 ? childResults : undefined,
      isBase,
      depth: 0,
    })

    // Unlock parents: decrement in-degree, add newly ready nodes
    for (const parentId of (parentsOf.get(nodeId) || [])) {
      const newDeg = (inDegree.get(parentId) || 1) - 1
      inDegree.set(parentId, newDeg)
      if (newDeg === 0) ready.push(parentId)
    }
  }
  return events
  } catch (e) { console.error('[dagExecTrace]', e); return [] }
})

// Current ready queue at the execution step (DAG mode only)
const dagReadyQueue = computed(() => {
  if (!showMemoMode.value) return []
  const ev = execTrace.value[execStep.value]
  if (!ev?.readyQueue) return []
  // Return rich info: nodeId + short label
  return ev.readyQueue.map(id => ({
    id,
    label: id.split('(')[0],
    args: id.match(/\(([^)]*)\)/)?.[1] || '',
    isPicked: id === ev.nodeId,
  }))
})

// Set of node IDs currently in the ready queue (for SVG highlighting)
const dagReadyNodeIds = computed(() => {
  if (!showMemoMode.value) return new Set<string>()
  const ev = execTrace.value[execStep.value]
  return new Set(ev?.readyQueue || [])
})

// Scheduling strategy analysis: what each ready node unlocks
const dagReadyAnalysis = computed(() => {
  if (!showMemoMode.value) return []
  const ev = execTrace.value[execStep.value]
  return ev?.readyAnalysis || []
})

const execTrace = computed<ExecEvent[]>(() => {
  try {
  // In memo mode, use DAG execution trace (each subproblem computed once)
  if (showMemoMode.value && dagExecTrace.value.length > 0) {
    return dagExecTrace.value
  }

  const serverTree = store?.subproblemGraph?.call_tree
  if (!serverTree) return []

  const op = store?.subproblemGraph?.complexity?.combine_operation || 'unknown'
  const events: ExecEvent[] = []

  function dfs(node: { id: string; args: string[]; result?: any; children: any[] }, depth: number, parent?: string) {
    const nodeId = node.id
    const isBase = !node.children || node.children.length === 0
    const name = nodeId.split('(')[0]
    const argsStr = (node.args || []).join(', ')

    events.push({
      nodeId,
      type: 'call',
      name,
      args: argsStr,
      isBase,
      depth,
      parent,
    })

    for (const child of (node.children || [])) {
      dfs(child, depth + 1, nodeId)
    }

    // Return event with composition
    const resultStr = node.result != null ? String(node.result) : undefined
    const childResults = (node.children || [])
      .map((c: any) => c.result != null ? String(c.result) : null)
      .filter((r: string | null): r is string => r != null)

    let composition: string | undefined
    if (childResults.length >= 2) {
      if (op === 'add') composition = childResults.join(' + ') + ' = ' + resultStr
      else if (op === 'max') composition = `max(${childResults.join(', ')}) = ${resultStr}`
      else if (op === 'min') composition = `min(${childResults.join(', ')}) = ${resultStr}`
      else composition = childResults.join(' + ') + ' = ' + resultStr
    } else if (childResults.length === 1 && !isBase) {
      composition = resultStr
    }

    events.push({
      nodeId,
      type: 'return',
      name,
      args: argsStr,
      returnValue: resultStr,
      composition,
      childResults: childResults.length > 0 ? childResults : undefined,
      isBase,
      depth,
      parent,
    })
  }

  dfs(serverTree, 0)
  return events
  } catch (e) { console.error('[execTrace]', e); return [] }
})

const execCurrentCall = computed(() => {
  return execTrace.value[execStep.value] || null
})

const execCurrentStack = computed(() => {
  const events = execTrace.value
  const step = execStep.value
  if (!events.length) return []

  // Rebuild stack up to current step
  const stack: { name: string; args: string; returned: boolean; returnValue?: string }[] = []
  for (let i = 0; i <= step; i++) {
    const ev = events[i]
    if (ev.type === 'call') {
      stack.push({ name: ev.name, args: ev.args, returned: false })
    } else {
      // Return: mark top of stack as returned, then pop
      if (stack.length > 0) {
        stack[stack.length - 1].returned = true
        stack[stack.length - 1].returnValue = ev.returnValue
      }
      // Pop after a brief moment — but since we show snapshot, pop immediately
      stack.pop()
    }
  }
  return stack
})

// Step-level narrative: baseline style, one peak at most
const execStepNarrative = computed(() => {
  const ev = execCurrentCall.value
  if (!ev) return ''
  const op = store?.subproblemGraph?.complexity?.combine_operation || 'unknown'

  // Memo mode: DAG execution narrative with scheduler + invariant
  if (showMemoMode.value) {
    if (ev.type === 'call') {
      const readyQ = ev.readyQueue || []
      const readyCount = readyQ.length
      const pickedFromMultiple = ev.pickedFromReady && readyCount > 1

      if (ev.isBase) {
        const readyNote = pickedFromMultiple
          ? `\nReady queue: [${readyQ.map(id => id.split('(')[0]).join(', ')}] — scheduler picked this base case.`
          : ''
        return `Base case. Already known — no computation needed.${readyNote}`
      }
      // Show the invariant: dependencies are already computed
      const childIds = store?.subproblemGraph?.dag?.edges
        ?.filter(e => e.from === ev.nodeId)
        .map(e => e.to) || []
      const dagNode = store?.subproblemGraph?.dag?.nodes?.find(n => n.id === ev.nodeId)
      const callCount = dagNode?.call_count || 1
      const deps = childIds.map(c => c.split('(')[0]).join(' and ')
      const reuseNote = callCount > 1
        ? `\nThis subproblem was called ${callCount}x in the tree. Now: compute once.`
        : ''
      // Strategy reasoning: explain WHY this node was picked
      let schedulerNote = ''
      if (pickedFromMultiple && ev.readyAnalysis) {
        const analysis = ev.readyAnalysis
        const picked = analysis.find(a => a.isPicked)
        const others = analysis.filter(a => !a.isPicked)
        const maxUnlock = Math.max(...analysis.map(a => a.unlockCount))
        const isBestChoice = picked && picked.unlockCount === maxUnlock

        if (picked && others.length > 0) {
          const comparison = analysis.map(a => {
            const l1 = a.unlockCount === 0 ? 'unlocks nothing' : 'unlocks ' + a.unlockCount
            const l2 = a.cascadeTargets.length > 0 ? ` → cascades to ${a.cascadeTargets.length} more` : ''
            return `${a.label} → ${l1}${l2}`
          }).join(', ')
          const cascadeNote = picked.cascadeTargets.length > 0
            ? `\nHover to see cascade: ${picked.unlockTargets.map(t => t.split('(')[0]).join(', ')} would then unlock ${picked.cascadeTargets.map(t => t.split('(')[0]).join(', ')}.`
            : ''
          const reason = isBestChoice && maxUnlock > 0
            ? `Picked ${ev.name} — unlocks the most dependent nodes.${cascadeNote}`
            : picked.unlockCount === 0
            ? `Picked ${ev.name} — base case, resolved immediately.`
            : `Picked ${ev.name}.${cascadeNote}`
          schedulerNote = `\n${comparison}\n${reason}`
        }
      } else if (readyCount === 1) {
        schedulerNote = `\nOnly node with all dependencies satisfied.`
      }
      if (childIds.length > 0) {
        return `${ev.nodeId} can be computed now.\n${deps} are already solved.${reuseNote}${schedulerNote}`
      }
      return `Compute ${ev.nodeId} once.${reuseNote}${schedulerNote}`
    }
    // Return event in memo mode
    if (ev.isBase) {
      return `Base case: ${ev.returnValue}. Stored in cache.`
    }
    if (ev.composition && ev.childResults?.length === 2) {
      const [a, b] = ev.childResults
      return `Combine cached results: ${a} + ${b} = ${ev.returnValue}.\nNo recomputation — children were already solved.`
    }
    if (ev.returnValue != null) {
      return `Result: ${ev.returnValue}. Stored — will never be recomputed.`
    }
    return `Done.`
  }

  // Tree mode: standard narrative
  if (ev.type === 'call') {
    if (ev.isBase) {
      return `This is the simplest case. The answer is already known.`
    }
    const ch = store?.subproblemGraph?.dag?.edges?.filter(e => e.from === ev.nodeId) || []
    if (ch.length === 2) {
      return `This problem splits into two smaller versions of itself.`
    }
    if (ch.length === 1) {
      return `This reduces to one smaller problem.`
    }
    return `Solving this subproblem.`
  }

  // Return event — explain WHY we can combine
  if (ev.isBase) {
    return `Base case returns ${ev.returnValue}.`
  }
  if (ev.composition && ev.childResults?.length === 2) {
    const [a, b] = ev.childResults
    if (op === 'add') {
      return `These are answers to smaller versions of the same problem.\n\nSo we can combine them: ${a} + ${b} = ${ev.returnValue}.\n\nThat is why recursion works.`
    }
    if (op === 'max') {
      return `These are answers to smaller versions of the same problem.\n\nThe better one: ${ev.returnValue}.\n\nThat is why recursion works.`
    }
    if (op === 'min') {
      return `These are answers to smaller versions of the same problem.\n\nThe cheaper one: ${ev.returnValue}.\n\nThat is why recursion works.`
    }
    if (op === 'merge') {
      return `These are sorted halves of the same problem.\n\nMerging them into one sorted result.\n\nThat is why recursion works.`
    }
    return `These are answers to smaller versions of the same problem.\n\nCombining: ${ev.composition}.\n\nThat is why recursion works.`
  }
  if (ev.returnValue != null) {
    return `Returns ${ev.returnValue}.`
  }
  return `Done.`
})

// ── Call Tree: actual execution tree with repeated nodes ──────────────
interface TreeNode {
  id: string            // unique instance id (e.g. "fib(3)#2")
  nodeId: string        // subproblem id (e.g. "fib(3)")
  label: string
  argsStr: string       // arguments display
  result?: string
  children: TreeNode[]
  callIdx: number       // index in execTrace where this call happens
  returnIdx: number     // index in execTrace where this return happens
  isRepeated: boolean   // same subproblem seen before
  isBase: boolean
  depth: number
  x: number
  y: number
  narrative: string     // one-line explanation
}

const callTree = computed<TreeNode | null>(() => {
  try {
  const serverTree = store?.subproblemGraph?.call_tree
  const dag = store?.subproblemGraph?.dag
  if (!serverTree) return null

  const op = store?.subproblemGraph?.complexity?.combine_operation || 'unknown'
  const callCounts = new Map(dag?.nodes.map(n => [n.id, n.call_count]) || [])

  // Track which subproblems we've already seen (for repeated detection)
  const seen = new Set<string>()
  let instanceCounter = new Map<string, number>()

  function buildTree(node: { id: string; args: string[]; result?: any; children: any[] }, depth: number): TreeNode {
    const nodeId = node.id
    const isBase = !node.children || node.children.length === 0
    const isRepeated = seen.has(nodeId)
    seen.add(nodeId)

    // Unique instance id
    const count = (instanceCounter.get(nodeId) || 0) + 1
    instanceCounter.set(nodeId, count)
    const instanceId = `${nodeId}#${count}`

    // Build children
    const childNodes = (node.children || []).map(c => buildTree(c, depth + 1))

    const resultStr = node.result != null ? String(node.result) : undefined
    const childResults = childNodes
      .map(cn => cn.result)
      .filter((r): r is string => r != null)

    // Generate one-line narrative
    let narrative = ''
    if (isBase) {
      narrative = `Base case = ${resultStr}`
    } else if (isRepeated) {
      const totalCalls = callCounts.get(nodeId) || 1
      narrative = `Seen before (${totalCalls}x total) = ${resultStr}`
    } else if (childResults.length === 2) {
      if (op === 'add') narrative = `${childResults[0]} + ${childResults[1]} = ${resultStr}`
      else if (op === 'max') narrative = `max(${childResults[0]}, ${childResults[1]}) = ${resultStr}`
      else if (op === 'min') narrative = `min(${childResults[0]}, ${childResults[1]}) = ${resultStr}`
      else if (op === 'merge') narrative = `merge = ${resultStr}`
      else narrative = `${childResults.join(' + ')} = ${resultStr}`
    } else if (childResults.length === 1) {
      narrative = `= ${resultStr}`
    } else {
      narrative = `= ${resultStr}`
    }

    const argsStr = (node.args || []).join(', ')

    return {
      id: instanceId,
      nodeId,
      label: nodeId.split('(')[0],
      argsStr,
      result: resultStr,
      children: childNodes,
      callIdx: -1,
      returnIdx: -1,
      isRepeated,
      isBase,
      depth,
      x: 0,
      y: 0,
      narrative,
    }
  }

  const tree = buildTree(serverTree, 0)

  // Layout: compute subtree widths, then position
  const nodeW = 100
  const nodeH = 32
  const gapX = 16
  const gapY = 40

  function computeWidth(node: TreeNode): number {
    if (node.children.length === 0) return nodeW
    const childWidths = node.children.map(c => computeWidth(c))
    return Math.max(nodeW, childWidths.reduce((a, b) => a + b, 0) + gapX * (childWidths.length - 1))
  }

  function layoutNode_(node: TreeNode, x: number, y: number) {
    const totalW = computeWidth(node)
    node.x = x + (totalW - nodeW) / 2
    node.y = y
    let cx = x
    for (const child of node.children) {
      const cw = computeWidth(child)
      layoutNode_(child, cx, y + nodeH + gapY)
      cx += cw + gapX
    }
  }

  layoutNode_(tree, 0, 0)

  return tree
  } catch (e) { console.error('[callTree]', e); return null }
})

// Flatten tree for rendering
function flattenTree(node: TreeNode): TreeNode[] {
  const result = [node]
  for (const child of node.children) {
    result.push(...flattenTree(child))
  }
  return result
}

const callTreeNodes = computed(() => {
  if (!callTree.value) return []
  return flattenTree(callTree.value)
})

const callTreeEdges = computed(() => {
  if (!callTree.value) return []
  const edges: { from: TreeNode; to: TreeNode }[] = []
  function walk(node: TreeNode) {
    for (const child of node.children) {
      edges.push({ from: node, to: child })
      walk(child)
    }
  }
  walk(callTree.value)
  return edges
})

// ── Memo DAG: tree restructured into DAG when memo mode is on ─────
const memoDagNodes = computed(() => {
  if (!showMemoMode.value || !callTree.value) return []
  // Keep only first occurrence of each nodeId
  const seen = new Set<string>()
  const nodes: TreeNode[] = []
  function walk(node: TreeNode) {
    if (!seen.has(node.nodeId)) {
      seen.add(node.nodeId)
      // Clone with fresh layout
      nodes.push({ ...node, children: [], x: 0, y: 0 })
    }
    for (const child of node.children) walk(child)
  }
  walk(callTree.value)

  // Layout: depth-based (like DAG layout)
  // Find depth for each nodeId from the tree
  const depthMap = new Map<string, number>()
  function getDepth(node: TreeNode, depth: number) {
    if (!depthMap.has(node.nodeId) || depthMap.get(node.nodeId)! > depth) {
      depthMap.set(node.nodeId, depth)
    }
    for (const child of node.children) getDepth(child, depth + 1)
  }
  getDepth(callTree.value, 0)

  // Group by depth
  const byDepth = new Map<number, TreeNode[]>()
  for (const n of nodes) {
    const d = depthMap.get(n.nodeId) || 0
    if (!byDepth.has(d)) byDepth.set(d, [])
    byDepth.get(d)!.push(n)
  }

  // Position
  const nodeW = 100
  const nodeH = 32
  const gapX = 16
  const gapY = 24
  for (const [depth, ns] of byDepth) {
    const x = depth * (nodeW + gapX)
    ns.forEach((n, i) => {
      n.x = x
      n.y = i * (nodeH + gapY)
    })
  }

  return nodes
})

// Lookup map for DAG nodes (used by propagation edge rendering)
const memoDagNodesMap = computed(() => {
  return new Map(memoDagNodes.value.map(n => [n.nodeId, n]))
})

const memoDagEdges = computed(() => {
  if (!showMemoMode.value || !callTree.value) return []
  // Build edges: for each tree edge (parent → child), create edge between unique nodes
  const edgeSet = new Set<string>()
  const edges: { from: TreeNode; to: TreeNode }[] = []
  const nodeMap = new Map(memoDagNodes.value.map(n => [n.nodeId, n]))

  function walk(node: TreeNode) {
    for (const child of node.children) {
      const fromNode = nodeMap.get(node.nodeId)
      const toNode = nodeMap.get(child.nodeId)
      if (fromNode && toNode && fromNode.nodeId !== toNode.nodeId) {
        const key = `${fromNode.nodeId}->${toNode.nodeId}`
        if (!edgeSet.has(key)) {
          edgeSet.add(key)
          edges.push({ from: fromNode, to: toNode })
        }
      }
      walk(child)
    }
  }
  walk(callTree.value)
  return edges
})

const memoDagWidth = computed(() => {
  if (memoDagNodes.value.length === 0) return 400
  return Math.max(400, Math.max(...memoDagNodes.value.map(n => n.x)) + 130)
})

const memoDagHeight = computed(() => {
  if (memoDagNodes.value.length === 0) return 200
  return Math.max(200, Math.max(...memoDagNodes.value.map(n => n.y)) + 60)
})

const callTreeWidth = computed(() => {
  if (!callTree.value || callTreeNodes.value.length === 0) return 400
  return Math.max(400, Math.max(...callTreeNodes.value.map(n => n.x)) + 130)
})

const callTreeHeight = computed(() => {
  if (!callTree.value || callTreeNodes.value.length === 0) return 200
  return Math.max(200, Math.max(...callTreeNodes.value.map(n => n.y)) + 60)
})

// Which tree nodes are visible at current exec step
const visibleTreeNodes = computed(() => {
  const step = execStep.value
  const trace = execTrace.value
  const visible = new Set<string>()
  const instanceCounts = new Map<string, number>()
  for (let i = 0; i <= Math.min(step, trace.length - 1); i++) {
    const ev = trace[i]
    if (!ev) continue
    const count = (instanceCounts.get(ev.nodeId) || 0) + 1
    instanceCounts.set(ev.nodeId, count)
    visible.add(`${ev.nodeId}#${count}`)
  }
  return visible
})

// Which tree node is currently active (at execStep)
const activeTreeNode = computed(() => {
  const ev = execCurrentCall.value
  if (!ev) return null
  const trace = execTrace.value
  const step = execStep.value
  let count = 0
  for (let i = 0; i <= step; i++) {
    if (trace[i]?.nodeId === ev.nodeId) count++
  }
  return `${ev.nodeId}#${count}`
})

// Track which nodes should flash (first time becoming repeated)
const flashNodes = computed(() => {
  const step = execStep.value
  if (step <= 0) return new Set<string>()
  const prevVisible = new Set<string>()
  const instanceCounts = new Map<string, number>()
  const trace = execTrace.value
  for (let i = 0; i <= step - 1; i++) {
    const ev = trace[i]
    if (!ev) continue
    const count = (instanceCounts.get(ev.nodeId) || 0) + 1
    instanceCounts.set(ev.nodeId, count)
    prevVisible.add(`${ev.nodeId}#${count}`)
  }
  // Flash = visible now but was not visible before, AND is repeated
  const flashing = new Set<string>()
  for (const id of visibleTreeNodes.value) {
    if (!prevVisible.has(id)) {
      const node = callTreeNodes.value.find(n => n.id === id)
      if (node?.isRepeated) flashing.add(id)
    }
  }
  return flashing
})

// Count of repeated nodes visible so far
const repeatCount = computed(() => {
  let count = 0
  for (const id of visibleTreeNodes.value) {
    const node = callTreeNodes.value.find(n => n.id === id)
    if (node?.isRepeated) count++
  }
  return count
})

// Hover state for inline narrative
const hoveredNode = ref<string | null>(null)
const hoveredNarrative = computed(() => {
  if (!hoveredNode.value) return null
  const node = callTreeNodes.value.find(n => n.id === hoveredNode.value)
  return node?.narrative || null
})
const hoveredNodePos = computed(() => {
  if (!hoveredNode.value) return null
  const node = callTreeNodes.value.find(n => n.id === hoveredNode.value)
  return node ? { x: node.x, y: node.y } : null
})

// ── Upgrade 4: Active edge (who called whom) ──────────────────────
const activeEdge = computed(() => {
  const ev = execCurrentCall.value
  if (!ev || !ev.parent) return null
  // Find the tree node instances for parent and current
  const trace = execTrace.value
  const step = execStep.value
  // Count instances up to current step
  const instanceCounts = new Map<string, number>()
  let parentId: string | null = null
  let childId: string | null = null
  for (let i = 0; i <= step; i++) {
    const t = trace[i]
    if (!t) continue
    const count = (instanceCounts.get(t.nodeId) || 0) + 1
    instanceCounts.set(t.nodeId, count)
    if (i === step) {
      childId = `${t.nodeId}#${count}`
    }
    // Track parent: the last call event for the parent nodeId before current
    if (t.nodeId === ev.parent && t.type === 'call') {
      parentId = `${t.nodeId}#${count}`
    }
  }
  if (!parentId || !childId) return null
  const pNode = callTreeNodes.value.find(n => n.id === parentId)
  const cNode = callTreeNodes.value.find(n => n.id === childId)
  if (!pNode || !cNode) return null
  return { from: pNode, to: cNode }
})

// ── Upgrade 5: Repeat pointer (dashed line to first occurrence) ────
const repeatPointer = computed(() => {
  const ev = execCurrentCall.value
  if (!ev) return null
  const trace = execTrace.value
  const step = execStep.value
  // Find the current node's instance ID
  const instanceCounts = new Map<string, number>()
  let currentInstId: string | null = null
  let firstInstId: string | null = null
  for (let i = 0; i <= step; i++) {
    const t = trace[i]
    if (!t) continue
    const count = (instanceCounts.get(t.nodeId) || 0) + 1
    instanceCounts.set(t.nodeId, count)
    if (i === step) {
      currentInstId = `${t.nodeId}#${count}`
    }
    if (t.nodeId === ev.nodeId && count === 1) {
      firstInstId = `${t.nodeId}#1`
    }
  }
  if (!currentInstId || !firstInstId || currentInstId === firstInstId) return null
  const current = callTreeNodes.value.find(n => n.id === currentInstId)
  const first = callTreeNodes.value.find(n => n.id === firstInstId)
  if (!current || !first || !current.isRepeated) return null
  return { from: current, to: first }
})

// Scheduler hover: which ready node is the user considering?
const hoveredReadyNode = ref<string | null>(null)
// Nodes that would be unlocked if we pick hoveredReadyNode
const dagWillUnlockNodes = computed(() => {
  if (!showMemoMode.value || !hoveredReadyNode.value) return new Set<string>()
  const ev = execTrace.value[execStep.value]
  if (!ev?.readyAnalysis) return new Set<string>()
  const match = ev.readyAnalysis.find(a => a.id === hoveredReadyNode.value)
  return new Set(match?.unlockTargets || [])
})
// Level-2 cascade: nodes unlocked after level-1 is processed
const dagCascadeNodes = computed(() => {
  if (!showMemoMode.value || !hoveredReadyNode.value) return new Set<string>()
  const ev = execTrace.value[execStep.value]
  if (!ev?.readyAnalysis) return new Set<string>()
  const match = ev.readyAnalysis.find(a => a.id === hoveredReadyNode.value)
  return new Set(match?.cascadeTargets || [])
})
const memoCachedNodes = computed(() => {
  if (!showMemoMode.value) return new Set<string>()
  // nodeId already includes args (e.g. "fib(3)"), so this is subproblem-level dedup
  // Track which subproblems have been computed up to current playback step
  const cached = new Set<string>()
  const computed_ = new Set<string>()  // subproblems already computed
  const instanceCounts = new Map<string, number>()
  const trace = execTrace.value
  const step = execStep.value
  for (let i = 0; i <= Math.min(step, trace.length - 1); i++) {
    const t = trace[i]
    if (!t || t.type !== 'call') continue
    const count = (instanceCounts.get(t.nodeId) || 0) + 1
    instanceCounts.set(t.nodeId, count)
    const instId = `${t.nodeId}#${count}`
    if (computed_.has(t.nodeId)) {
      cached.add(instId) // would be a cache hit — same subproblem already solved
    }
    computed_.add(t.nodeId)
  }
  return cached
})

// ── Complexity curve: cumulative calls vs unique over time ─────────
const complexityCurve = computed(() => {
  const trace = execTrace.value
  if (trace.length === 0) return null
  // Build curve LIVE up to current step (not pre-computed)
  const step = execStep.value
  const points: { step: number; total: number; unique: number; waste: number }[] = []
  const seen = new Set<string>()
  let total = 0
  for (let i = 0; i <= Math.min(step, trace.length - 1); i++) {
    const t = trace[i]
    if (!t || t.type !== 'call') continue
    total++
    seen.add(t.nodeId)
    points.push({ step: i, total, unique: seen.size, waste: total - seen.size })
  }
  if (points.length < 2) return null
  const maxTotal = Math.max(points[points.length - 1].total, 2)
  const chartW = 200
  const chartH = 60
  const maxStep = Math.max(step, 1)
  const toX = (s: number) => (s / maxStep) * chartW
  const toY = (val: number) => chartH - (val / maxTotal) * chartH
  const totalPath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(p.step).toFixed(1)},${toY(p.total).toFixed(1)}`).join(' ')
  const uniquePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(p.step).toFixed(1)},${toY(p.unique).toFixed(1)}`).join(' ')
  // Waste area: polygon between total line and unique line
  const wastePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(p.step).toFixed(1)},${toY(p.total).toFixed(1)}`).join(' ')
    + ' ' + [...points].reverse().map((p, i) => `${i === 0 ? 'L' : 'L'}${toX(p.step).toFixed(1)},${toY(p.unique).toFixed(1)}`).join(' ')
    + ' Z'
  const curPoint = points[points.length - 1]
  return {
    chartW, chartH, totalPath, uniquePath, wastePath,
    curX: toX(curPoint.step),
    curTotalY: toY(curPoint.total),
    curUniqueY: toY(curPoint.unique),
    curTotal: curPoint.total,
    curUnique: curPoint.unique,
    curWaste: curPoint.waste,
    maxTotal,
  }
})

// Tree node styling helpers
function treeFill(node: TreeNode): string {
  if (showMemoMode.value) {
    if (memoCachedNodes.value.has(node.id)) return 'rgba(52,211,153,0.12)'
    return 'rgba(251,114,153,0.1)'
  }
  if (activeTreeNode.value === node.id) return 'rgba(34,211,238,0.12)'
  if (node.isRepeated) return 'rgba(251,114,153,0.1)'
  return 'rgba(100,100,120,0.05)'
}
function treeStroke(node: TreeNode): string {
  if (showMemoMode.value) {
    if (memoCachedNodes.value.has(node.id)) return '#34d399'
    return '#fb7299'
  }
  if (activeTreeNode.value === node.id) return 'var(--accent)'
  if (node.isRepeated) return '#fb7299'
  return 'var(--border)'
}
function treeStrokeWidth(node: TreeNode): number {
  if (showMemoMode.value) return 2
  return (activeTreeNode.value === node.id || node.isRepeated) ? 2 : 1
}
function treeLabelFill(node: TreeNode): string {
  if (showMemoMode.value) {
    if (memoCachedNodes.value.has(node.id)) return '#34d399'
    return '#fb7299'
  }
  if (activeTreeNode.value === node.id) return 'var(--accent)'
  if (node.isRepeated) return '#fb7299'
  return 'var(--text)'
}
function treeResultFill(node: TreeNode): string {
  return node.isRepeated ? 'rgba(251,114,153,0.7)' : 'var(--text-dim)'
}
function treeFilter(node: TreeNode): string | undefined {
  if (node.isRepeated && activeTreeNode.value !== node.id) return 'url(#repeat-glow)'
  return undefined
}

// Selected tree node for tooltip
const selectedTreeNode = ref<string | null>(null)
const selectedNodeNarrative = computed(() => {
  if (!selectedTreeNode.value) return null
  const node = callTreeNodes.value.find(n => n.id === selectedTreeNode.value)
  return node?.narrative || null
})

function onTreeNodeClick(node: TreeNode) {
  selectedTreeNode.value = selectedTreeNode.value === node.id ? null : node.id
}

function execStepBack() {
  if (execStep.value > 0) execStep.value--
}

function execStepForward() {
  if (execStep.value < execTrace.value.length - 1) execStep.value++
}

function execTogglePlay() {
  if (execPlaying.value) {
    execPlaying.value = false
    if (execPlayTimer) { clearTimeout(execPlayTimer); execPlayTimer = null }
    return
  }
  execPlaying.value = true
  execPlayNext()
}

function execPlayNext() {
  if (!execPlaying.value) return
  if (execStep.value < execTrace.value.length - 1) {
    execStep.value++
    execPlayTimer = window.setTimeout(execPlayNext, 400)
  } else {
    execPlaying.value = false
  }
}

const generalRule = computed(() => {
  const pattern = store?.subproblemGraph?.complexity?.pattern
  const levels = store?.subproblemGraph?.layout?.level_info?.length
  if (!pattern || !levels) return null

  if (isCostBalanced.value && levels >= 2) {
    return {
      pattern: 'Balanced Recursion (equal cost per level)',
      lines: [
        `If each level does ~${avgLevelCost.value} work`,
        `and there are ${levels} levels`,
        `→ total work = ${avgLevelCost.value} × ${levels}`,
      ],
      takeaway: `Whenever cost/level is constant, complexity = cost × depth. For divide-and-conquer splitting into k subproblems of size n/k: depth = log_k(n), cost/level = n → O(n log n).`,
    }
  }

  if (isCostDecreasing.value && levelCosts.value.length >= 2) {
    const first = levelCosts.value[0]
    return {
      pattern: 'Decreasing Work (cost shrinks each level)',
      lines: [
        `Work decreases: ${levelCostSummary.value}`,
        `The first level dominates the total`,
        `→ total ≈ first level = ${first}`,
      ],
      takeaway: `When work shrinks geometrically (each level ÷ constant), total ≈ first level. For T(n) = T(n/k): depth = log_k(n), cost/level = O(1) → O(log n).`,
    }
  }

  if (levelCosts.value.length >= 2) {
    const last = levelCosts.value[levelCosts.value.length - 1]
    return {
      pattern: 'Growing Work (cost increases each level)',
      lines: [
        `Work grows: ${levelCostSummary.value}`,
        `The bottom levels dominate`,
        `→ total ≈ last level × depth`,
      ],
      takeaway: `When work grows geometrically, the bottom levels dominate. For tree recursion like Fibonacci: depth = n, branching = 2 → total = O(2^n).`,
    }
  }

  return null
})

// WHY Narrative: combines algorithm-level pattern with step-level causal chain
const narrative = computed(() => {
  const path = criticalPathOrdered.value
  if (path.length < 2) return null

  // If we have algorithm-level narrative from pattern recognition, use it as the core
  const algoNarrative = store?.patternResult?.narrative
  if (algoNarrative) {
    // Build step-level detail from critical path
    const getExp = (step: number) => store.stepExplanations.find(e => e.step === step)
    const getStep = (step: number) => store.timeline.find(s => s.index === step)
    const sharedVars = (from: number, to: number): string[] => {
      const fs = getStep(from)
      const ts = getStep(to)
      if (!fs || !ts) return []
      const fromChanged = new Set(fs.changed || [])
      return [...fromChanged].filter(v => (ts.changed || []).includes(v) || (ts.code || '').includes(v))
    }
    const isControlEdge = (from: number, to: number) =>
      store.controlEdges.some(e => e.from === from && e.to === to)
    const _describeAction2 = (code: string) => {
      const c = code.trim()
      if (c.startsWith('return ')) return 'returns result'
      if (c.startsWith('if ') || c.startsWith('elif ')) return 'checks condition'
      if (c.startsWith('for ')) return 'iterates'
      if (c.startsWith('while ')) return 'loops'
      if (c.includes('= [')) return 'builds collection'
      if (c.includes('.append(')) return 'adds to collection'
      if (c.match(/^\w+\s*=\s*/)) return `computes ${c.split('=')[0].trim()}`
      return c.length > 24 ? c.slice(0, 24) + '…' : c
    }

    // Build a compact causal chain description
    const chainParts: string[] = []
    for (let i = 1; i < path.length; i++) {
      const prev = path[i - 1]
      const cur = path[i]
      const exp = getExp(cur)
      const imp = exp?.importance || 'medium'
      const explanation = exp?.importance_explanation || exp?.explanation || _describeAction2(getStep(cur)?.code || '')

      let transition = ''
      if (i === 1) transition = 'First, it '
      else if (i === path.length - 1) transition = 'Finally, it '
      else if (imp === 'high') transition = 'Then, critically, it '
      else transition = 'Then it '

      let cause = ''
      if (isControlEdge(prev, cur)) {
        const condCode = getStep(prev)?.code?.replace(/^(if |elif |for |while )/, '').replace(/:$/, '') || ''
        cause = ` based on "${condCode}"`
      } else {
        const shared = sharedVars(prev, cur)
        if (shared.length > 0) cause = ` using ${shared.join(' and ')}`
      }

      const expLower = explanation.charAt(0).toLowerCase() + explanation.slice(1)
      chainParts.push(`${transition}${expLower}${cause}`)
    }

    // Find turning points
    const turningPoints = path.filter(s => getExp(s)?.turning_point)
    let turningNote = ''
    if (turningPoints.length > 0 && path.length > 4) {
      const tpStep = turningPoints[turningPoints.length - 1]
      const tpExp = getExp(tpStep)?.importance_explanation || ''
      if (tpExp) turningNote = ` The key turning point is when ${tpExp.toLowerCase()}.`
    }

    // Compose: algorithm narrative + critical path chain + complexity reasoning
    const chain = chainParts.length > 0 ? ' Specifically: ' + chainParts.join(', then ') + '.' : ''
    const complexity = store?.patternResult?.complexity || ''
    const complexityNote = complexity ? ' ' + complexity : ''
    return algoNarrative + chain + turningNote + complexityNote
  }

  const getExp = (step: number) => store.stepExplanations.find(e => e.step === step)
  const getStep = (step: number) => store.timeline.find(s => s.index === step)
  const getAction = (step: number) => {
    const s = getStep(step)
    return s ? _describeAction(s.code || '') : `step ${step}`
  }
  const getExplanation = (step: number) => {
    const exp = getExp(step)
    return exp?.importance_explanation || exp?.explanation || getAction(step)
  }
  const getImportance = (step: number) => getExp(step)?.importance || 'medium'

  // Find shared variables between two steps
  const sharedVars = (from: number, to: number): string[] => {
    const fs = getStep(from)
    const ts = getStep(to)
    if (!fs || !ts) return []
    const fromChanged = new Set(fs.changed || [])
    return [...fromChanged].filter(v => (ts.changed || []).includes(v) || (ts.code || '').includes(v))
  }

  // Check if edge is control flow
  const isControlEdge = (from: number, to: number) =>
    store.controlEdges.some(e => e.from === from && e.to === to)

  // Detect pattern: is this a loop-heavy path?
  const loopSteps = path.filter(s => {
    const exp = getExp(s)
    return exp?.importance_reasons?.some(r => r.includes('loop'))
  })
  const isLoopHeavy = loopSteps.length >= path.length * 0.4

  // Detect pattern: does it have a base case?
  const baseCaseStep = path.find(s => {
    const exp = getExp(s)
    return exp?.importance_reasons?.includes('base_case')
  })

  // Build sentences
  const sentences: string[] = []

  // Opening: what does the algorithm do
  const firstAction = getAction(path[0])
  const lastAction = getAction(path[path.length - 1])
  const lastExp = getExp(path[path.length - 1])
  const returnReason = lastExp?.importance_reasons?.includes('return')

  if (path.length <= 3) {
    // Short path: compact summary
    sentences.push(`此算法通过 ${path.length} 个关键步骤执行。`)
  } else if (isLoopHeavy) {
    sentences.push(`此算法通过 ${path.length} 个关键步骤处理数据，迭代构建结果。`)
  } else {
    sentences.push(`此算法通过 ${path.length} 个关键步骤得出结果。`)
  }

  // Base case: if present, mention it early
  if (baseCaseStep && baseCaseStep !== path[0]) {
    const bcExp = getExplanation(baseCaseStep)
    sentences.push(`首先检查基准情况 — ${bcExp.toLowerCase()} — 处理最简单的情况再继续。`)
  }

  // Middle: walk the path with causal transitions
  const startIdx = baseCaseStep && baseCaseStep !== path[0] ? path.indexOf(baseCaseStep) + 1 : 1
  for (let i = startIdx; i < path.length; i++) {
    const prev = path[i - 1]
    const cur = path[i]
    const exp = getExplanation(cur)
    const imp = getImportance(cur)

    // Transition word
    let transition = ''
    if (i === 1 && !baseCaseStep) {
      transition = '首先，'
    } else if (i === path.length - 1) {
      transition = '最后，'
    } else if (i === path.length - 2) {
      transition = '然后，'
    } else if (imp === 'high') {
      transition = '关键地，'
    } else {
      transition = '接下来，'
    }

    // Causal link
    let cause = ''
    const control = isControlEdge(prev, cur)
    const shared = sharedVars(prev, cur)
    if (control) {
      const condCode = getStep(prev)?.code?.replace(/^(if |elif |for |while )/, '').replace(/:$/, '') || ''
      cause = ` 因为 "${condCode}" 决定了这条路径`
    } else if (shared.length > 0) {
      cause = ` 使用上一步的 ${shared.join(' 和 ')}`
    }

    // Compose sentence
    const expLower = exp.charAt(0).toLowerCase() + exp.slice(1)
    if (cause) {
      sentences.push(`${transition}${expLower}${cause}.`)
    } else {
      sentences.push(`${transition}${expLower}.`)
    }
  }

  // Closing: wrap up with result significance
  if (returnReason) {
    const resultCode = getStep(path[path.length - 1])?.code || ''
    const resultVar = resultCode.replace(/^return\s*/, '').trim()
    if (resultVar) {
      sentences.push(`最终产生结果: ${resultVar}。`)
    } else {
      sentences.push(`最终产生结果。`)
    }
  }

  // Complexity note if we have turning points
  const turningPoints = path.filter(s => getExp(s)?.turning_point)
  if (turningPoints.length > 0 && path.length > 4) {
    const tpStep = turningPoints[turningPoints.length - 1]
    const tpExp = getExplanation(tpStep)
    sentences.push(`最重要的转折点在第 ${tpStep} 步，此时 ${tpExp.toLowerCase()}。`)
  }

  return sentences.join(' ')
})

// Downstream steps for causal highlighting
const downstreamSteps = computed(() => {
  if (causalSource.value === null) return new Set<number>()
  const exp = store.stepExplanations.find(e => e.step === causalSource.value)
  if (!exp?.affects?.length) return new Set<number>()
  return new Set(exp.affects)
})

// Causal graph data for SVG rendering
interface GraphNode { id: number; x: number; y: number; code: string; importance: string; score: number; folded?: number; explanation?: string; reasonIcons?: string[] }
interface GraphEdge { from: number; to: number; type: 'data' | 'control' }

// Map step index to its loop group (if any)
const stepToLoopGroup = computed(() => {
  const map = new Map<number, { rep: number; count: number }>()
  for (const group of store.loopGroups) {
    if (group.steps.length < 3) continue
    const rep = group.steps[0]  // representative step
    for (const idx of group.steps) {
      map.set(idx, { rep, count: group.steps.length })
    }
  }
  return map
})

const causalGraph = computed(() => {
  if (causalSource.value === null) return null
  const srcExp = store.stepExplanations.find(e => e.step === causalSource.value)
  if (!srcExp?.affects?.length) return null

  const srcIdx = causalSource.value

  // Collect all reachable nodes (data edges, transitive)
  const allNodes = new Set<number>([srcIdx])
  const dataEdges: GraphEdge[] = []
  const queue = [srcIdx]
  const visited = new Set<number>()

  while (queue.length > 0) {
    const cur = queue.shift()!
    if (visited.has(cur)) continue
    visited.add(cur)
    const exp = store.stepExplanations.find(e => e.step === cur)
    for (const target of (exp?.affects || [])) {
      if (target === srcIdx) continue
      allNodes.add(target)
      dataEdges.push({ from: cur, to: target, type: 'data' })
      if (!visited.has(target)) queue.push(target)
    }
  }

  // Add control edges involving these nodes
  const controlEdges: GraphEdge[] = []
  for (const ce of store.controlEdges) {
    if (allNodes.has(ce.from) || allNodes.has(ce.to)) {
      allNodes.add(ce.from)
      allNodes.add(ce.to)
      controlEdges.push({ from: ce.from, to: ce.to, type: 'control' })
    }
  }

  if (allNodes.size <= 1) return null

  // Find upstream (steps that affect source via data)
  const upstream: number[] = []
  for (const exp of store.stepExplanations) {
    if (exp.affects?.includes(srcIdx) && exp.step !== srcIdx && !allNodes.has(exp.step)) {
      upstream.push(exp.step)
      allNodes.add(exp.step)
    }
  }

  // Loop folding: collapse repeated iterations into representative nodes
  const foldedNodes = new Map<number, number>()  // step → representative
  const foldCounts = new Map<number, number>()    // representative → count
  for (const id of allNodes) {
    const group = stepToLoopGroup.value.get(id)
    if (group && allNodes.has(group.rep)) {
      foldedNodes.set(id, group.rep)
      foldCounts.set(group.rep, group.count)
    }
  }

  // Unique nodes after folding
  const uniqueNodes = new Set<number>()
  for (const id of allNodes) {
    uniqueNodes.add(foldedNodes.get(id) || id)
  }

  // Layout: multi-column for chains
  const colMap = new Map<number, number>()
  const srcRep = foldedNodes.get(srcIdx) || srcIdx
  colMap.set(srcRep, upstream.length > 0 ? 1 : 0)

  // BFS to assign columns for downstream
  const bfsQueue: [number, number][] = []
  for (const e of dataEdges) {
    const fromRep = foldedNodes.get(e.from) || e.from
    const toRep = foldedNodes.get(e.to) || e.to
    if (fromRep === srcRep && toRep !== srcRep) {
      bfsQueue.push([toRep, colMap.get(srcRep)! + 1])
    }
  }
  const bfsVisited = new Set<number>([srcRep])
  while (bfsQueue.length > 0) {
    const [node, col] = bfsQueue.shift()!
    if (bfsVisited.has(node)) continue
    bfsVisited.add(node)
    colMap.set(node, col)
    for (const e of dataEdges) {
      const fromRep = foldedNodes.get(e.from) || e.from
      const toRep = foldedNodes.get(e.to) || e.to
      if (fromRep === node && !bfsVisited.has(toRep) && uniqueNodes.has(toRep)) {
        bfsQueue.push([toRep, col + 1])
      }
    }
  }

  // Upstream gets column -1
  for (const id of upstream) {
    const rep = foldedNodes.get(id) || id
    colMap.set(rep, -1)
  }

  // Assign columns for any unassigned nodes
  for (const id of uniqueNodes) {
    if (!colMap.has(id)) colMap.set(id, 0)
  }

  // Group nodes by column
  const columns = new Map<number, number[]>()
  for (const [id, col] of colMap) {
    if (!columns.has(col)) columns.set(col, [])
    columns.get(col)!.push(id)
  }

  const nodeW = 160, nodeH = 48, gapY = 16, colGap = 200
  const maxCol = Math.max(...columns.keys(), 0)
  const minCol = Math.min(...columns.keys(), 0)

  // Position nodes
  const nodes: GraphNode[] = []
  const nodeById = new Map<number, GraphNode>()

  for (const [col, ids] of columns) {
    ids.forEach((id, row) => {
      const step = store.timeline.find(s => s.index === id)
      const exp = store.stepExplanations.find(e => e.step === id)
      const x = (col - minCol) * colGap
      const y = row * (nodeH + gapY)
      const folded = foldCounts.get(id)
      const node: GraphNode = {
        id, x, y,
        code: step?.code || '',
        importance: exp?.importance || 'low',
        score: exp?.importance_score || 0,
        folded: folded && folded > 1 ? folded : undefined,
        explanation: exp?.importance_explanation,
        reasonIcons: exp?.importance_reasons?.map(r => reasonIcon(r)).slice(0, 3),
      }
      nodes.push(node)
      nodeById.set(id, node)
    })
  }

  // Dedupe edges, remap folded nodes
  const edgeSet = new Set<string>()
  const edges: GraphEdge[] = []
  const allRawEdges = [...dataEdges, ...controlEdges]
  for (const e of allRawEdges) {
    const from = foldedNodes.get(e.from) || e.from
    const to = foldedNodes.get(e.to) || e.to
    if (from === to) continue  // skip self-loops after folding
    const key = `${from}-${to}-${e.type}`
    if (!edgeSet.has(key) && nodeById.has(from) && nodeById.has(to)) {
      edgeSet.add(key)
      edges.push({ from, to, type: e.type })
    }
  }

  const maxRows = Math.max(...[...columns.values()].map(c => c.length), 1)
  const width = (maxCol - minCol + 1) * colGap + nodeW + 20
  const height = maxRows * (nodeH + gapY) + 20

  return { nodes, edges, width, height, nodeW, nodeH, nodeById }
})

const steps = computed(() => store.timeline)
const hasStepExplanations = computed(() => store.stepExplanations.length > 0)

// Auto-collapse: only show steps above score threshold
const visibleSteps = computed(() => {
  if (store.showAllSteps || !hasStepExplanations.value) return steps.value
  return steps.value.filter(step => {
    const exp = store.stepExplanations.find(e => e.step === step.index)
    return !exp || (exp.importance_score || 0) >= 0.30
  })
})

function skippedCount(beforeIdx: number): number {
  if (store.showAllSteps || !hasStepExplanations.value) return 0
  const beforeVisible = visibleSteps.value.findIndex(s => s.index === beforeIdx)
  if (beforeVisible <= 0) return 0
  const prevVisibleIdx = visibleSteps.value[beforeVisible - 1].index
  return beforeIdx - prevVisibleIdx - 1
}

// Use focused explanation if available, fall back to batch
const activeExplanation = computed(() => {
  if (store.focusedExplanation && store.focusedExplanation.step === (store?.currentStep ?? 0)) {
    return store.focusedExplanation
  }
  return store?.currentStepExplanation
})

function importanceColor(imp: string): string {
  if (imp === 'high') return 'var(--primary)'
  if (imp === 'low') return 'var(--text-muted)'
  return 'var(--highlight)'
}

function importanceIcon(imp: string): string {
  if (imp === 'high') return '⭐'
  if (imp === 'low') return '—'
  return '○'
}

function reasonIcon(r: string): string {
  const map: Record<string, string> = {
    base_case: '🛑',
    bounds_check: '🛡',
    branch: '🔀',
    loop_entry: '🔁',
    loop_break: '⏭',
    loop_continue: '↪',
    return: '↩',
    raise: '⚠',
    error_boundary: '🛡',
    generator: '⚡',
    function_call: '▸',
    mutation: '🔄',
    large_value_jump: '📈',
    value_jump: '📊',
    type_change: '🔀',
    boolean_flip: '🔀',
    new_var: '✦',
    string_growth: '📝',
    collection_growth: '📦',
    future_impact: '→',
    turning_point: '💫',
    state_change: '•',
  }
  if (r.includes('_new_vars')) return '✦'
  if (r.includes('_vars_changed')) return '🔄'
  return map[r] || '•'
}

function patternLabel(p: string): string {
  const map: Record<string, string> = {
    memoization: 'Memoization',
    divide_and_conquer: 'Divide & Conquer',
    binary_search: 'Binary Search',
    tree_recursion: 'Tree Recursion',
    linear_recursion: 'Linear Recursion',
    recursion: 'Recursion',
    search: 'Search',
    accumulation: 'Accumulation',
    state_transformation: 'State Transform',
    iteration: 'Iteration',
    sequential: 'Sequential',
  }
  return map[p] || p
}

function propertyLabel(p: string): string {
  const map: Record<string, string> = {
    overlapping_subproblems: 'Overlapping Subproblems',
    result_reuse: 'Result Reuse',
    divide_structure: 'Divide Structure',
    recursive_decomposition: 'Recursive Decomposition',
    early_termination: 'Early Termination',
    accumulation: 'Accumulation',
    state_evolution: 'State Evolution',
    iteration: 'Iteration',
    sequential: 'Sequential',
  }
  return map[p] || p
}

function reasonLabel(r: string): string {
  const map: Record<string, string> = {
    branch: 'conditional branch',
    loop_entry: 'loop start',
    loop_break: 'loop break',
    loop_continue: 'loop continue',
    return: 'return statement',
    raise: 'exception raised',
    error_boundary: 'try block',
    error_catch: 'exception caught',
    generator: 'yield',
    function_call: 'function call',
    state_change: 'state changed',
    large_value_jump: 'large value jump',
    turning_point: 'turning point',
    llm_high: 'LLM: high',
    llm_low: 'LLM: low',
  }
  if (r.includes('_vars_changed')) return r.replace('_', ' ')
  if (r.includes('_new_vars')) return r.replace('_', ' ')
  return map[r] || r
}

function scoreToHeatColor(score: number): string {
  if (score >= 0.7) return 'var(--primary)'
  if (score >= 0.5) return '#fb923c'
  if (score >= 0.30) return 'var(--highlight)'
  return 'var(--border)'
}

// Fetch focused explanation for current step
let focusDebounce: number | null = null
async function fetchFocus(stepIndex: number) {
  if (focusDebounce) clearTimeout(focusDebounce)
  focusDebounce = window.setTimeout(async () => {
    store.focusLoading = true
    try {
      const result = await getExplainStepFocus(
        store.code, stepIndex, store.funcName, store.language,
        2, 2, 'mock', '', store.sessionId
      )
      if (result) store.focusedExplanation = result
    } finally {
      store.focusLoading = false
    }
  }, 300)
}

// Normal play
function togglePlay() {
  store.isPlaying = !store.isPlaying
  explainPlaying.value = false
  if (store.isPlaying) {
    playNext()
  } else if (playTimer.value) {
    clearTimeout(playTimer.value)
    playTimer.value = null
  }
}

function playNext() {
  if (!store.isPlaying) return
  if ((store?.currentStep ?? 0) < (store?.totalSteps ?? 0) - 1) {
    store.nextStep()
    playTimer.value = window.setTimeout(playNext, store.playSpeed)
  } else {
    store.isPlaying = false
  }
}

// Explain Mode — auto-play with AI narration + importance-based pause
function toggleExplainMode() {
  if (explainPlaying.value) {
    explainPlaying.value = false
    store.isPlaying = false
    if (playTimer.value) {
      clearTimeout(playTimer.value)
      playTimer.value = null
    }
    return
  }

  explainPlaying.value = true
  store.isPlaying = true
  store.goToStep(0)
  explainPlayNext()
}

function explainPlayNext() {
  if (!explainPlaying.value) return
  if ((store?.currentStep ?? 0) < (store?.totalSteps ?? 0) - 1) {
    store.nextStep()

    // Importance-based delay
    const currentImp = store?.currentStepExplanation?.importance || 'medium'
    let delay: number
    if (currentImp === 'high') {
      delay = 2500  // Pause at important steps
    } else if (currentImp === 'low') {
      delay = 600   // Skip through boilerplate
    } else {
      delay = 1200  // Normal pace
    }

    playTimer.value = window.setTimeout(explainPlayNext, delay)
  } else {
    explainPlaying.value = false
    store.isPlaying = false
  }
}

// Go to step + fetch focus
function goToStepWithFocus(idx: number) {
  store.goToStep(idx)
  fetchFocus(idx)
  // Toggle causal source: click same step again to clear
  const exp = store.stepExplanations.find(e => e.step === idx)
  if (exp?.affects?.length) {
    causalSource.value = causalSource.value === idx ? null : idx
  } else {
    causalSource.value = null
  }
}

onUnmounted(() => {
  if (playTimer.value) clearTimeout(playTimer.value)
  if (focusDebounce) clearTimeout(focusDebounce)
})
</script>

<template>
  <div class="timeline-panel animate-slide-up">
    <!-- No-data guard: prevents slider with max=-1 from corrupting currentStep -->
    <div v-if="(store?.totalSteps ?? 0) === 0" class="empty-state">
      <p>暂无时间线数据，请先运行分析</p>
    </div>

    <!-- Controls -->
    <div class="controls" v-if="(store?.totalSteps ?? 0) > 0">
      <button class="btn btn-secondary btn-sm" @click="goToStepWithFocus((store?.currentStep ?? 0) - 1)">&#9664;</button>
      <button class="btn btn-sm" :class="(store?.isPlaying ?? false) && !explainPlaying ? 'btn-primary' : 'btn-secondary'" @click="togglePlay">
        {{ (store?.isPlaying ?? false) && !explainPlaying ? '&#9632;' : '&#9654;' }}
      </button>
      <button class="btn btn-secondary btn-sm" @click="goToStepWithFocus((store?.currentStep ?? 0) + 1)">&#9654;</button>
      <input
        type="range"
        class="slider"
        :min="0"
        :max="Math.max(0, (store?.totalSteps ?? 0) - 1)"
        :value="(store?.currentStep ?? 0)"
        @input="goToStepWithFocus(+($event.target as HTMLInputElement).value)"
      />
      <span class="step-display">{{ (store?.currentStep ?? 0) }} / {{ Math.max(0, (store?.totalSteps ?? 0) - 1) }}</span>
      <input type="number" class="speed-input" v-model.number="store.playSpeed" min="100" max="3000" step="100" />
      <span class="speed-label">ms</span>

      <button
        v-if="hasStepExplanations"
        class="btn btn-sm explain-btn"
        :class="explainPlaying ? 'explain-active' : ''"
        @click="toggleExplainMode"
        title="AI-guided walkthrough"
      >
        {{ explainPlaying ? 'Stop' : 'Explain' }}
      </button>
    </div>

    <!-- AI Step Explanation -->
    <div
      v-if="activeExplanation"
      class="step-explain card"
      :class="{
        'is-turning-point': activeExplanation.turning_point,
        'is-high': activeExplanation.importance === 'high',
        'is-loading': (store?.focusLoading ?? false),
      }"
    >
      <div class="explain-header">
        <span class="explain-badge">
          {{ (store?.focusLoading ?? false) ? '...' : 'AI' }}
        </span>
        <span class="explain-step-label">Step {{ (store?.currentStep ?? 0) }}</span>
        <!-- Reason icons (primary visual) -->
        <span v-if="activeExplanation.importance_reasons?.length" class="explain-reason-icons">
          <span
            v-for="r in activeExplanation.importance_reasons"
            :key="r"
            class="reason-icon-lg"
            :title="reasonLabel(r)"
          >{{ reasonIcon(r) }}</span>
        </span>
        <span
          class="explain-importance"
          :style="{ color: importanceColor(activeExplanation.importance) }"
        >
          {{ importanceIcon(activeExplanation.importance) }}
        </span>
        <span v-if="activeExplanation.turning_point" class="turning-badge">关键转折</span>
      </div>
      <!-- Natural language explanation (secondary, compact) -->
      <div v-if="activeExplanation.importance_explanation" class="explain-importance-text">
        {{ activeExplanation.importance_explanation }}
      </div>
      <!-- Causal link: affects downstream steps -->
      <div v-if="activeExplanation.affects?.length" class="explain-causal">
        <span class="causal-icon">→</span>
        影响步骤 {{ activeExplanation.affects.join(', ') }}
      </div>
      <!-- LLM explanation (main content) -->
      <div class="explain-text">{{ activeExplanation.explanation }}</div>
      <div v-if="activeExplanation.what_changed" class="explain-diff">
        {{ activeExplanation.what_changed }}
      </div>
      <!-- Score bar -->
      <div v-if="activeExplanation.importance_score != null" class="explain-score-bar">
        <div class="score-track">
          <div class="score-fill" :style="{ width: (activeExplanation.importance_percentile ?? activeExplanation.importance_score) * 100 + '%', background: scoreToHeatColor(activeExplanation.importance_percentile ?? activeExplanation.importance_score) }"></div>
        </div>
        <span class="score-num">{{ ((activeExplanation.importance_percentile ?? activeExplanation.importance_score) * 100).toFixed(0) }}%ile</span>
      </div>
    </div>

    <!-- Current step highlight -->
    <div
      v-if="(store?.currentStepData)"
      class="current-step card"
      :class="{ 'step-glow': activeExplanation?.importance === 'high' }"
    >
      <div class="step-header">
        <span class="step-num">Step {{ (store?.currentStepData).index }}</span>
        <span class="step-loc">{{ (store?.currentStepData).file }}:{{ (store?.currentStepData).line }}</span>
      </div>
      <div class="step-code">{{ (store?.currentStepData).code }}</div>
      <div v-if="(store?.currentStepData).changed.length" class="step-changes">
        已变更: {{ (store?.currentStepData).changed.join(', ') }}
      </div>
      <div v-if="(store?.currentStepData).new_vars.length" class="step-new">
        新增: {{ (store?.currentStepData).new_vars.join(', ') }}
      </div>
    </div>

    <!-- Variable state -->
    <div v-if="(store?.currentStepData)" class="vars-section">
      <div class="section-title">变量</div>
      <div class="var-grid">
        <div
          v-for="(info, name) in (store?.currentStepData).vars"
          :key="name"
          class="var-card"
          :class="{ changed: info.changed, 'is-new': info.is_new }"
        >
          <div class="var-name">{{ name }}</div>
          <div class="var-value">{{ info.value }}</div>
          <div class="var-type">{{ info.type }}</div>
          <span v-if="info.changed" class="var-badge changed-badge">已变更</span>
          <span v-if="info.is_new" class="var-badge new-badge">新</span>
        </div>
      </div>
    </div>

    <!-- Importance Heatmap -->
    <div v-if="hasStepExplanations" class="heatmap-bar">
      <div class="heatmap-label">重要性</div>
      <div class="heatmap-row">
        <div
          v-for="step in steps"
          :key="step.index"
          class="heatmap-cell"
          :class="{ 'cell-current': step.index === (store?.currentStep ?? 0) }"
          :style="{
            background: scoreToHeatColor(store.stepExplanations.find(e => e.step === step.index)?.importance_percentile ?? store.stepExplanations.find(e => e.step === step.index)?.importance_score ?? 0),
            opacity: (store.stepExplanations.find(e => e.step === step.index)?.importance_percentile ?? store.stepExplanations.find(e => e.step === step.index)?.importance_score ?? 0) * 0.7 + 0.3,
          }"
          :title="`Step ${step.index}: ${((store.stepExplanations.find(e => e.step === step.index)?.importance_percentile ?? 0) * 100).toFixed(0)}%ile`"
          @mouseenter="hoveredStep = step.index"
          @mouseleave="hoveredStep = null"
          @click="goToStepWithFocus(step.index)"
        />
      </div>
    </div>

    <!-- WHY Narrative -->
    <div v-if="narrative" class="narrative card">
      <div class="narrative-header">
        <span class="narrative-badge">原理</span>
        <span v-if="store?.patternResult?.pattern" class="pattern-badge">{{ patternLabel(store?.patternResult.pattern) }}</span>
        <span class="narrative-title">算法运作原理</span>
        <span class="narrative-path">{{ criticalPathOrdered.join(' → ') }}</span>
      </div>
      <div class="narrative-text">{{ narrative }}</div>
      <!-- Complexity reasoning -->
      <div v-if="store?.patternResult?.complexity" class="narrative-complexity">
        <span class="complexity-icon">⚡</span>
        {{ store?.patternResult.complexity }}
      </div>
      <!-- Evidence chips -->
      <div v-if="store?.patternResult?.properties" class="narrative-evidence">
        <span
          v-for="(data, prop) in store?.patternResult.properties"
          :key="prop"
          class="evidence-chip"
          :title="(data.evidence_sample || []).join('\n')"
        >
          <span class="evidence-name">{{ propertyLabel(String(prop)) }}</span>
          <span class="evidence-conf">{{ Math.round((data.confidence || 0) * 100) }}%</span>
        </span>
      </div>
    </div>

    <!-- Step list -->
    <div class="step-list">
      <div class="section-title">
        <span>步骤</span>
        <button
          v-if="hasStepExplanations"
          class="toggle-all-btn"
          @click="store.showAllSteps = !store.showAllSteps"
        >
          {{ (store?.showAllSteps ?? false) ? '自动折叠' : `显示全部 (${(store?.totalSteps ?? 0)})` }}
        </button>
      </div>
      <div class="steps-scroll">
        <template v-for="step in visibleSteps" :key="step.index">
          <!-- Skip indicator -->
          <div v-if="skippedCount(step.index) > 0" class="skip-indicator">
            跳过 {{ skippedCount(step.index) }} 步
          </div>
          <div
            class="step-item"
            :class="{
              active: step.index === (store?.currentStep ?? 0),
              'has-ai': hasStepExplanations,
              'step-important': store.stepExplanations.find(e => e.step === step.index)?.importance === 'high',
              'step-weight-high': (store.stepExplanations.find(e => e.step === step.index)?.importance_score || 0) >= 0.55,
              'step-weight-medium': (store.stepExplanations.find(e => e.step === step.index)?.importance_score || 0) >= 0.30 && (store.stepExplanations.find(e => e.step === step.index)?.importance_score || 0) < 0.55,
              'is-causal-source': causalSource === step.index,
              'is-downstream': downstreamSteps.has(step.index),
            }"
            :title="store.stepExplanations.find(e => e.step === step.index)?.importance_explanation || ''"
            @mouseenter="hoveredStep = step.index"
            @mouseleave="hoveredStep = null"
            @click="goToStepWithFocus(step.index)"
          >
            <span class="step-idx">{{ step.index }}</span>
            <!-- Reason icons (compact, inline) -->
            <span v-if="hasStepExplanations" class="step-reason-icons">
              <span
                v-for="r in (store.stepExplanations.find(e => e.step === step.index)?.importance_reasons || []).slice(0, 3)"
                :key="r"
                class="reason-icon"
                :title="reasonLabel(r)"
              >{{ reasonIcon(r) }}</span>
            </span>
            <span class="step-code-text">{{ step.code }}</span>
            <!-- Causal "affects" label -->
            <span
              v-if="causalSource === step.index && store.stepExplanations.find(e => e.step === step.index)?.affects?.length"
              class="causal-affects-label"
            >
              影响 → {{ store.stepExplanations.find(e => e.step === step.index)?.affects?.join(', ') }}
            </span>
            <span
              v-if="hasStepExplanations"
              class="step-score-bar"
              :style="{ background: scoreToHeatColor(store.stepExplanations.find(e => e.step === step.index)?.importance_percentile ?? store.stepExplanations.find(e => e.step === step.index)?.importance_score ?? 0) }"
            ></span>
            <span v-if="step.changed.length" class="step-changes-dot">&#x1F534;</span>
          </div>
        </template>
      </div>
    </div>

    <!-- Causal Graph -->
    <div v-if="causalGraph" class="causal-graph card">
      <div class="section-title">
        <span>因果图</span>
        <span class="graph-legend">
          <span class="legend-item"><span class="legend-line legend-data"></span> 数据</span>
          <span class="legend-item"><span class="legend-line legend-control"></span> 控制</span>
        </span>
      </div>
      <svg
        :width="causalGraph.width"
        :height="causalGraph.height"
        class="graph-svg"
      >
        <!-- Edges (arrows) -->
        <defs>
          <marker id="arrow-data" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="rgba(167,139,250,0.6)" />
          </marker>
          <marker id="arrow-control" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="rgba(34,211,238,0.5)" />
          </marker>
        </defs>
        <!-- Edges -->
        <template v-for="(edge, i) in causalGraph.edges" :key="'e'+i">
          <g v-if="causalGraph.nodeById.get(edge.from) && causalGraph.nodeById.get(edge.to)">
            <!-- Visible edge -->
            <line
              :x1="causalGraph.nodeById.get(edge.from)!.x + causalGraph.nodeW"
              :y1="causalGraph.nodeById.get(edge.from)!.y + causalGraph.nodeH / 2"
              :x2="causalGraph.nodeById.get(edge.to)!.x"
              :y2="causalGraph.nodeById.get(edge.to)!.y + causalGraph.nodeH / 2"
              :stroke="criticalPath.has(edge.from) && criticalPath.has(edge.to)
                ? 'var(--primary)'
                : (executedSteps.has(edge.from) && executedSteps.has(edge.to))
                  ? (edge.type === 'control' ? 'rgba(34,211,238,0.5)' : 'rgba(167,139,250,0.5)')
                  : 'rgba(100,100,120,0.15)'"
              :stroke-width="criticalPath.has(edge.from) && criticalPath.has(edge.to) ? 2.5 : (executedSteps.has(edge.from) && executedSteps.has(edge.to)) ? 2 : 1"
              :stroke-dasharray="edge.type === 'control' ? '6,3' : 'none'"
              :marker-end="edge.type === 'control' ? 'url(#arrow-control)' : 'url(#arrow-data)'"
            />
            <!-- Invisible click target (wider) -->
            <line
              :x1="causalGraph.nodeById.get(edge.from)!.x + causalGraph.nodeW"
              :y1="causalGraph.nodeById.get(edge.from)!.y + causalGraph.nodeH / 2"
              :x2="causalGraph.nodeById.get(edge.to)!.x"
              :y2="causalGraph.nodeById.get(edge.to)!.y + causalGraph.nodeH / 2"
              stroke="transparent"
              stroke-width="12"
              class="edge-click-target"
              @click.stop="selectedEdge = selectedEdge?.from === edge.from && selectedEdge?.to === edge.to ? null : { from: edge.from, to: edge.to }"
            />
          </g>
        </template>
        <!-- Nodes -->
        <g
          v-for="node in causalGraph.nodes"
          :key="'n'+node.id"
          :transform="`translate(${node.x}, ${node.y})`"
          class="graph-node"
          :class="{
            'node-source': node.id === causalSource,
            'node-high': node.importance === 'high',
            'node-hovered': hoveredStep === node.id,
            'node-executed': executedSteps.has(node.id),
            'node-current': node.id === (store?.currentStep ?? 0),
            'node-critical': criticalPath.has(node.id),
          }"
          @click="goToStepWithFocus(node.id)"
          @mouseenter="hoveredStep = node.id"
          @mouseleave="hoveredStep = null"
        >
          <rect
            :width="causalGraph.nodeW"
            :height="causalGraph.nodeH"
            rx="6"
            :fill="node.id === causalSource ? 'rgba(34,211,238,0.12)' : criticalPath.has(node.id) ? 'rgba(251,114,153,0.10)' : node.id === (store?.currentStep ?? 0) ? 'rgba(251,114,153,0.15)' : executedSteps.has(node.id) ? 'rgba(167,139,250,0.08)' : 'rgba(100,100,120,0.04)'"
            :stroke="hoveredStep === node.id ? 'var(--highlight)' : criticalPath.has(node.id) ? 'var(--primary)' : node.importance === 'high' ? 'var(--primary)' : node.id === causalSource ? 'var(--highlight)' : executedSteps.has(node.id) ? 'rgba(167,139,250,0.3)' : 'var(--border)'"
            :stroke-width="hoveredStep === node.id || node.id === (store?.currentStep ?? 0) || criticalPath.has(node.id) ? 2.5 : 1.5"
          />
          <!-- Semantic explanation (PRIMARY — what this step does) -->
          <text v-if="node.explanation" x="8" y="14" class="node-meaning" :fill="criticalPath.has(node.id) ? 'var(--primary)' : executedSteps.has(node.id) ? 'var(--text)' : 'rgba(120,120,140,0.5)'">
            {{ node.explanation.length > 26 ? node.explanation.slice(0, 26) + '…' : node.explanation }}
          </text>
          <!-- Reason icons + code (SECONDARY — implementation detail) -->
          <text v-if="node.reasonIcons?.length" x="8" y="30" class="node-icons" :fill="executedSteps.has(node.id) ? 'var(--text-muted)' : 'rgba(120,120,140,0.3)'">
            {{ node.reasonIcons.join('') }}
          </text>
          <text :x="node.reasonIcons?.length ? 8 + node.reasonIcons.length * 11 : 8" y="30" class="node-code" :fill="executedSteps.has(node.id) ? 'var(--text-muted)' : 'rgba(120,120,140,0.3)'">
            #{{ node.id }} {{ node.code.length > 16 ? node.code.slice(0, 16) + '…' : node.code }}
          </text>
          <!-- Execution path dot -->
          <circle
            v-if="node.id === (store?.currentStep ?? 0)"
            :cx="causalGraph.nodeW - 8"
            :cy="causalGraph.nodeH / 2"
            r="4"
            fill="var(--primary)"
            class="exec-dot"
          />
        </g>
      </svg>
      <!-- Critical path legend -->
      <div class="critical-path-legend">
        <span class="path-dot"></span>
        <span>WHY path: {{ [...criticalPath].sort((a,b) => a-b).join(' → ') }}</span>
      </div>
      <!-- Edge explanation panel -->
      <div v-if="edgeExplanation" class="edge-explain">
        <div class="edge-explain-header">
          <span class="edge-explain-icon">{{ edgeExplanation.isControl ? '⊘' : '→' }}</span>
          <span>Step {{ edgeExplanation.from }} → Step {{ edgeExplanation.to }}</span>
          <button class="edge-close" @click="selectedEdge = null">×</button>
        </div>
        <div class="edge-explain-text">{{ edgeExplanation.text }}</div>
        <div v-if="edgeExplanation.sharedVars.length" class="edge-vars">
          Shared: {{ edgeExplanation.sharedVars.join(', ') }}
        </div>
      </div>
    </div>

    <!-- Subproblem Graph: Computation DAG + Complexity -->
    <div v-if="store?.subproblemGraph?.is_recursive && store?.subproblemGraph?.layout" class="subproblem-section">
      <div class="subproblem-header">
        <span class="subproblem-badge">DAG</span>
        <span class="subproblem-title">Computation Structure</span>
        <span class="subproblem-stats" v-if="store?.subproblemGraph.dag">
          {{ store?.subproblemGraph.dag.unique_count }} unique / {{ store?.subproblemGraph.dag.total_count }} total calls
        </span>
        <span class="submode-tabs">
          <button :class="['submode-btn', { active: subMode === 'execution' }]" @click="subMode = 'execution'">Execution</button>
          <button :class="['submode-btn', { active: subMode === 'analysis' }]" @click="subMode = 'analysis'">Analysis</button>
        </span>
      </div>

      <!-- Execution Mode: call trace + stack + return flow -->
      <div v-if="subMode === 'execution'" class="execution-mode">
        <!-- Execution controls -->
        <div class="exec-controls">
          <button class="exec-btn" @click="execStepBack" :disabled="execStep <= 0">◀</button>
          <span class="exec-step-label">Step {{ execStep }} / {{ execTrace.length - 1 }}</span>
          <button class="exec-btn" @click="execStepForward" :disabled="execStep >= execTrace.length - 1">▶</button>
          <button class="exec-btn exec-play" @click="execTogglePlay">{{ execPlaying ? '⏸' : '▶▶' }}</button>
        </div>
        <!-- Ready Queue (DAG scheduler mode) -->
        <div v-if="showMemoMode && dagReadyQueue.length > 0" class="ready-queue">
          <div class="ready-queue-header">
            <span class="ready-queue-badge">SCHEDULER</span>
            <span class="ready-queue-title">Ready Queue</span>
            <span class="ready-queue-count">{{ dagReadyQueue.length }} node{{ dagReadyQueue.length > 1 ? 's' : '' }}</span>
          </div>
          <!-- Strategy analysis: what each ready node unlocks -->
          <div class="ready-strategy">
            <div
              v-for="item in dagReadyAnalysis"
              :key="item.id"
              class="strategy-row"
              :class="{
                'strategy-picked': item.isPicked,
                'strategy-other': !item.isPicked,
                'strategy-hovered': hoveredReadyNode === item.id,
              }"
              @mouseenter="hoveredReadyNode = item.id"
              @mouseleave="hoveredReadyNode = null"
            >
              <span class="strategy-icon">{{ item.isPicked ? '▶' : '○' }}</span>
              <span class="strategy-label">{{ item.label }}</span>
              <span class="strategy-arrow">→</span>
              <span class="strategy-unlock" :class="{ 'strategy-leaf': item.unlockCount === 0 }">
                {{ item.unlockCount === 0 ? 'leaf — no impact' : item.unlockCount === 1 ? 'unlocks 1' : 'unlocks ' + item.unlockCount }}
              </span>
              <span v-if="item.unlockTargets.length > 0" class="strategy-targets">
                ({{ item.unlockTargets.map(t => t.split('(')[0]).join(', ') }})
              </span>
              <span v-if="item.cascadeTargets.length > 0" class="strategy-cascade">
                +{{ item.cascadeTargets.length }} cascade
              </span>
              <span v-if="item.isPicked" class="strategy-badge">PICKED</span>
            </div>
          </div>
          <!-- Pick reasoning: why this choice -->
          <div v-if="dagReadyAnalysis.length > 1" class="ready-queue-pick">
            <span class="pick-arrow">→</span>
            <span class="pick-text">
              <template v-if="dagReadyAnalysis.find(a => a.isPicked)?.unlockCount ?? 0 > 0">
                Picked <strong>{{ dagReadyAnalysis.find(a => a.isPicked)?.label }}</strong>
                — unlocks {{ dagReadyAnalysis.find(a => a.isPicked)?.unlockCount }} dependent node{{ (dagReadyAnalysis.find(a => a.isPicked)?.unlockCount ?? 0) > 1 ? 's' : '' }}
              </template>
              <template v-else>
                Picked <strong>{{ dagReadyAnalysis.find(a => a.isPicked)?.label }}</strong>
                — base case, no dependencies to unlock
              </template>
            </span>
          </div>
        </div>
        <!-- Call stack -->
        <div class="exec-stack">
          <div class="stack-label">Call Stack</div>
          <div class="stack-frames">
            <div
              v-for="(frame, i) in execCurrentStack"
              :key="i"
              class="stack-frame"
              :class="{ 'stack-active': i === execCurrentStack.length - 1 }"
            >
              <span class="frame-name">{{ frame.name }}</span>
              <span class="frame-args">{{ frame.args }}</span>
              <span v-if="frame.returned" class="frame-return">→ {{ frame.returnValue }}</span>
            </div>
          </div>
        </div>
        <!-- Current call highlight -->
        <div class="exec-current" v-if="execCurrentCall">
          <!-- Step narrative: the "explanation" — primary -->
          <div class="step-narrative" v-if="execStepNarrative">{{ execStepNarrative }}</div>
          <!-- Raw data: secondary, compact -->
          <div class="current-raw">
            <span class="current-label">{{ execCurrentCall.type === 'call' ? '→' : '←' }}</span>
            <span class="current-call">{{ execCurrentCall.name }}({{ execCurrentCall.args }})</span>
            <span v-if="execCurrentCall.returnValue != null" class="current-return">→ {{ execCurrentCall.returnValue }}</span>
          </div>
          <!-- Operation type: what kind of combine -->
          <div v-if="execCurrentCall.type === 'return' && store?.subproblemGraph?.complexity?.combine_operation_label && store?.subproblemGraph.complexity.combine_operation !== 'unknown'" class="combine-operation">
            <span class="combine-label">Combine</span>
            <span class="combine-type">{{ store?.subproblemGraph.complexity.combine_operation_label }}</span>
          </div>
          <!-- Return Composition: how child results combine -->
          <div v-if="execCurrentCall.composition" class="current-composition">
            <span class="compose-icon">=</span>
            <span class="compose-expr">{{ execCurrentCall.composition }}</span>
          </div>
          <div v-if="execCurrentCall.childResults?.length" class="current-children">
            <span class="children-label">from</span>
            <span v-for="(r, i) in execCurrentCall.childResults" :key="i" class="child-result">{{ execCurrentCall.name }}({{ execCurrentCall.args?.split(',')[i]?.trim() || '' }}) → {{ r }}</span>
          </div>
        </div>
        <!-- Call Tree: visual execution tree with repeated nodes -->
        <div class="call-tree-container" v-if="callTreeNodes.length > 0">
          <div class="call-tree-header">
            <span class="call-tree-badge">TREE</span>
            <span class="call-tree-title">Call Tree</span>
            <span class="call-tree-legend">
              <span v-if="!showMemoMode" class="legend-item"><span class="legend-dot legend-new"></span> first seen</span>
              <span v-if="!showMemoMode" class="legend-item"><span class="legend-dot legend-repeat"></span> repeated</span>
              <span v-if="!showMemoMode" class="legend-item"><span class="legend-dot legend-active"></span> current</span>
              <span v-if="showMemoMode" class="legend-item"><span class="legend-dot legend-cached"></span> cache hit</span>
              <span v-if="showMemoMode" class="legend-item"><span class="legend-dot legend-computed"></span> computed</span>
            </span>
            <button class="memo-toggle" :class="{ active: showMemoMode }" @click="showMemoMode = !showMemoMode">
              {{ showMemoMode ? '🧠 Memo ON' : 'Memo OFF' }}
            </button>
          </div>
          <!-- Execution invariant (memo mode) -->
          <div v-if="showMemoMode" class="exec-invariant">
            <span class="invariant-label">INVARIANT</span>
            <span class="invariant-text">A node is computed only after all its dependencies are computed.</span>
          </div>
          <div class="call-tree-scroll">
            <!-- TREE MODE (memo OFF) -->
            <svg
              v-if="!showMemoMode"
              :width="callTreeWidth"
              :height="callTreeHeight"
              class="call-tree-svg"
            >
              <defs>
                <marker id="tree-arrow" markerWidth="6" markerHeight="5" refX="6" refY="2.5" orient="auto">
                  <polygon points="0 0, 6 2.5, 0 5" fill="rgba(167,139,250,0.4)" />
                </marker>
                <marker id="tree-arrow-active" markerWidth="6" markerHeight="5" refX="6" refY="2.5" orient="auto">
                  <polygon points="0 0, 6 2.5, 0 5" fill="var(--accent)" />
                </marker>
                <marker id="tree-arrow-repeat" markerWidth="6" markerHeight="5" refX="6" refY="2.5" orient="auto">
                  <polygon points="0 0, 6 2.5, 0 5" fill="#fb7299" />
                </marker>
                <filter id="repeat-glow">
                  <feGaussianBlur stdDeviation="1.5" result="blur"/>
                  <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                </filter>
                <filter id="active-glow">
                  <feGaussianBlur stdDeviation="2" result="blur"/>
                  <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                </filter>
              </defs>
              <!-- Edges -->
              <g v-for="(edge, i) in callTreeEdges" :key="'te'+i">
                <line
                  v-if="visibleTreeNodes.has(edge.from.id) && visibleTreeNodes.has(edge.to.id)"
                  :x1="edge.from.x + 50"
                  :y1="edge.from.y + 32"
                  :x2="edge.to.x + 50"
                  :y2="edge.to.y"
                  :stroke="activeTreeNode === edge.to.id ? 'var(--accent)' : 'rgba(167,139,250,0.25)'"
                  :stroke-width="activeTreeNode === edge.to.id ? 2 : 1"
                  :marker-end="activeTreeNode === edge.to.id ? 'url(#tree-arrow-active)' : 'url(#tree-arrow)'"
                />
              </g>
              <!-- Active edge glow -->
              <g v-if="activeEdge">
                <line
                  :x1="activeEdge.from.x + 50"
                  :y1="activeEdge.from.y + 32"
                  :x2="activeEdge.to.x + 50"
                  :y2="activeEdge.to.y"
                  stroke="var(--accent)"
                  stroke-width="3"
                  stroke-linecap="round"
                  class="active-edge-glow"
                  marker-end="url(#tree-arrow-active)"
                />
                <circle r="3" fill="var(--accent)" class="flow-dot">
                  <animateMotion
                    :dur="'0.6s'"
                    repeatCount="1"
                    :path="`M${activeEdge.from.x + 50},${activeEdge.from.y + 32} L${activeEdge.to.x + 50},${activeEdge.to.y}`"
                  />
                </circle>
              </g>
              <!-- Repeat pointer -->
              <g v-if="repeatPointer">
                <line
                  :x1="repeatPointer.from.x + 50"
                  :y1="repeatPointer.from.y + 16"
                  :x2="repeatPointer.to.x + 50"
                  :y2="repeatPointer.to.y + 16"
                  stroke="#fb7299"
                  stroke-width="1.5"
                  stroke-dasharray="4,3"
                  stroke-linecap="round"
                  class="repeat-pointer-line"
                  marker-end="url(#tree-arrow-repeat)"
                />
                <text
                  :x="(repeatPointer.from.x + repeatPointer.to.x) / 2 + 50"
                  :y="(repeatPointer.from.y + repeatPointer.to.y) / 2 + 12"
                  class="repeat-pointer-label"
                  fill="#fb7299"
                  text-anchor="middle"
                >seen before</text>
              </g>
              <!-- Nodes -->
              <g
                v-for="node in callTreeNodes"
                :key="node.id"
                :transform="`translate(${node.x}, ${node.y})`"
                class="tree-node"
                :class="{
                  'tree-node-active': activeTreeNode === node.id,
                  'tree-node-repeat': node.isRepeated,
                  'tree-node-flash': flashNodes.has(node.id),
                  'tree-node-enter': visibleTreeNodes.has(node.id),
                }"
                v-if="visibleTreeNodes.has(node.id)"
                @mouseenter="hoveredNode = node.id"
                @mouseleave="hoveredNode = null"
              >
                <rect
                  width="100" height="32" rx="6"
                  :fill="treeFill(node)"
                  :stroke="treeStroke(node)"
                  :stroke-width="treeStrokeWidth(node)"
                  :filter="treeFilter(node)"
                />
                <text x="8" y="14" class="tree-label" :fill="treeLabelFill(node)">
                  {{ node.label }}{{ node.argsStr ? '(' + node.argsStr + ')' : '' }}
                </text>
                <text v-if="node.result !== undefined" x="8" y="26" class="tree-result" :fill="treeResultFill(node)">
                  = {{ node.result }}
                </text>
                <g v-if="node.isRepeated" :transform="`translate(84, 2)`">
                  <rect width="14" height="12" rx="3" fill="rgba(251,114,153,0.3)" />
                  <text x="7" y="9.5" text-anchor="middle" class="tree-repeat-badge" fill="#fb7299">↺</text>
                </g>
                <circle
                  v-if="flashNodes.has(node.id)"
                  cx="50" cy="16" r="60"
                  fill="none"
                  stroke="rgba(255,68,68,0.4)"
                  stroke-width="2"
                  class="burst-ring"
                />
              </g>
              <!-- Hover narrative -->
              <g
                v-if="hoveredNarrative && hoveredNodePos"
                :transform="`translate(${hoveredNodePos.x - 10}, ${hoveredNodePos.y + 36})`"
                class="tree-hover-narrative"
              >
                <rect
                  :width="Math.max(120, hoveredNarrative.length * 6.5 + 16)"
                  height="24" rx="4"
                  fill="rgba(15,23,42,0.92)"
                  stroke="rgba(251,114,153,0.4)"
                  stroke-width="1"
                />
                <text x="8" y="16" class="hover-narrative-text" fill="#e2e8f0">
                  {{ hoveredNarrative }}
                </text>
              </g>
            </svg>

            <!-- DAG MODE (memo ON) — tree restructured into DAG -->
            <!-- Visual rule hint -->
            <div v-if="showMemoMode && hoveredReadyNode" class="dag-hint">
              <span class="dag-hint-icon">→</span>
              <span class="dag-hint-text">
                <template v-if="dagWillUnlockNodes.size > 0">
                  <span class="dag-hint-bright">Bright</span> = direct unlock
                  <template v-if="dagCascadeNodes.size > 0"> · <span class="dag-hint-dim">Dim</span> = cascade</template>
                </template>
                <template v-else>
                  No nodes unlocked — this is a leaf choice
                </template>
              </span>
            </div>
            <div v-else-if="showMemoMode" class="dag-hint dag-hint-idle">
              <span class="dag-hint-text">Hover a ready node to see what it unlocks</span>
            </div>
            <svg
              v-if="showMemoMode"
              :width="memoDagWidth"
              :height="memoDagHeight"
              class="call-tree-svg"
            >
              <defs>
                <marker id="dag-arrow" markerWidth="6" markerHeight="5" refX="6" refY="2.5" orient="auto">
                  <polygon points="0 0, 6 2.5, 0 5" fill="rgba(52,211,153,0.5)" />
                </marker>
                <marker id="unlock-arrow" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                  <polygon points="0 0, 8 3, 0 6" fill="#fbb92a" />
                </marker>
              </defs>
              <!-- DAG Edges -->
              <g v-for="(edge, i) in memoDagEdges" :key="'de'+i">
                <line
                  :x1="edge.from.x + 50"
                  :y1="edge.from.y + 32"
                  :x2="edge.to.x + 50"
                  :y2="edge.to.y"
                  stroke="rgba(52,211,153,0.35)"
                  stroke-width="1.5"
                  marker-end="url(#dag-arrow)"
                />
              </g>
              <!-- Propagation edges: level-1 (amber) and level-2 (dim amber) -->
              <g v-for="item in (hoveredReadyNode ? dagReadyAnalysis.filter(a => a.id === hoveredReadyNode) : [])" :key="'prop-'+item.id">
                <!-- Level-1 edges: ready node → direct unlocks -->
                <g v-for="targetId in item.unlockTargets" :key="'pe-'+targetId">
                  <line
                    v-if="memoDagNodesMap.get(targetId) && memoDagNodesMap.get(item.id)"
                    :x1="memoDagNodesMap.get(item.id)!.x + 50"
                    :y1="memoDagNodesMap.get(item.id)!.y + 16"
                    :x2="memoDagNodesMap.get(targetId)!.x + 50"
                    :y2="memoDagNodesMap.get(targetId)!.y + 16"
                    stroke="#fbb92a"
                    stroke-width="2.5"
                    stroke-dasharray="6,3"
                    class="propagation-edge"
                    marker-end="url(#unlock-arrow)"
                  />
                </g>
                <!-- Level-2 edges: level-1 → cascade unlocks -->
                <g v-for="cascadeId in item.cascadeTargets" :key="'ce-'+cascadeId">
                  <g v-for="l1Id in item.unlockTargets" :key="'ce-'+l1Id+'-'+cascadeId">
                    <line
                      v-if="memoDagNodesMap.get(l1Id) && memoDagNodesMap.get(cascadeId)"
                      :x1="memoDagNodesMap.get(l1Id)!.x + 50"
                      :y1="memoDagNodesMap.get(l1Id)!.y + 16"
                      :x2="memoDagNodesMap.get(cascadeId)!.x + 50"
                      :y2="memoDagNodesMap.get(cascadeId)!.y + 16"
                      stroke="rgba(251,193,58,0.35)"
                      stroke-width="1.5"
                      stroke-dasharray="4,4"
                      class="cascade-edge"
                    />
                  </g>
                </g>
              </g>
              <!-- DAG Nodes -->
              <g
                v-for="node in memoDagNodes"
                :key="node.nodeId"
                :transform="`translate(${node.x}, ${node.y})`"
                class="tree-node"
                :class="{
                  'dag-node-ready': dagReadyNodeIds.has(node.nodeId) && execCurrentCall?.nodeId !== node.nodeId,
                  'dag-node-picked': execCurrentCall?.nodeId === node.nodeId && showMemoMode,
                  'dag-node-will-unlock': dagWillUnlockNodes.has(node.nodeId),
                  'dag-node-cascade': dagCascadeNodes.has(node.nodeId) && !dagWillUnlockNodes.has(node.nodeId),
                }"
                @mouseenter="hoveredNode = node.id"
                @mouseleave="hoveredNode = null"
              >
                <!-- Cascade glow (level-2, dim amber) -->
                <rect
                  v-if="dagCascadeNodes.has(node.nodeId) && !dagWillUnlockNodes.has(node.nodeId)"
                  x="-3" y="-3" width="106" height="38" rx="8"
                  fill="rgba(251,193,58,0.04)"
                  stroke="rgba(251,193,58,0.3)"
                  stroke-width="1.5"
                  stroke-dasharray="3,3"
                  class="cascade-ring"
                />
                <!-- Will-unlock glow (level-1, amber) -->
                <rect
                  v-if="dagWillUnlockNodes.has(node.nodeId)"
                  x="-4" y="-4" width="108" height="40" rx="9"
                  fill="rgba(251,193,58,0.08)"
                  stroke="rgba(251,193,58,0.7)"
                  stroke-width="2"
                  class="will-unlock-ring"
                />
                <!-- Ready glow (behind the rect) -->
                <rect
                  v-if="dagReadyNodeIds.has(node.nodeId) && execCurrentCall?.nodeId !== node.nodeId && !dagWillUnlockNodes.has(node.nodeId)"
                  x="-3" y="-3" width="106" height="38" rx="8"
                  fill="none"
                  stroke="rgba(52,211,153,0.5)"
                  stroke-width="2"
                  stroke-dasharray="4,2"
                  class="ready-glow-ring"
                />
                <rect
                  width="100" height="32" rx="6"
                  :fill="dagWillUnlockNodes.has(node.nodeId) ? 'rgba(251,193,58,0.15)' : dagCascadeNodes.has(node.nodeId) ? 'rgba(251,193,58,0.06)' : execCurrentCall?.nodeId === node.nodeId && showMemoMode ? 'rgba(52,211,153,0.2)' : dagReadyNodeIds.has(node.nodeId) ? 'rgba(52,211,153,0.12)' : 'rgba(52,211,153,0.08)'"
                  :stroke="dagWillUnlockNodes.has(node.nodeId) ? '#fbb92a' : dagCascadeNodes.has(node.nodeId) ? 'rgba(251,193,58,0.4)' : execCurrentCall?.nodeId === node.nodeId && showMemoMode ? '#34d399' : '#34d399'"
                  :stroke-width="dagWillUnlockNodes.has(node.nodeId) ? 2 : dagCascadeNodes.has(node.nodeId) ? 1.5 : execCurrentCall?.nodeId === node.nodeId && showMemoMode ? 2.5 : 1.5"
                />
                <text x="8" y="14" class="tree-label" :fill="dagWillUnlockNodes.has(node.nodeId) ? '#fbb92a' : dagCascadeNodes.has(node.nodeId) ? 'rgba(251,193,58,0.6)' : '#34d399'">
                  {{ node.label }}{{ node.argsStr ? '(' + node.argsStr + ')' : '' }}
                </text>
                <text v-if="node.result !== undefined" x="8" y="26" class="tree-result" :fill="dagWillUnlockNodes.has(node.nodeId) ? 'rgba(251,185,42,0.7)' : dagCascadeNodes.has(node.nodeId) ? 'rgba(251,193,58,0.4)' : 'rgba(52,211,153,0.7)'">
                  = {{ node.result }}
                </text>
                <!-- Cache hit badge -->
                <g :transform="`translate(84, 2)`">
                  <rect width="14" height="12" rx="3" fill="rgba(52,211,153,0.2)" />
                  <text x="7" y="9.5" text-anchor="middle" class="tree-repeat-badge" fill="#34d399">✓</text>
                </g>
              </g>
              <!-- Hover narrative for DAG -->
              <g
                v-if="hoveredNarrative && hoveredNodePos"
                :transform="`translate(${hoveredNodePos.x - 10}, ${hoveredNodePos.y + 36})`"
                class="tree-hover-narrative"
              >
                <rect
                  :width="Math.max(120, hoveredNarrative.length * 6.5 + 16)"
                  height="24" rx="4"
                  fill="rgba(15,23,42,0.92)"
                  stroke="rgba(52,211,153,0.4)"
                  stroke-width="1"
                />
                <text x="8" y="16" class="hover-narrative-text" fill="#e2e8f0">
                  {{ hoveredNarrative }}
                </text>
              </g>
            </svg>
          </div>
          <!-- Complexity curve: cumulative calls vs unique -->
          <div v-if="complexityCurve" class="complexity-curve">
            <div class="curve-header">
              <span class="curve-title">Growth</span>
              <span class="curve-stats">
                <span class="curve-total">{{ complexityCurve.curTotal }} calls</span>
                <span class="curve-sep">/</span>
                <span class="curve-unique">{{ complexityCurve.curUnique }} unique</span>
                <span v-if="complexityCurve.curWaste > 0" class="curve-waste">(+{{ complexityCurve.curWaste }} waste)</span>
              </span>
            </div>
            <svg :width="complexityCurve.chartW + 10" :height="complexityCurve.chartH + 10" class="curve-svg">
              <!-- Waste area: between total and unique lines -->
              <path :d="complexityCurve.wastePath" fill="rgba(251,114,153,0.1)" />
              <!-- Total calls line (red) -->
              <path :d="complexityCurve.totalPath" fill="none" stroke="#fb7299" stroke-width="1.5" />
              <!-- Unique subproblems line (green) -->
              <path :d="complexityCurve.uniquePath" fill="none" stroke="#34d399" stroke-width="1.5" />
              <!-- Current position dots -->
              <circle :cx="complexityCurve.curX" :cy="complexityCurve.curTotalY" r="3" fill="#fb7299" />
              <circle :cx="complexityCurve.curX" :cy="complexityCurve.curUniqueY" r="3" fill="#34d399" />
            </svg>
          </div>
          <!-- Explosion counter: how many repeated calls -->
          <div v-if="repeatCount > 0 && !showMemoMode" class="tree-explosion-counter">
            <span class="explosion-icon">💥</span>
            <span class="explosion-text">{{ repeatCount }} repeated calls — that's the waste</span>
          </div>
          <!-- Memo savings counter -->
          <div v-if="showMemoMode" class="memo-savings-counter">
            <span class="memo-savings-icon">🧠</span>
            <span class="memo-savings-text">
              With memo: {{ store?.subproblemGraph?.dag?.unique_count || 0 }} calls instead of {{ store?.subproblemGraph?.dag?.total_count || 0 }}
              — saves {{ (store?.subproblemGraph?.dag?.total_count || 0) - (store?.subproblemGraph?.dag?.unique_count || 0) }} recomputations
            </span>
          </div>
        </div>
      </div>

      <!-- Cognitive Narrative: the "explanation layer" — primary, human-readable -->
      <div v-if="store?.subproblemGraph?.complexity?.cognitive_narrative" class="cognitive-narrative">
        <div class="cognitive-header">
          <span class="cognitive-badge">EXPLAIN</span>
          <span class="cognitive-title">What is happening?</span>
        </div>
        <div class="cognitive-text">{{ store?.subproblemGraph.complexity.cognitive_narrative }}</div>
      </div>

      <!-- Auto Summary (compact, below narrative) -->
      <div v-if="store?.subproblemGraph?.complexity?.auto_summary" class="auto-summary">
        <div class="summary-header">Summary</div>
        <div class="summary-grid">
          <div class="summary-item">
            <span class="summary-label">Total calls</span>
            <span class="summary-value">{{ store?.subproblemGraph.complexity.auto_summary.total_calls }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">Unique subproblems</span>
            <span class="summary-value">{{ store?.subproblemGraph.complexity.auto_summary.unique_subproblems }}</span>
          </div>
          <div class="summary-item" v-if="store?.subproblemGraph.complexity.auto_summary.repeated_calls > 0">
            <span class="summary-label">Repeated calls</span>
            <span class="summary-value summary-warn">{{ store?.subproblemGraph.complexity.auto_summary.repeated_calls }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">Recursion depth</span>
            <span class="summary-value">{{ store?.subproblemGraph.complexity.auto_summary.depth }}</span>
          </div>
          <div class="summary-item" v-if="store?.subproblemGraph.complexity.auto_summary.branching_factor > 0">
            <span class="summary-label">Branching factor</span>
            <span class="summary-value">{{ store?.subproblemGraph.complexity.auto_summary.branching_factor }}</span>
          </div>
          <div class="summary-item" v-if="store?.subproblemGraph.complexity.auto_summary.operation !== 'COMBINE'">
            <span class="summary-label">Operation</span>
            <span class="summary-value summary-op">{{ store?.subproblemGraph.complexity.auto_summary.operation }}</span>
          </div>
        </div>
        <div class="summary-complexity">
          <div class="summary-complexity-row">
            <span class="summary-label">Without cache</span>
            <span class="summary-value summary-bad">{{ store?.subproblemGraph.complexity.auto_summary.complexity }}</span>
          </div>
          <div class="summary-complexity-row" v-if="store?.subproblemGraph.complexity.auto_summary.optimized_complexity">
            <span class="summary-label">With cache</span>
            <span class="summary-value summary-good">{{ store?.subproblemGraph.complexity.auto_summary.optimized_complexity.split(' --')[0] }}</span>
          </div>
          <div class="summary-complexity-row" v-if="store?.subproblemGraph.complexity.auto_summary.speedup">
            <span class="summary-label">Speedup</span>
            <span class="summary-value summary-highlight">{{ store?.subproblemGraph.complexity.auto_summary.speedup }}</span>
          </div>
        </div>
        <div class="summary-memo" v-if="store?.subproblemGraph.complexity.auto_summary.has_memoization_benefit">
          💡 Memoization would reduce calls from {{ store?.subproblemGraph.complexity.auto_summary.total_calls }} to {{ store?.subproblemGraph.complexity.auto_summary.unique_subproblems }}
        </div>
      </div>

      <!-- Analysis Mode: complexity + DAG + sandbox -->
      <div v-if="subMode === 'analysis'">

      <!-- Complexity Analysis -->
      <div class="complexity-card" v-if="store?.subproblemGraph.complexity">
        <div class="complexity-row" v-if="store?.subproblemGraph.complexity.pattern">
          <span class="complexity-label">Pattern</span>
          <span class="complexity-value complexity-highlight">{{ patternLabel(store?.subproblemGraph.complexity.pattern) }}</span>
          <span v-if="store?.subproblemGraph.complexity.execution" class="execution-tag" :class="store?.subproblemGraph.complexity.execution.toLowerCase()">
            {{ store?.subproblemGraph.complexity.execution }}
          </span>
          <span v-if="store?.subproblemGraph.complexity.shrink && store?.subproblemGraph.complexity.shrink !== 'none'" class="shrink-tag">
            {{ store?.subproblemGraph.complexity.shrink }}
          </span>
        </div>
        <div class="complexity-row">
          <span class="complexity-label">Recurrence</span>
          <span class="complexity-value">{{ store?.subproblemGraph.complexity.recurrence }}</span>
        </div>
        <div class="complexity-row">
          <span class="complexity-label">Without cache</span>
          <span class="complexity-value complexity-bad">{{ store?.subproblemGraph.complexity.without_cache }}</span>
        </div>
        <div class="complexity-row">
          <span class="complexity-label">With cache</span>
          <span class="complexity-value complexity-good">{{ store?.subproblemGraph.complexity.with_cache }}</span>
        </div>
        <div class="complexity-row">
          <span class="complexity-label">Speedup</span>
          <span class="complexity-value complexity-highlight">{{ store?.subproblemGraph.complexity.speedup }}</span>
        </div>
      </div>

      <!-- Semantic Explanation -->
      <div v-if="store?.subproblemGraph.complexity?.semantic_explanation" class="semantic-explanation">
        <div class="semantic-header">Why this complexity?</div>
        <div class="semantic-lines">
          <div
            v-for="(line, i) in store?.subproblemGraph.complexity.semantic_explanation.split('\n')"
            :key="i"
            class="semantic-line"
            :class="{ 'semantic-conclusion': line.includes('→') || line.includes('Therefore') }"
          >{{ line }}</div>
        </div>
      </div>

      <!-- DAG Visualization -->
      <div class="dag-container">
        <svg
          :width="store?.subproblemGraph.layout.width"
          :height="store?.subproblemGraph.layout.height"
          class="dag-svg"
        >
          <defs>
            <marker id="dag-arrow" markerWidth="6" markerHeight="5" refX="6" refY="2.5" orient="auto">
              <polygon points="0 0, 6 2.5, 0 5" fill="rgba(167,139,250,0.5)" />
            </marker>
          </defs>
          <!-- Edges -->
          <g v-for="(edge, i) in store?.subproblemGraph.layout.edges" :key="'de'+i">
            <line
              :x1="edge.from_pos.x + store?.subproblemGraph.layout.nodeW"
              :y1="edge.from_pos.y + store?.subproblemGraph.layout.nodeH / 2"
              :x2="edge.to_pos.x"
              :y2="edge.to_pos.y + store?.subproblemGraph.layout.nodeH / 2"
              stroke="rgba(167,139,250,0.35)"
              stroke-width="1.5"
              marker-end="url(#dag-arrow)"
            />
            <!-- Edge label: subproblem size -->
            <text
              v-if="edge.size_label"
              :x="(edge.from_pos.x + store?.subproblemGraph.layout.nodeW + edge.to_pos.x) / 2"
              :y="(edge.from_pos.y + store?.subproblemGraph.layout.nodeH / 2 + edge.to_pos.y + store?.subproblemGraph.layout.nodeH / 2) / 2 - 4"
              class="edge-label"
              fill="#a78bfa"
              text-anchor="middle"
            >{{ edge.size_label }}</text>
          </g>
          <!-- Nodes -->
          <g
            v-for="node in store?.subproblemGraph.layout.nodes"
            :key="node.id"
            :transform="`translate(${node.x}, ${node.y})`"
            class="dag-node"
            :class="{ 'dag-reused': node.is_reused }"
          >
            <rect
              :width="store?.subproblemGraph.layout.nodeW"
              :height="store?.subproblemGraph.layout.nodeH"
              rx="4"
              :fill="node.is_reused ? 'rgba(251,114,153,0.12)' : 'rgba(100,100,120,0.06)'"
              :stroke="node.is_reused ? 'var(--primary)' : 'var(--border)'"
              :stroke-width="node.is_reused ? 2 : 1"
            />
            <text x="6" y="14" class="dag-label" :fill="node.is_reused ? 'var(--primary)' : 'var(--text-dim)'">
              {{ node.label }}
            </text>
            <text v-if="node.state_size != null" :x="store?.subproblemGraph.layout.nodeW - 6" y="28" class="dag-state" fill="#a78bfa" text-anchor="end">
              n={{ node.state_size }}
            </text>
            <text v-else-if="node.result != null" x="6" y="28" class="dag-result" fill="var(--text-muted)">
              → {{ String(node.result).slice(0, 12) }}
            </text>
            <!-- Reuse count badge -->
            <g v-if="node.call_count > 1">
              <circle :cx="store?.subproblemGraph.layout.nodeW - 8" cy="10" r="8" fill="var(--primary)" />
              <text :x="store?.subproblemGraph.layout.nodeW - 8" y="14" class="dag-count" fill="#0f172a" text-anchor="middle">
                {{ node.call_count }}
              </text>
            </g>
          </g>
        </svg>
      </div>

      <!-- Recursion Level View -->
      <div v-if="store?.subproblemGraph.layout?.level_info?.length" class="level-view">
        <div class="level-header">Cost per Level</div>
        <div class="level-rows">
          <div
            v-for="lvl in store?.subproblemGraph.layout.level_info"
            :key="lvl.depth"
            class="level-row"
          >
            <span class="level-depth">L{{ lvl.depth }}</span>
            <div class="level-bar-container">
              <div
                class="level-bar"
                :class="{ 'level-bar-balanced': isCostBalanced }"
                :style="{ width: Math.max(8, ((lvl.level_cost ?? lvl.node_count) / maxCostPerLevel) * 100) + '%' }"
              />
              <span class="level-bar-label" v-if="lvl.level_cost != null">cost = {{ lvl.level_cost }}</span>
              <span class="level-bar-label" v-else>{{ lvl.node_count }} node{{ lvl.node_count > 1 ? 's' : '' }}</span>
            </div>
            <span class="level-size" v-if="lvl.avg_problem_size !== null">{{ lvl.node_count }}×{{ lvl.avg_problem_size }}</span>
          </div>
        </div>
        <!-- Visual Proof: explicit reasoning chain -->
        <div class="level-proof" v-if="store?.subproblemGraph.complexity">
          <template v-if="isCostBalanced">
            <div class="proof-line">
              <span class="proof-icon">→</span>
              <span>Each level costs ~{{ avgLevelCost }}</span>
            </div>
            <div class="proof-line">
              <span class="proof-icon">→</span>
              <span>{{ store?.subproblemGraph.layout.level_info.length }} levels total</span>
            </div>
            <div class="proof-line proof-conclusion">
              <span class="proof-icon">∴</span>
              <span>{{ avgLevelCost }} × {{ store?.subproblemGraph.layout.level_info.length }} = </span>
              <span class="proof-result">{{ store?.subproblemGraph.complexity.without_cache?.split(' --')[0] }}</span>
            </div>
          </template>
          <template v-else-if="isCostDecreasing">
            <div class="proof-line">
              <span class="proof-icon">→</span>
              <span>Work decreases each level ({{ levelCostSummary }})</span>
            </div>
            <div class="proof-line">
              <span class="proof-icon">→</span>
              <span>Dominated by top levels</span>
            </div>
            <div class="proof-line proof-conclusion">
              <span class="proof-icon">∴</span>
              <span>Total = </span>
              <span class="proof-result">{{ store?.subproblemGraph.complexity.without_cache?.split(' --')[0] }}</span>
            </div>
          </template>
          <template v-else>
            <div class="proof-line">
              <span class="proof-icon">→</span>
              <span>Cost grows each level ({{ levelCostSummary }})</span>
            </div>
            <div class="proof-line proof-conclusion">
              <span class="proof-icon">∴</span>
              <span>Total = </span>
              <span class="proof-result">{{ store?.subproblemGraph.complexity.without_cache?.split(' --')[0] }}</span>
            </div>
          </template>
        </div>
      </div>

      <!-- General Rule: teaches transferable analysis -->
      <div v-if="generalRule" class="general-rule">
        <div class="rule-header">General Rule</div>
        <div class="rule-pattern">{{ generalRule.pattern }}</div>
        <div class="rule-body">
          <div v-for="(line, i) in generalRule.lines" :key="i" class="rule-line">{{ line }}</div>
        </div>
        <div class="rule-takeaway">{{ generalRule.takeaway }}</div>
      </div>

      <!-- Pattern Sandbox: interactive experimentation -->
      <div class="sandbox-section">
        <div class="sandbox-header">
          <span class="sandbox-title">Pattern Sandbox</span>
          <span class="sandbox-steps">
            <span :class="['step-tag', { active: sandboxStep >= 1 }]">Explore</span>
            <span class="step-arrow">→</span>
            <span :class="['step-tag', { active: sandboxStep >= 2 }]">Compare</span>
            <span class="step-arrow">→</span>
            <span :class="['step-tag', { active: sandboxStep >= 3 }]">Explain</span>
          </span>
        </div>
        <div class="sandbox-controls">
          <div class="sandbox-patterns">
            <button
              v-for="p in sandboxPatterns"
              :key="p.key"
              :class="['sandbox-btn', { active: sandboxPattern === p.key }]"
              @click="sandboxPattern = p.key"
            >{{ p.label }}</button>
          </div>
          <div class="sandbox-sliders">
            <div class="slider-group">
              <label>Branching: {{ sandboxBranching }}</label>
              <input type="range" v-model.number="sandboxBranching" min="1" max="4" step="1" />
            </div>
            <div class="slider-group">
              <label>Depth: {{ sandboxDepth }}</label>
              <input type="range" v-model.number="sandboxDepth" min="1" max="6" step="1" />
            </div>
          </div>
        </div>
        <div class="sandbox-result">
          <div class="sandbox-levels">
            <div
              v-for="lvl in sandboxLevels"
              :key="lvl.depth"
              class="sandbox-level-row"
            >
              <span class="sandbox-level-label">L{{ lvl.depth }}</span>
              <div class="sandbox-bar-wrap">
                <div class="sandbox-bar" :style="{ width: lvl.barWidth + '%' }" />
                <span class="sandbox-bar-text">{{ lvl.cost }}</span>
              </div>
            </div>
          </div>
          <div class="sandbox-complexity">
            <div class="sandbox-calc">{{ sandboxCalculation }}</div>
            <div class="sandbox-answer">{{ sandboxComplexity }}</div>
          </div>
        </div>
        <!-- Guided Discovery -->
        <div class="sandbox-hint" v-if="sandboxHint">
          <span class="hint-icon">?</span>
          <span class="hint-text">{{ sandboxHint }}</span>
        </div>
        <!-- Explain prompt: force articulation -->
        <div class="sandbox-explain" v-if="sandboxExplainPrompt">
          <span class="explain-icon">→</span>
          <span class="explain-text">{{ sandboxExplainPrompt }}</span>
        </div>
        <!-- Input + Feedback -->
        <div class="sandbox-input-area" v-if="sandboxExplainPrompt">
          <div class="input-row" v-if="!sandboxFeedback">
            <input
              v-model="sandboxUserAnswer"
              class="sandbox-input"
              placeholder="Type your explanation..."
              @keydown.enter="submitSandboxAnswer"
            />
            <button class="sandbox-submit" @click="submitSandboxAnswer">→</button>
          </div>
          <div class="sandbox-feedback" v-if="sandboxFeedback" :class="sandboxFeedback.type">
            <span class="feedback-icon">{{ sandboxFeedback.type === 'correct' ? '✓' : sandboxFeedback.type === 'partial' ? '~' : '✗' }}</span>
            <span class="feedback-text">{{ sandboxFeedback.message }}</span>
            <button class="feedback-reset" @click="sandboxFeedback = null; sandboxUserAnswer = ''">try again</button>
          </div>
          <button class="show-answer-btn" v-if="!sandboxFeedback" @click="showSandboxAnswer = !showSandboxAnswer">
            {{ showSandboxAnswer ? 'hide' : 'show answer' }}
          </button>
          <div class="sample-answer" v-if="showSandboxAnswer">
            {{ sandboxSampleAnswer }}
          </div>
        </div>
      </div>

      <!-- Shared subproblems detail -->
      <div v-if="store?.subproblemGraph.complexity?.shared_subproblems?.length" class="shared-subs">
        <div class="shared-title">Most recomputed subproblems:</div>
        <div
          v-for="sub in store?.subproblemGraph.complexity.shared_subproblems.slice(0, 5)"
          :key="sub.id"
          class="shared-item"
        >
          <span class="shared-id">{{ sub.id }}</span>
          <span class="shared-count">×{{ sub.called }}</span>
        </div>
      </div>

      <!-- Performance narrative -->
      <div v-if="store?.subproblemGraph.narrative" class="perf-narrative">
        {{ store?.subproblemGraph.narrative }}
      </div>

      </div><!-- end analysis mode -->
    </div>
  </div>
</template>

<style scoped>
.timeline-panel { display: flex; flex-direction: column; gap: 12px; }

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--text-muted);
  font-size: 14px;
}

.controls {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  flex-wrap: wrap;
}

.btn-sm { padding: 4px 12px; font-size: 12px; }
.slider { flex: 1; accent-color: var(--primary); min-width: 80px; }
.step-display { font-size: 13px; color: var(--highlight); font-weight: 600; min-width: 60px; text-align: center; }
.speed-input {
  width: 50px; background: var(--bg-dark); color: var(--text);
  border: 1px solid var(--border); border-radius: 4px;
  padding: 2px 6px; font-size: 11px; text-align: center;
}
.speed-label { font-size: 11px; color: var(--text-muted); }

.explain-btn {
  background: linear-gradient(135deg, rgba(34,211,238,0.15), rgba(167,139,250,0.15));
  border-color: rgba(34,211,238,0.3); color: var(--highlight);
  font-weight: 700; letter-spacing: 0.5px;
}
.explain-btn:hover {
  border-color: var(--highlight);
  background: linear-gradient(135deg, rgba(34,211,238,0.25), rgba(167,139,250,0.25));
}
.explain-active {
  background: linear-gradient(135deg, var(--highlight), #a78bfa) !important;
  color: #0f172a !important; border-color: transparent !important;
  animation: pulse-glow 1.5s infinite;
}
@keyframes pulse-glow {
  0%, 100% { box-shadow: 0 0 8px rgba(34,211,238,0.3); }
  50% { box-shadow: 0 0 16px rgba(34,211,238,0.6); }
}

/* AI Step Explanation */
.step-explain {
  background: linear-gradient(135deg, rgba(34,211,238,0.06), rgba(167,139,250,0.06));
  border: 1px solid rgba(34,211,238,0.2);
  border-left: 3px solid var(--highlight);
  transition: all 0.3s ease;
}

.step-explain.is-turning-point {
  border-color: var(--primary);
  border-left: 3px solid var(--primary);
  background: linear-gradient(135deg, rgba(251,114,153,0.08), rgba(167,139,250,0.08));
  animation: turning-pulse 0.6s ease-out;
}

.step-explain.is-high {
  transform: scale(1.01);
}

.step-explain.is-loading {
  opacity: 0.7;
}

.explain-importance-text {
  font-size: 12px;
  color: var(--highlight);
  line-height: 1.5;
  padding: 6px 10px;
  background: color-mix(in srgb, var(--highlight) 8%, transparent);
  border-radius: 6px;
  border-left: 3px solid var(--highlight);
  margin-bottom: 6px;
}

.explain-causal {
  font-size: 12px;
  color: var(--highlight);
  padding: 4px 10px;
  background: rgba(167,139,250,0.08);
  border-radius: 6px;
  border-left: 3px solid rgba(167,139,250,0.4);
  margin-bottom: 6px;
}
.causal-icon {
  font-weight: 700;
  margin-right: 4px;
}

.explain-reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}

.reason-tag {
  font-size: 10px;
  background: rgba(255,255,255,0.05);
  border: 1px solid var(--border);
  color: var(--text-muted);
  padding: 2px 8px;
  border-radius: 10px;
}

.explain-score-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.score-track {
  flex: 1;
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  overflow: hidden;
}

.score-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s ease;
}

.score-num {
  font-size: 11px;
  color: var(--text-muted);
  min-width: 32px;
  text-align: right;
  font-family: monospace;
}

@keyframes turning-pulse {
  0% { transform: scale(0.97); opacity: 0.7; }
  50% { transform: scale(1.02); }
  100% { transform: scale(1); opacity: 1; }
}

.explain-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
}
.explain-badge {
  background: linear-gradient(135deg, #22d3ee, #a78bfa);
  color: #0f172a; font-size: 9px; font-weight: 800;
  padding: 2px 6px; border-radius: 3px; letter-spacing: 1px;
}
.explain-step-label { font-size: 12px; font-weight: 600; color: var(--highlight); }
.explain-importance {
  font-size: 10px; margin-left: auto;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.turning-badge {
  font-size: 9px; background: rgba(251,114,153,0.2); color: var(--primary);
  padding: 2px 8px; border-radius: 4px; font-weight: 700; letter-spacing: 0.5px;
  animation: turning-badge-glow 1s infinite;
}
@keyframes turning-badge-glow {
  0%, 100% { box-shadow: 0 0 4px rgba(251,114,153,0.2); }
  50% { box-shadow: 0 0 10px rgba(251,114,153,0.5); }
}

.explain-text { font-size: 14px; color: var(--text); line-height: 1.6; }
.explain-diff {
  font-size: 11px; color: var(--text-muted); margin-top: 6px;
  font-style: italic; padding-top: 6px; border-top: 1px solid var(--border);
}

/* Current step */
.current-step { border-color: var(--primary); transition: all 0.3s ease; }
.current-step.step-glow {
  border-color: var(--primary);
  box-shadow: 0 0 16px rgba(251,114,153,0.25);
  animation: step-glow-pulse 1.5s infinite;
}
@keyframes step-glow-pulse {
  0%, 100% { box-shadow: 0 0 12px rgba(251,114,153,0.2); }
  50% { box-shadow: 0 0 24px rgba(251,114,153,0.4); }
}

.step-header { display: flex; justify-content: space-between; margin-bottom: 6px; }
.step-num { font-weight: 700; color: var(--primary); }
.step-loc { font-size: 12px; color: var(--text-muted); }
.step-code { font-family: monospace; font-size: 14px; color: var(--highlight); padding: 6px 0; }
.step-changes { font-size: 11px; color: var(--warning); margin-top: 4px; }
.step-new { font-size: 11px; color: var(--success); margin-top: 2px; }

.section-title { font-size: 13px; font-weight: 600; color: var(--text-dim); margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
.var-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 6px; }

.var-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 6px; padding: 8px 10px; position: relative; transition: all 0.2s;
}
.var-card.changed { border-color: var(--warning); background: rgba(251,191,36,0.05); }
.var-card.is-new { border-color: var(--success); background: rgba(52,211,153,0.05); }
.var-name { font-size: 12px; font-weight: 600; color: var(--highlight); }
.var-value { font-size: 11px; font-family: monospace; color: var(--text); margin-top: 2px; word-break: break-all; max-height: 40px; overflow: hidden; }
.var-type { font-size: 10px; color: var(--text-muted); margin-top: 2px; }
.var-badge { position: absolute; top: -6px; right: 4px; font-size: 8px; padding: 1px 5px; border-radius: 6px; font-weight: 700; }
.changed-badge { background: var(--warning); color: #000; }
.new-badge { background: var(--success); color: #000; }

.heatmap-bar {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
}

.heatmap-label {
  font-size: 10px;
  color: var(--text-muted);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.heatmap-row {
  display: flex;
  gap: 1px;
  height: 16px;
  align-items: flex-end;
}

.heatmap-cell {
  flex: 1;
  min-width: 2px;
  border-radius: 1px 1px 0 0;
  cursor: pointer;
  transition: all 0.15s;
}

.heatmap-cell:hover {
  transform: scaleY(1.5);
  filter: brightness(1.3);
}
.heatmap-cell.cell-current {
  transform: scaleY(2);
  box-shadow: 0 0 6px var(--primary);
}

.step-list { flex: 1; min-height: 0; }
.steps-scroll { max-height: 300px; overflow-y: auto; }

.toggle-all-btn {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.toggle-all-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.skip-indicator {
  text-align: center;
  font-size: 10px;
  color: var(--text-muted);
  padding: 2px 0;
  opacity: 0.6;
  border-bottom: 1px dashed var(--border);
  margin: 2px 0;
}

.step-item {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 8px; cursor: pointer; border-radius: 4px;
  font-size: 11px; transition: all 0.15s;
}
.step-item:hover { background: var(--bg-card-hover); }
.step-item.active { background: rgba(251,114,153,0.15); border-left: 2px solid var(--primary); }
.step-item.step-important {
  border-left: 2px solid transparent;
  background: rgba(251,114,153,0.04);
}
.step-item.step-important:not(.active) {
  border-left: 2px solid rgba(251,114,153,0.3);
}
.step-item.has-ai .step-idx { min-width: 24px; }

/* Visual weight: high importance steps are larger and brighter */
.step-item.step-weight-high {
  font-size: 12px;
  font-weight: 600;
  background: rgba(251,114,153,0.06);
  padding: 6px 8px;
}
.step-item.step-weight-high .step-code-text {
  color: var(--text);
}
.step-item.step-weight-medium .step-code-text {
  color: var(--text-dim);
  opacity: 0.9;
}

.step-idx { color: var(--text-muted); min-width: 30px; text-align: right; }
.step-code-text { font-family: monospace; color: var(--text-dim); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step-changes-dot { font-size: 8px; }
.step-ai-dot { font-size: 10px; min-width: 14px; text-align: center; }
.step-score-bar { width: 3px; height: 14px; border-radius: 1px; flex-shrink: 0; }

/* Reason icons (inline in step list) */
.step-reason-icons {
  display: inline-flex; gap: 2px; flex-shrink: 0;
}
.reason-icon {
  font-size: 10px; line-height: 1;
  opacity: 0.7;
}

/* Reason icons (in explanation card) */
.explain-reason-icons {
  display: inline-flex; gap: 4px; margin-left: 8px;
}
.reason-icon-lg {
  font-size: 16px; line-height: 1;
  cursor: default;
}

/* Causal source: highlighted step that affects others */
.step-item.is-causal-source {
  background: rgba(34,211,238,0.12);
  border-left: 2px solid var(--highlight);
}
.step-item.is-causal-source .step-code-text {
  color: var(--text);
}

/* Downstream steps: affected by causal source */
.step-item.is-downstream {
  background: rgba(167,139,250,0.10);
  border-left: 2px solid rgba(167,139,250,0.4);
  position: relative;
}
.step-item.is-downstream::before {
  content: '←';
  position: absolute;
  left: -14px;
  color: rgba(167,139,250,0.5);
  font-size: 10px;
}

/* Causal affects label */
.causal-affects-label {
  font-size: 10px;
  color: var(--highlight);
  background: rgba(34,211,238,0.08);
  padding: 1px 6px;
  border-radius: 3px;
  white-space: nowrap;
  flex-shrink: 0;
}

/* WHY Narrative */
.narrative {
  background: linear-gradient(135deg, rgba(251,114,153,0.06), rgba(167,139,250,0.06));
  border: 1px solid rgba(251,114,153,0.2);
  border-left: 3px solid var(--primary);
  padding: 12px 14px;
}
.narrative-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
}
.narrative-badge {
  background: linear-gradient(135deg, #fb7299, #a78bfa);
  color: #0f172a; font-size: 9px; font-weight: 800;
  padding: 2px 8px; border-radius: 3px; letter-spacing: 1px;
}
.narrative-title {
  font-size: 13px; font-weight: 700; color: var(--primary);
}
.pattern-badge {
  font-size: 10px; font-weight: 700; color: var(--highlight);
  background: rgba(34,211,238,0.12); border: 1px solid rgba(34,211,238,0.25);
  padding: 1px 8px; border-radius: 10px; letter-spacing: 0.3px;
}
.narrative-path {
  font-size: 10px; color: var(--text-muted); font-family: monospace;
  margin-left: auto;
}
.narrative-text {
  font-size: 13px; color: var(--text); line-height: 1.8;
  letter-spacing: 0.01em;
}
.narrative-complexity {
  margin-top: 10px; padding: 8px 10px;
  background: rgba(251,191,36,0.06);
  border: 1px solid rgba(251,191,36,0.15);
  border-left: 3px solid rgba(251,191,36,0.4);
  border-radius: 6px;
  font-size: 12px; color: var(--text-dim); line-height: 1.6;
}
.complexity-icon { margin-right: 4px; }
.narrative-evidence {
  display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px;
}
.evidence-chip {
  display: flex; align-items: center; gap: 6px;
  padding: 3px 10px; border-radius: 12px;
  background: rgba(167,139,250,0.08);
  border: 1px solid rgba(167,139,250,0.2);
  font-size: 11px; cursor: default;
  transition: all 0.2s;
}
.evidence-chip:hover {
  background: rgba(167,139,250,0.15);
  border-color: rgba(167,139,250,0.4);
}
.evidence-name { color: var(--text); font-weight: 600; }
.evidence-conf {
  color: var(--highlight);
  font-family: monospace; font-size: 10px;
}

/* Causal Graph */
.causal-graph {
  padding: 10px;
  overflow-x: auto;
}
.graph-legend {
  display: flex; gap: 12px; font-size: 10px; color: var(--text-muted);
}
.legend-item { display: flex; align-items: center; gap: 4px; }
.legend-line { display: inline-block; width: 16px; height: 2px; }
.legend-data { background: rgba(167,139,250,0.6); }
.legend-control { background: rgba(34,211,238,0.5); border-top: 2px dashed rgba(34,211,238,0.5); height: 0; }
.graph-svg {
  display: block;
  margin-top: 8px;
}
.graph-node { cursor: pointer; transition: opacity 0.2s; }
.graph-node:hover rect {
  filter: brightness(1.3);
}
.graph-node.node-source rect {
  stroke-width: 2;
}
.graph-node.node-high rect {
  stroke: var(--primary);
}
.graph-node.node-hovered rect {
  filter: brightness(1.4);
}
.graph-node.node-current rect {
  stroke: var(--primary);
  stroke-width: 2.5;
}
.node-meaning { font-size: 10px; font-weight: 600; }
.node-icons { font-size: 9px; }
.node-code { font-size: 8px; font-family: monospace; }

/* Critical path node */
.graph-node.node-critical rect {
  stroke: var(--primary);
  stroke-width: 2.5;
}

/* Edge click target */
.edge-click-target { cursor: pointer; }
.edge-click-target:hover + line { filter: brightness(1.5); }

/* Execution path dot animation */
.exec-dot {
  animation: exec-pulse 1.2s ease-in-out infinite;
}
@keyframes exec-pulse {
  0%, 100% { opacity: 0.6; r: 4; }
  50% { opacity: 1; r: 6; }
}

/* Critical path legend */
.critical-path-legend {
  display: flex; align-items: center; gap: 6px;
  font-size: 10px; color: var(--primary); margin-top: 8px;
  padding: 4px 8px; background: rgba(251,114,153,0.06);
  border-radius: 4px;
}
.path-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--primary); flex-shrink: 0;
}

/* Edge explanation panel */
.edge-explain {
  margin-top: 8px; padding: 8px 10px;
  background: rgba(167,139,250,0.06);
  border: 1px solid rgba(167,139,250,0.2);
  border-radius: 6px;
  font-size: 11px;
}
.edge-explain-header {
  display: flex; align-items: center; gap: 6px;
  font-weight: 600; color: var(--highlight); margin-bottom: 4px;
}
.edge-explain-icon { font-size: 14px; }
.edge-close {
  margin-left: auto; background: none; border: none;
  color: var(--text-muted); cursor: pointer; font-size: 14px; padding: 0 4px;
}
.edge-explain-text { color: var(--text); line-height: 1.5; }
.edge-vars {
  margin-top: 4px; font-size: 10px; color: var(--text-muted);
  font-family: monospace;
}

/* Subproblem Graph / Computation DAG */
.subproblem-section {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  overflow: hidden;
}
.subproblem-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 10px;
}
.subproblem-badge {
  background: linear-gradient(135deg, #fb7299, #a78bfa);
  color: #0f172a; font-size: 9px; font-weight: 800;
  padding: 2px 8px; border-radius: 3px; letter-spacing: 1px;
}
.subproblem-title {
  font-size: 13px; font-weight: 700; color: var(--primary);
}
.subproblem-stats {
  font-size: 11px; color: var(--text-muted); font-family: monospace; margin-left: auto;
}

.complexity-card {
  background: rgba(251,191,36,0.04);
  border: 1px solid rgba(251,191,36,0.15);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.complexity-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 3px 0;
}
.complexity-label {
  font-size: 11px; color: var(--text-muted); font-weight: 600;
}
.complexity-value {
  font-size: 12px; color: var(--text); font-family: monospace;
}
.complexity-bad { color: #f87171; }
.complexity-good { color: #34d399; }
.complexity-highlight {
  color: var(--highlight); font-weight: 700;
}

.execution-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  margin-left: 6px;
}
.execution-tag.and {
  background: rgba(251,114,153,0.15);
  color: var(--primary);
}
.execution-tag.or {
  background: rgba(34,211,238,0.15);
  color: var(--accent);
}

.shrink-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  background: rgba(167,139,250,0.12);
  color: #a78bfa;
  margin-left: 4px;
}

.semantic-explanation {
  background: rgba(167,139,250,0.04);
  border: 1px solid rgba(167,139,250,0.12);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.semantic-header {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}
.semantic-lines {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.semantic-line {
  font-size: 12px;
  color: var(--text);
  line-height: 1.5;
  padding-left: 8px;
  border-left: 2px solid transparent;
}
.semantic-line.semantic-conclusion {
  color: var(--highlight);
  font-weight: 600;
  border-left-color: var(--highlight);
}

.edge-label {
  font-size: 9px;
  font-weight: 600;
  pointer-events: none;
}

.dag-container {
  overflow-x: auto; overflow-y: hidden;
  padding: 4px 0;
  margin-bottom: 10px;
}
.dag-svg { display: block; }
.dag-node { cursor: default; }
.dag-label { font-size: 9px; font-family: monospace; }
.dag-result { font-size: 8px; font-family: monospace; }
.dag-count { font-size: 8px; font-weight: 800; }
.dag-state { font-size: 9px; font-weight: 700; }

/* Recursion Level View */
.level-view {
  background: rgba(34,211,238,0.03);
  border: 1px solid rgba(34,211,238,0.12);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.level-header {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}
.level-rows {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.level-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.level-depth {
  font-size: 10px;
  font-weight: 700;
  color: var(--accent);
  width: 24px;
  text-align: right;
  flex-shrink: 0;
}
.level-bar-container {
  flex: 1;
  height: 16px;
  background: rgba(34,211,238,0.06);
  border-radius: 3px;
  position: relative;
  overflow: hidden;
}
.level-bar {
  height: 100%;
  background: linear-gradient(90deg, rgba(34,211,238,0.25), rgba(34,211,238,0.45));
  border-radius: 3px;
  transition: width 0.3s ease;
}
.level-bar-balanced {
  background: linear-gradient(90deg, rgba(34,211,238,0.35), rgba(34,211,238,0.6)) !important;
}
.level-bar-label {
  position: absolute;
  left: 6px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 9px;
  font-weight: 600;
  color: var(--text);
}
.level-size {
  font-size: 10px;
  color: var(--text-dim);
  width: 50px;
  text-align: right;
  flex-shrink: 0;
}
.level-proof {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(34,211,238,0.1);
  font-size: 12px;
}
.proof-line {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text);
  line-height: 1.6;
}
.proof-icon {
  color: var(--accent);
  font-weight: 700;
  width: 14px;
  flex-shrink: 0;
}
.proof-conclusion {
  margin-top: 2px;
  font-weight: 700;
}
.proof-result {
  color: var(--highlight);
  font-weight: 800;
  font-size: 13px;
}

/* General Rule: transferable analysis pattern */
.general-rule {
  background: rgba(251,114,153,0.04);
  border: 1px solid rgba(251,114,153,0.15);
  border-left: 3px solid var(--primary);
  border-radius: 0 6px 6px 0;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.rule-header {
  font-size: 10px;
  font-weight: 700;
  color: var(--primary);
  text-transform: uppercase;
  letter-spacing: 0.8px;
  margin-bottom: 4px;
}
.rule-pattern {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 6px;
}
.rule-body {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.rule-line {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.5;
  padding-left: 8px;
}
.rule-takeaway {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(251,114,153,0.1);
  line-height: 1.5;
  font-style: italic;
}

/* Pattern Sandbox */
.sandbox-section {
  background: rgba(251,114,153,0.03);
  border: 1px solid rgba(251,114,153,0.12);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.sandbox-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.sandbox-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sandbox-steps {
  display: flex;
  align-items: center;
  gap: 4px;
}
.step-tag {
  font-size: 9px;
  font-weight: 600;
  color: var(--text-muted);
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(100,100,120,0.06);
  transition: all 0.2s;
}
.step-tag.active {
  color: var(--primary);
  background: rgba(251,114,153,0.1);
}
.step-arrow {
  font-size: 8px;
  color: var(--text-muted);
}
.sandbox-controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}
.sandbox-patterns {
  display: flex;
  gap: 4px;
}
.sandbox-btn {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: none;
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.sandbox-btn:hover {
  border-color: var(--primary);
  color: var(--text);
}
.sandbox-btn.active {
  background: rgba(251,114,153,0.12);
  border-color: var(--primary);
  color: var(--primary);
}
.sandbox-sliders {
  display: flex;
  gap: 16px;
}
.slider-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}
.slider-group label {
  font-size: 10px;
  color: var(--text-dim);
  font-weight: 600;
}
.slider-group input[type="range"] {
  width: 100%;
  height: 4px;
  -webkit-appearance: none;
  background: var(--border);
  border-radius: 2px;
  outline: none;
}
.slider-group input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--primary);
  cursor: pointer;
}
.sandbox-result {
  display: flex;
  gap: 12px;
}
.sandbox-levels {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.sandbox-level-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sandbox-level-label {
  font-size: 9px;
  font-weight: 700;
  color: var(--accent);
  width: 16px;
  text-align: right;
  flex-shrink: 0;
}
.sandbox-bar-wrap {
  flex: 1;
  height: 14px;
  background: rgba(251,114,153,0.06);
  border-radius: 2px;
  position: relative;
  overflow: hidden;
}
.sandbox-bar {
  height: 100%;
  background: linear-gradient(90deg, rgba(251,114,153,0.3), rgba(251,114,153,0.5));
  border-radius: 2px;
  transition: width 0.2s ease;
}
.sandbox-bar-text {
  position: absolute;
  left: 4px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 8px;
  font-weight: 700;
  color: var(--text);
}
.sandbox-complexity {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 80px;
  gap: 2px;
}
.sandbox-calc {
  font-size: 9px;
  color: var(--text-dim);
  text-align: center;
}
.sandbox-answer {
  font-size: 14px;
  font-weight: 800;
  color: var(--highlight);
}
.sandbox-hint {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 8px;
  background: rgba(251,114,153,0.06);
  border-radius: 4px;
  border-left: 2px solid var(--primary);
}
.hint-icon {
  font-size: 11px;
  font-weight: 800;
  color: var(--primary);
  flex-shrink: 0;
}
.hint-text {
  font-size: 11px;
  color: var(--text);
  line-height: 1.5;
  font-style: italic;
}
.sandbox-explain {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding: 6px 8px;
  background: rgba(34,211,238,0.06);
  border-radius: 4px;
  border-left: 2px solid var(--accent);
}
.explain-icon {
  font-size: 11px;
  color: var(--accent);
  flex-shrink: 0;
  font-weight: 800;
}
.explain-text {
  font-size: 11px;
  color: var(--text);
  line-height: 1.5;
  font-weight: 600;
}

.sandbox-input-area {
  margin-top: 6px;
}
.input-row {
  display: flex;
  gap: 4px;
}
.sandbox-input {
  flex: 1;
  padding: 5px 8px;
  background: rgba(100,100,120,0.06);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-size: 11px;
  outline: none;
  transition: border-color 0.2s;
}
.sandbox-input:focus {
  border-color: var(--primary);
}
.sandbox-input::placeholder {
  color: var(--text-muted);
}
.sandbox-submit {
  padding: 4px 10px;
  background: rgba(251,114,153,0.12);
  border: 1px solid var(--primary);
  border-radius: 4px;
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
}
.sandbox-submit:hover {
  background: rgba(251,114,153,0.2);
}
.sandbox-feedback {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 11px;
  line-height: 1.4;
}
.sandbox-feedback.correct {
  background: rgba(34,197,94,0.08);
  border-left: 2px solid #22c55e;
}
.sandbox-feedback.partial {
  background: rgba(234,179,8,0.08);
  border-left: 2px solid #eab308;
}
.sandbox-feedback.hint {
  background: rgba(100,100,120,0.06);
  border-left: 2px solid var(--text-muted);
}
.feedback-icon {
  font-size: 12px;
  font-weight: 800;
  flex-shrink: 0;
}
.sandbox-feedback.correct .feedback-icon { color: #22c55e; }
.sandbox-feedback.partial .feedback-icon { color: #eab308; }
.sandbox-feedback.hint .feedback-icon { color: var(--text-muted); }
.feedback-text {
  flex: 1;
  color: var(--text);
}
.feedback-reset {
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 10px;
  cursor: pointer;
  text-decoration: underline;
  flex-shrink: 0;
}
.show-answer-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 10px;
  cursor: pointer;
  margin-top: 4px;
  text-decoration: underline;
}
.sample-answer {
  margin-top: 4px;
  padding: 6px 8px;
  background: rgba(34,211,238,0.06);
  border-radius: 4px;
  font-size: 11px;
  color: var(--text);
  line-height: 1.5;
  border-left: 2px solid var(--accent);
}

.shared-subs {
  background: rgba(251,114,153,0.04);
  border: 1px solid rgba(251,114,153,0.12);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 10px;
}
.shared-title {
  font-size: 10px; color: var(--text-muted); margin-bottom: 4px;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.shared-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 2px 0; font-size: 11px;
}
.shared-id { color: var(--text); font-family: monospace; }
.shared-count {
  color: var(--primary); font-weight: 700; font-family: monospace;
  background: rgba(251,114,153,0.1); padding: 1px 6px; border-radius: 4px;
}

.perf-narrative {
  font-size: 12px; color: var(--text-dim); line-height: 1.7;
  padding: 8px 10px;
  background: rgba(167,139,250,0.04);
  border-left: 3px solid rgba(167,139,250,0.3);
  border-radius: 0 6px 6px 0;
}

/* Submode tabs: Execution / Analysis */
.submode-tabs {
  display: flex;
  gap: 0;
  margin-left: auto;
}
.submode-btn {
  padding: 3px 10px;
  background: none;
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
  letter-spacing: 0.3px;
}
.submode-btn:first-child {
  border-radius: 4px 0 0 4px;
  border-right: none;
}
.submode-btn:last-child {
  border-radius: 0 4px 4px 0;
}
.submode-btn:hover {
  color: var(--text);
  background: rgba(100,100,120,0.06);
}
.submode-btn.active {
  background: rgba(34,211,238,0.12);
  border-color: var(--accent);
  color: var(--accent);
}

/* Execution Mode */
.execution-mode {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px 0;
}
.exec-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 6px;
}
.exec-btn {
  padding: 4px 10px;
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-dim);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.exec-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.exec-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
.exec-play {
  background: rgba(34,211,238,0.08);
  border-color: rgba(34,211,238,0.3);
  color: var(--accent);
  font-weight: 700;
}
.exec-step-label {
  font-size: 11px;
  color: var(--text-muted);
  font-family: monospace;
  flex: 1;
  text-align: center;
}

/* Call Stack */
.exec-stack {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
}
.stack-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}
.stack-frames {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.stack-frame {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: rgba(100,100,120,0.04);
  border-radius: 4px;
  border-left: 2px solid var(--border);
  font-size: 11px;
  transition: all 0.2s;
}
.stack-frame.stack-active {
  background: rgba(34,211,238,0.08);
  border-left-color: var(--accent);
}
.frame-name {
  font-weight: 700;
  color: var(--highlight);
  font-family: monospace;
}
.frame-args {
  color: var(--text-dim);
  font-family: monospace;
  font-size: 10px;
}
.frame-return {
  margin-left: auto;
  color: var(--accent);
  font-family: monospace;
  font-size: 10px;
}

/* Current call highlight */
.exec-current {
  background: linear-gradient(135deg, rgba(34,211,238,0.06), rgba(167,139,250,0.06));
  border: 1px solid rgba(34,211,238,0.2);
  border-left: 3px solid var(--accent);
  border-radius: 0 6px 6px 0;
  padding: 10px 12px;
}
.step-narrative {
  font-size: 14px;
  color: var(--text);
  line-height: 1.6;
  margin-bottom: 6px;
}
.current-raw {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-family: monospace;
  color: var(--text-muted);
}
.current-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}
.current-call {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  font-family: monospace;
}
.current-return {
  font-size: 11px;
  color: var(--highlight);
  font-family: monospace;
  margin-top: 2px;
}

/* DAG in execution mode */
.exec-dag {
  overflow-x: auto;
  padding: 4px 0;
}

/* Call Tree Visualization */
.call-tree-container {
  margin-top: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  background: rgba(15,23,42,0.4);
}
.call-tree-header {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}
.call-tree-badge {
  background: linear-gradient(135deg, #fb7299, #a78bfa);
  color: #0f172a; font-size: 9px; font-weight: 800;
  padding: 2px 8px; border-radius: 3px; letter-spacing: 1px;
}
.call-tree-title {
  font-size: 12px; font-weight: 700; color: var(--text);
}
.call-tree-legend {
  margin-left: auto; display: flex; gap: 12px;
}
.legend-item {
  display: flex; align-items: center; gap: 4px;
  font-size: 10px; color: var(--text-muted);
}
.legend-dot {
  width: 8px; height: 8px; border-radius: 50%;
}
.legend-new {
  background: var(--border);
  border: 1px solid var(--text-dim);
}
.legend-repeat {
  background: rgba(251,114,153,0.4);
  border: 1px solid #fb7299;
}
.legend-active {
  background: rgba(34,211,238,0.3);
  border: 1px solid var(--accent);
}
.call-tree-scroll {
  overflow-x: auto; overflow-y: auto;
  max-height: 400px;
  padding: 12px;
}
.call-tree-svg {
  display: block;
}
.tree-node {
  cursor: pointer;
}
/* Upgrade 1: Tree "grows" — nodes appear with fade-in */
.tree-node-enter {
  animation: tree-grow 0.4s cubic-bezier(0.22, 1, 0.36, 1) both;
}
@keyframes tree-grow {
  0% { opacity: 0; }
  100% { opacity: 1; }
}
/* Upgrade 2: Repeated node flash — explosive burst when first repeated */
.tree-node-flash rect {
  animation: repeat-flash 0.7s ease-out;
}
@keyframes repeat-flash {
  0% { stroke-width: 2; }
  20% { stroke-width: 5; stroke: #ff2222; fill: rgba(255,34,34,0.3); }
  50% { stroke-width: 4; stroke: #ff4444; fill: rgba(255,68,68,0.2); }
  80% { stroke-width: 3; stroke: #fb7299; fill: rgba(251,114,153,0.15); }
  100% { stroke-width: 2; stroke: #fb7299; fill: rgba(251,114,153,0.1); }
}
/* Radial burst ring */
.burst-ring {
  animation: burst-expand 0.7s ease-out forwards;
  pointer-events: none;
}
@keyframes burst-expand {
  0% { r: 10; opacity: 0.8; stroke-width: 3; }
  40% { r: 40; opacity: 0.5; stroke-width: 2; }
  100% { r: 80; opacity: 0; stroke-width: 0.5; }
}
.tree-node:hover rect {
  stroke-width: 2.5;
}
.tree-label {
  font-size: 11px; font-weight: 600; font-family: monospace;
}
.tree-result {
  font-size: 9px; font-family: monospace;
}
.tree-repeat-badge {
  font-size: 8px; font-weight: 800;
}
/* Hover narrative — appears directly on the node */
.tree-hover-narrative {
  pointer-events: none;
}
.hover-narrative-text {
  font-size: 10px; font-weight: 500; font-family: monospace;
}
/* Explosion counter */
.tree-explosion-counter {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px;
  border-top: 1px solid var(--border);
  background: rgba(251,114,153,0.06);
  animation: counter-pulse 0.4s ease-out;
}
@keyframes counter-pulse {
  0% { background: rgba(251,114,153,0.15); }
  100% { background: rgba(251,114,153,0.06); }
}
.explosion-icon {
  font-size: 14px;
}
.explosion-text {
  font-size: 11px; color: #fb7299; font-weight: 600;
}
/* Legacy tooltip (keep for compatibility) */
.tree-tooltip {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid var(--border);
  background: rgba(251,114,153,0.05);
  cursor: pointer;
}
.tree-tooltip-icon {
  font-size: 14px; flex-shrink: 0;
}
.tree-tooltip-text {
  font-size: 12px; color: var(--text); line-height: 1.4;
  font-weight: 500;
}

/* Upgrade 4: Active edge glow */
.active-edge-glow {
  filter: url(#active-glow);
  animation: edge-pulse 0.8s ease-in-out infinite alternate;
}
@keyframes edge-pulse {
  0% { opacity: 0.6; stroke-width: 2; }
  100% { opacity: 1; stroke-width: 3.5; }
}
.flow-dot {
  animation: flow-fade 0.6s ease-out forwards;
}
@keyframes flow-fade {
  0% { opacity: 1; }
  100% { opacity: 0; }
}

/* Upgrade 5: Repeat pointer */
.repeat-pointer-line {
  animation: pointer-appear 0.4s ease-out;
}
@keyframes pointer-appear {
  0% { opacity: 0; stroke-dashoffset: 20; }
  100% { opacity: 0.7; stroke-dashoffset: 0; }
}
.repeat-pointer-label {
  font-size: 9px; font-weight: 600; font-family: monospace;
  animation: label-fade 0.5s ease-out;
}
@keyframes label-fade {
  0% { opacity: 0; }
  100% { opacity: 0.7; }
}

/* Memo toggle */
.memo-toggle {
  margin-left: auto;
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: rgba(100,100,120,0.06);
  color: var(--text-dim);
  font-size: 10px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.memo-toggle:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.memo-toggle.active {
  background: rgba(52,211,153,0.1);
  border-color: #34d399;
  color: #34d399;
}

/* Legend for memo mode */
.legend-cached {
  background: rgba(52,211,153,0.3);
  border: 1px solid #34d399;
}
.legend-computed {
  background: rgba(251,114,153,0.3);
  border: 1px solid #fb7299;
}

/* Memo savings counter */
.memo-savings-counter {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px;
  border-top: 1px solid var(--border);
  background: rgba(52,211,153,0.06);
  animation: counter-pulse 0.4s ease-out;
}
.memo-savings-icon {
  font-size: 14px;
}
.memo-savings-text {
  font-size: 11px; color: #34d399; font-weight: 600;
}

/* Execution invariant (memo mode) */
.exec-invariant {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 12px;
  background: rgba(52,211,153,0.04);
  border-bottom: 1px solid rgba(52,211,153,0.15);
}
.invariant-label {
  background: rgba(52,211,153,0.15);
  color: #34d399; font-size: 8px; font-weight: 800;
  padding: 2px 6px; border-radius: 3px; letter-spacing: 1px;
}
.invariant-text {
  font-size: 11px; color: var(--text-dim); font-weight: 500;
  font-style: italic;
}

/* Ready Queue (scheduler) */
.ready-queue {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 12px;
  background: rgba(52,211,153,0.04);
  border: 1px solid rgba(52,211,153,0.15);
  border-radius: 6px;
}
.ready-queue-header {
  display: flex; align-items: center; gap: 6px;
}
.ready-queue-badge {
  background: rgba(52,211,153,0.15);
  color: #34d399; font-size: 8px; font-weight: 800;
  padding: 2px 6px; border-radius: 3px; letter-spacing: 1px;
}
.ready-queue-title {
  font-size: 11px; font-weight: 600; color: var(--text-dim);
}
.ready-queue-count {
  font-size: 10px; color: var(--text-muted); margin-left: auto;
}
.ready-strategy {
  display: flex; flex-direction: column; gap: 3px;
}
.strategy-row {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  transition: all 0.2s;
}
.strategy-picked {
  background: rgba(52,211,153,0.12);
  border: 1px solid rgba(52,211,153,0.3);
}
.strategy-other {
  background: rgba(52,211,153,0.04);
  border: 1px solid rgba(52,211,153,0.08);
  opacity: 0.7;
}
.strategy-icon {
  font-size: 9px; width: 12px; text-align: center;
}
.strategy-picked .strategy-icon {
  color: #34d399;
}
.strategy-label {
  font-family: 'Fira Code', monospace;
  font-weight: 600;
  color: var(--text);
  min-width: 50px;
}
.strategy-picked .strategy-label {
  color: #34d399;
}
.strategy-arrow {
  color: var(--text-muted);
  font-size: 10px;
}
.strategy-unlock {
  color: #34d399;
  font-weight: 600;
}
.strategy-leaf {
  color: var(--text-muted);
  font-weight: 400;
  font-style: italic;
}
.strategy-targets {
  color: var(--text-muted);
  font-size: 10px;
  font-family: 'Fira Code', monospace;
}
.strategy-cascade {
  font-size: 9px;
  color: rgba(251,193,58,0.7);
  font-weight: 600;
  padding: 1px 4px;
  border-radius: 2px;
  background: rgba(251,193,58,0.08);
}
.strategy-badge {
  margin-left: auto;
  background: rgba(52,211,153,0.2);
  color: #34d399;
  font-size: 8px;
  font-weight: 800;
  padding: 1px 5px;
  border-radius: 3px;
  letter-spacing: 0.5px;
}
.ready-queue-pick {
  display: flex; align-items: center; gap: 6px;
  padding-top: 4px;
  border-top: 1px solid rgba(52,211,153,0.1);
}
.pick-arrow {
  color: #34d399; font-size: 12px; font-weight: 700;
}
.pick-text {
  font-size: 11px; color: var(--text-dim);
}
.pick-text strong {
  color: #34d399;
}

/* DAG node scheduler highlights */
.dag-node-picked rect {
  filter: url(#active-glow);
}
.ready-glow-ring {
  animation: ready-ring-pulse 1.5s ease-in-out infinite;
}
@keyframes ready-ring-pulse {
  0%, 100% { stroke-opacity: 0.3; }
  50% { stroke-opacity: 0.8; }
}
/* Will-unlock propagation: amber glow on nodes that would be unlocked */
.will-unlock-ring {
  animation: will-unlock-pulse 0.8s ease-in-out infinite;
}
@keyframes will-unlock-pulse {
  0%, 100% { stroke-opacity: 0.5; fill-opacity: 0.6; }
  50% { stroke-opacity: 1; fill-opacity: 1; }
}
.dag-node-will-unlock {
  filter: drop-shadow(0 0 6px rgba(251,193,58,0.4));
}
.dag-node-cascade {
  filter: drop-shadow(0 0 3px rgba(251,193,58,0.2));
}
.cascade-ring {
  animation: cascade-pulse 2s ease-in-out infinite;
}
@keyframes cascade-pulse {
  0%, 100% { stroke-opacity: 0.2; }
  50% { stroke-opacity: 0.5; }
}
/* Strategy row hover state */
.strategy-hovered {
  background: rgba(52,211,153,0.1) !important;
  border-color: rgba(52,211,153,0.4) !important;
}
.strategy-hovered .strategy-label {
  color: #34d399 !important;
}
.strategy-hovered .strategy-unlock {
  color: #fbb92a !important;
}
/* DAG hint bar */
.dag-hint {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 12px;
  background: rgba(251,193,58,0.05);
  border: 1px solid rgba(251,193,58,0.15);
  border-radius: 5px;
  margin-bottom: 6px;
}
.dag-hint-idle {
  background: rgba(52,211,153,0.04);
  border-color: rgba(52,211,153,0.12);
}
.dag-hint-icon {
  color: #fbb92a; font-weight: 700; font-size: 12px;
}
.dag-hint-idle .dag-hint-icon {
  color: var(--text-muted);
}
.dag-hint-text {
  font-size: 11px; color: var(--text-dim);
}
.dag-hint-bright {
  color: #fbb92a; font-weight: 700;
}
.dag-hint-dim {
  color: rgba(251,193,58,0.5); font-weight: 600;
}

/* Propagation edge: animated flow from ready node to unlock target */
.propagation-edge {
  animation: flow-propagation 1s linear infinite;
}
@keyframes flow-propagation {
  to { stroke-dashoffset: -18; }
}

/* Complexity curve */
.complexity-curve {
  padding: 6px 12px;
  border-top: 1px solid var(--border);
  background: rgba(15,23,42,0.3);
}
.curve-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 4px;
}
.curve-title {
  font-size: 10px; font-weight: 700; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: 0.5px;
}
.curve-stats {
  display: flex; align-items: center; gap: 4px; font-size: 10px;
}
.curve-total { color: #fb7299; font-weight: 600; }
.curve-sep { color: var(--text-muted); }
.curve-unique { color: #34d399; font-weight: 600; }
.curve-waste { color: var(--text-muted); font-weight: 400; }
.curve-svg {
  display: block;
}

/* Return Composition */
.current-composition {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding: 5px 8px;
  background: rgba(52,211,153,0.08);
  border: 1px solid rgba(52,211,153,0.2);
  border-radius: 4px;
}
.compose-icon {
  font-size: 12px;
  font-weight: 800;
  color: #34d399;
  flex-shrink: 0;
}
.compose-expr {
  font-size: 13px;
  font-weight: 700;
  color: #34d399;
  font-family: monospace;
  letter-spacing: 0.5px;
}
.current-children {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  flex-wrap: wrap;
}
.children-label {
  font-size: 9px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.child-result {
  font-size: 10px;
  font-family: monospace;
  color: var(--text-dim);
  padding: 2px 6px;
  background: rgba(167,139,250,0.06);
  border: 1px solid rgba(167,139,250,0.12);
  border-radius: 3px;
}

/* Combine operation type */
.combine-operation {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.combine-label {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.combine-type {
  font-size: 11px;
  font-weight: 800;
  color: #a78bfa;
  padding: 1px 8px;
  background: rgba(167,139,250,0.12);
  border: 1px solid rgba(167,139,250,0.25);
  border-radius: 4px;
  letter-spacing: 1px;
}

/* Cognitive Narrative: the explanation layer */
.cognitive-narrative {
  background: linear-gradient(135deg, rgba(251,114,153,0.05), rgba(167,139,250,0.05));
  border: 1px solid rgba(251,114,153,0.2);
  border-left: 3px solid var(--primary);
  border-radius: 0 8px 8px 0;
  padding: 12px 14px;
}
.cognitive-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.cognitive-badge {
  background: linear-gradient(135deg, #fb7299, #a78bfa);
  color: #0f172a;
  font-size: 9px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: 3px;
  letter-spacing: 1px;
}
.cognitive-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--primary);
}
.cognitive-text {
  font-size: 14px;
  color: var(--text);
  line-height: 1.7;
  letter-spacing: 0.01em;
  white-space: pre-line;
}

/* Auto Summary */
.auto-summary {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}
.summary-header {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 6px;
  margin-bottom: 10px;
}
.summary-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 8px;
  background: rgba(100,100,120,0.04);
  border-radius: 4px;
}
.summary-label {
  font-size: 9px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.summary-value {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  font-family: monospace;
}
.summary-warn {
  color: #fb923c;
}
.summary-op {
  color: #a78bfa;
  font-size: 12px;
  letter-spacing: 1px;
}
.summary-complexity {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}
.summary-complexity-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.summary-bad {
  color: #f87171;
  font-weight: 800;
}
.summary-good {
  color: #34d399;
  font-weight: 800;
}
.summary-highlight {
  color: var(--highlight);
  font-weight: 800;
}
.summary-memo {
  margin-top: 8px;
  padding: 6px 8px;
  background: rgba(52,211,153,0.06);
  border-left: 2px solid #34d399;
  border-radius: 0 4px 4px 0;
  font-size: 11px;
  color: var(--text);
}
</style>
