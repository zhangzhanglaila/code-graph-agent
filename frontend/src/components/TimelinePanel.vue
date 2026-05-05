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
  for (let i = 0; i <= store.currentStep; i++) {
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
  const levels = store.subproblemGraph?.layout?.level_info
  if (!levels?.length) return 1
  const costs = levels.map(l => l.level_cost ?? l.node_count)
  return Math.max(1, ...costs)
})

const levelCosts = computed(() => {
  const levels = store.subproblemGraph?.layout?.level_info
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

// Reset feedback when pattern changes
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
}

const execTrace = computed<ExecEvent[]>(() => {
  const dag = store.subproblemGraph?.dag
  const layout = store.subproblemGraph?.layout
  if (!dag || !layout) return []

  // Build adjacency: parent → [children] sorted by node id
  const children = new Map<string, string[]>()
  const parentOf = new Map<string, string>()
  for (const e of dag.edges) {
    if (!children.has(e.from)) children.set(e.from, [])
    children.get(e.from)!.push(e.to)
    parentOf.set(e.to, e.from)
  }
  for (const [, ch] of children) ch.sort()

  // Find root
  const hasParent = new Set(dag.edges.map(e => e.to))
  const root = dag.nodes.find(n => !hasParent.has(n.id))?.id || dag.nodes[0]?.id
  if (!root) return []

  const layoutNode = new Map(layout.nodes.map(n => [n.id, n]))

  // Track results as we DFS — children finish before parent
  const resultsMap = new Map<string, string>()

  const events: ExecEvent[] = []
  function dfs(nodeId: string, depth: number) {
    const ln = layoutNode.get(nodeId)
    const ch = children.get(nodeId) || []
    const isBase = ch.length === 0
    const parent = parentOf.get(nodeId)

    events.push({
      nodeId,
      type: 'call',
      name: ln?.label?.split('(')[0] || nodeId.split('(')[0],
      args: ln?.label?.match(/\(([^)]*)\)/)?.[1] || '',
      isBase,
      depth,
      parent,
    })

    for (const child of ch) {
      dfs(child, depth + 1)
    }

    // Children are done — collect their results for composition
    const node = dag.nodes.find(n => n.id === nodeId)
    const resultStr = node?.result != null ? String(node.result) : undefined
    if (resultStr != null) resultsMap.set(nodeId, resultStr)

    const childResults = ch
      .map(c => resultsMap.get(c))
      .filter((r): r is string => r != null)

    // Build composition expression
    let composition: string | undefined
    if (childResults.length >= 2) {
      composition = childResults.join(' + ') + ' = ' + resultStr
    } else if (childResults.length === 1 && !isBase) {
      // Single child — show what operation was applied
      composition = resultStr
    }

    events.push({
      nodeId,
      type: 'return',
      name: ln?.label?.split('(')[0] || nodeId.split('(')[0],
      args: ln?.label?.match(/\(([^)]*)\)/)?.[1] || '',
      returnValue: resultStr,
      composition,
      childResults: childResults.length > 0 ? childResults : undefined,
      isBase,
      depth,
      parent,
    })
  }
  dfs(root, 0)
  return events
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

function isNodeActive(node: { id: string }): boolean {
  const ev = execCurrentCall.value
  return ev?.nodeId === node.id
}

function isNodeVisited(node: { id: string }): boolean {
  const ev = execCurrentCall.value
  const currentIdx = execStep.value
  const trace = execTrace.value
  // Check if this node has been called before current step
  for (let i = 0; i <= currentIdx; i++) {
    if (trace[i]?.nodeId === node.id && trace[i]?.type === 'call') return true
  }
  return false
}

function isEdgeActive(edge: { from: string; to: string }): boolean {
  const ev = execCurrentCall.value
  if (!ev) return false
  if (ev.type === 'call') {
    // Call flow: parent → child (downward)
    if (ev.nodeId === edge.to) return true
    if (ev.nodeId === edge.from) {
      const trace = execTrace.value
      const idx = execStep.value
      if (idx + 1 < trace.length && trace[idx + 1]?.nodeId === edge.to) return true
    }
  } else {
    // Return flow: child → parent (upward) — highlight edge from child to current returning node
    if (ev.nodeId === edge.to) return true
  }
  return false
}

function isEdgeReturnFlow(edge: { from: string; to: string }): boolean {
  const ev = execCurrentCall.value
  if (!ev || ev.type !== 'return') return false
  // Return flow: edge TO the returning node (child → parent)
  return ev.nodeId === edge.to
}

function isNodeReturning(node: { id: string }): boolean {
  const ev = execCurrentCall.value
  return ev?.type === 'return' && ev.nodeId === node.id
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
  const pattern = store.subproblemGraph?.complexity?.pattern
  const levels = store.subproblemGraph?.layout?.level_info?.length
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
  const algoNarrative = store.patternResult?.narrative
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
    const complexity = store.patternResult?.complexity || ''
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
    sentences.push(`This algorithm executes through ${path.length} key steps.`)
  } else if (isLoopHeavy) {
    sentences.push(`This algorithm processes data through ${path.length} key steps, iterating to build up a result.`)
  } else {
    sentences.push(`This algorithm works through ${path.length} key steps to produce its result.`)
  }

  // Base case: if present, mention it early
  if (baseCaseStep && baseCaseStep !== path[0]) {
    const bcExp = getExplanation(baseCaseStep)
    sentences.push(`It first checks a base case — ${bcExp.toLowerCase()} — to handle the simplest scenario before proceeding.`)
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
      transition = 'First, '
    } else if (i === path.length - 1) {
      transition = 'Finally, '
    } else if (i === path.length - 2) {
      transition = 'Then, '
    } else if (imp === 'high') {
      transition = 'Critically, '
    } else {
      transition = 'Next, '
    }

    // Causal link
    let cause = ''
    const control = isControlEdge(prev, cur)
    const shared = sharedVars(prev, cur)
    if (control) {
      const condCode = getStep(prev)?.code?.replace(/^(if |elif |for |while )/, '').replace(/:$/, '') || ''
      cause = ` because "${condCode}" determines this path`
    } else if (shared.length > 0) {
      cause = ` using ${shared.join(' and ')} from the previous step`
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
      sentences.push(`This produces the final result: ${resultVar}.`)
    } else {
      sentences.push(`This produces the final result.`)
    }
  }

  // Complexity note if we have turning points
  const turningPoints = path.filter(s => getExp(s)?.turning_point)
  if (turningPoints.length > 0 && path.length > 4) {
    const tpStep = turningPoints[turningPoints.length - 1]
    const tpExp = getExplanation(tpStep)
    sentences.push(`The most significant turning point is at step ${tpStep}, where ${tpExp.toLowerCase()}.`)
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
  if (store.focusedExplanation && store.focusedExplanation.step === store.currentStep) {
    return store.focusedExplanation
  }
  return store.currentStepExplanation
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
  if (store.currentStep < store.totalSteps - 1) {
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
  if (store.currentStep < store.totalSteps - 1) {
    store.nextStep()

    // Importance-based delay
    const currentImp = store.currentStepExplanation?.importance || 'medium'
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
    <!-- Controls -->
    <div class="controls">
      <button class="btn btn-secondary btn-sm" @click="goToStepWithFocus(store.currentStep - 1)">&#9664;</button>
      <button class="btn btn-sm" :class="store.isPlaying && !explainPlaying ? 'btn-primary' : 'btn-secondary'" @click="togglePlay">
        {{ store.isPlaying && !explainPlaying ? '&#9632;' : '&#9654;' }}
      </button>
      <button class="btn btn-secondary btn-sm" @click="goToStepWithFocus(store.currentStep + 1)">&#9654;</button>
      <input
        type="range"
        class="slider"
        :min="0"
        :max="store.totalSteps - 1"
        :value="store.currentStep"
        @input="goToStepWithFocus(+($event.target as HTMLInputElement).value)"
      />
      <span class="step-display">{{ store.currentStep }} / {{ store.totalSteps - 1 }}</span>
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
        'is-loading': store.focusLoading,
      }"
    >
      <div class="explain-header">
        <span class="explain-badge">
          {{ store.focusLoading ? '...' : 'AI' }}
        </span>
        <span class="explain-step-label">Step {{ store.currentStep }}</span>
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
        <span v-if="activeExplanation.turning_point" class="turning-badge">TURNING POINT</span>
      </div>
      <!-- Natural language explanation (secondary, compact) -->
      <div v-if="activeExplanation.importance_explanation" class="explain-importance-text">
        {{ activeExplanation.importance_explanation }}
      </div>
      <!-- Causal link: affects downstream steps -->
      <div v-if="activeExplanation.affects?.length" class="explain-causal">
        <span class="causal-icon">→</span>
        Affects steps {{ activeExplanation.affects.join(', ') }}
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
      v-if="store.currentStepData"
      class="current-step card"
      :class="{ 'step-glow': activeExplanation?.importance === 'high' }"
    >
      <div class="step-header">
        <span class="step-num">Step {{ store.currentStepData.index }}</span>
        <span class="step-loc">{{ store.currentStepData.file }}:{{ store.currentStepData.line }}</span>
      </div>
      <div class="step-code">{{ store.currentStepData.code }}</div>
      <div v-if="store.currentStepData.changed.length" class="step-changes">
        Changed: {{ store.currentStepData.changed.join(', ') }}
      </div>
      <div v-if="store.currentStepData.new_vars.length" class="step-new">
        New: {{ store.currentStepData.new_vars.join(', ') }}
      </div>
    </div>

    <!-- Variable state -->
    <div v-if="store.currentStepData" class="vars-section">
      <div class="section-title">Variables</div>
      <div class="var-grid">
        <div
          v-for="(info, name) in store.currentStepData.vars"
          :key="name"
          class="var-card"
          :class="{ changed: info.changed, 'is-new': info.is_new }"
        >
          <div class="var-name">{{ name }}</div>
          <div class="var-value">{{ info.value }}</div>
          <div class="var-type">{{ info.type }}</div>
          <span v-if="info.changed" class="var-badge changed-badge">CHANGED</span>
          <span v-if="info.is_new" class="var-badge new-badge">NEW</span>
        </div>
      </div>
    </div>

    <!-- Importance Heatmap -->
    <div v-if="hasStepExplanations" class="heatmap-bar">
      <div class="heatmap-label">Importance</div>
      <div class="heatmap-row">
        <div
          v-for="step in steps"
          :key="step.index"
          class="heatmap-cell"
          :class="{ 'cell-current': step.index === store.currentStep }"
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
        <span class="narrative-badge">WHY</span>
        <span v-if="store.patternResult?.pattern" class="pattern-badge">{{ patternLabel(store.patternResult.pattern) }}</span>
        <span class="narrative-title">How this algorithm works</span>
        <span class="narrative-path">{{ criticalPathOrdered.join(' → ') }}</span>
      </div>
      <div class="narrative-text">{{ narrative }}</div>
      <!-- Complexity reasoning -->
      <div v-if="store.patternResult?.complexity" class="narrative-complexity">
        <span class="complexity-icon">⚡</span>
        {{ store.patternResult.complexity }}
      </div>
      <!-- Evidence chips -->
      <div v-if="store.patternResult?.properties" class="narrative-evidence">
        <span
          v-for="(data, prop) in store.patternResult.properties"
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
        <span>Steps</span>
        <button
          v-if="hasStepExplanations"
          class="toggle-all-btn"
          @click="store.showAllSteps = !store.showAllSteps"
        >
          {{ store.showAllSteps ? 'Auto-fold' : `Show all (${store.totalSteps})` }}
        </button>
      </div>
      <div class="steps-scroll">
        <template v-for="step in visibleSteps" :key="step.index">
          <!-- Skip indicator -->
          <div v-if="skippedCount(step.index) > 0" class="skip-indicator">
            {{ skippedCount(step.index) }} steps skipped
          </div>
          <div
            class="step-item"
            :class="{
              active: step.index === store.currentStep,
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
              affects → {{ store.stepExplanations.find(e => e.step === step.index)?.affects?.join(', ') }}
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
        <span>Causal Graph</span>
        <span class="graph-legend">
          <span class="legend-item"><span class="legend-line legend-data"></span> data</span>
          <span class="legend-item"><span class="legend-line legend-control"></span> control</span>
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
            'node-current': node.id === store.currentStep,
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
            :fill="node.id === causalSource ? 'rgba(34,211,238,0.12)' : criticalPath.has(node.id) ? 'rgba(251,114,153,0.10)' : node.id === store.currentStep ? 'rgba(251,114,153,0.15)' : executedSteps.has(node.id) ? 'rgba(167,139,250,0.08)' : 'rgba(100,100,120,0.04)'"
            :stroke="hoveredStep === node.id ? 'var(--highlight)' : criticalPath.has(node.id) ? 'var(--primary)' : node.importance === 'high' ? 'var(--primary)' : node.id === causalSource ? 'var(--highlight)' : executedSteps.has(node.id) ? 'rgba(167,139,250,0.3)' : 'var(--border)'"
            :stroke-width="hoveredStep === node.id || node.id === store.currentStep || criticalPath.has(node.id) ? 2.5 : 1.5"
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
            v-if="node.id === store.currentStep"
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
    <div v-if="store.subproblemGraph?.is_recursive && store.subproblemGraph?.layout" class="subproblem-section">
      <div class="subproblem-header">
        <span class="subproblem-badge">DAG</span>
        <span class="subproblem-title">Computation Structure</span>
        <span class="subproblem-stats" v-if="store.subproblemGraph.dag">
          {{ store.subproblemGraph.dag.unique_count }} unique / {{ store.subproblemGraph.dag.total_count }} total calls
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
          <div class="current-label">{{ execCurrentCall.type === 'call' ? '→ Calling' : execCurrentCall.type === 'return' ? '← Returning' : '· Base case' }}</div>
          <div class="current-call">{{ execCurrentCall.name }}({{ execCurrentCall.args }})</div>
          <div v-if="execCurrentCall.returnValue != null" class="current-return">returns {{ execCurrentCall.returnValue }}</div>
          <!-- Operation type: what kind of combine -->
          <div v-if="execCurrentCall.type === 'return' && store.subproblemGraph?.complexity?.combine_operation_label && store.subproblemGraph.complexity.combine_operation !== 'unknown'" class="combine-operation">
            <span class="combine-label">Combine</span>
            <span class="combine-type">{{ store.subproblemGraph.complexity.combine_operation_label }}</span>
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
        <!-- DAG with current node highlighted -->
        <div class="exec-dag">
          <svg
            :width="store.subproblemGraph.layout.width"
            :height="store.subproblemGraph.layout.height"
            class="dag-svg"
          >
            <defs>
              <marker id="dag-arrow-exec" markerWidth="6" markerHeight="5" refX="6" refY="2.5" orient="auto">
                <polygon points="0 0, 6 2.5, 0 5" fill="rgba(167,139,250,0.5)" />
              </marker>
              <marker id="dag-arrow-return" markerWidth="6" markerHeight="5" refX="6" refY="2.5" orient="auto">
                <polygon points="0 0, 6 2.5, 0 5" fill="#34d399" />
              </marker>
              <filter id="return-glow">
                <feGaussianBlur stdDeviation="2" result="blur"/>
                <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
              </filter>
            </defs>
            <!-- Base edges (faint) -->
            <g v-for="(edge, i) in store.subproblemGraph.layout.edges" :key="'ee'+i">
              <line
                :x1="edge.from_pos.x + store.subproblemGraph.layout.nodeW"
                :y1="edge.from_pos.y + store.subproblemGraph.layout.nodeH / 2"
                :x2="edge.to_pos.x"
                :y2="edge.to_pos.y + store.subproblemGraph.layout.nodeH / 2"
                stroke="rgba(167,139,250,0.15)"
                stroke-width="1"
              />
            </g>
            <!-- Active call flow (parent → child, downward) -->
            <g v-for="(edge, i) in store.subproblemGraph.layout.edges" :key="'ec'+i">
              <line
                v-if="isEdgeActive(edge) && !isEdgeReturnFlow(edge)"
                :x1="edge.from_pos.x + store.subproblemGraph.layout.nodeW"
                :y1="edge.from_pos.y + store.subproblemGraph.layout.nodeH / 2"
                :x2="edge.to_pos.x"
                :y2="edge.to_pos.y + store.subproblemGraph.layout.nodeH / 2"
                stroke="var(--primary)"
                stroke-width="2"
                marker-end="url(#dag-arrow-exec)"
              />
            </g>
            <!-- Return flow (child → parent, upward, glowing green) -->
            <g v-for="(edge, i) in store.subproblemGraph.layout.edges" :key="'er'+i">
              <line
                v-if="isEdgeReturnFlow(edge)"
                :x1="edge.from_pos.x + store.subproblemGraph.layout.nodeW"
                :y1="edge.from_pos.y + store.subproblemGraph.layout.nodeH / 2"
                :x2="edge.to_pos.x"
                :y2="edge.to_pos.y + store.subproblemGraph.layout.nodeH / 2"
                stroke="#34d399"
                stroke-width="2.5"
                filter="url(#return-glow)"
                marker-end="url(#dag-arrow-return)"
              />
            </g>
            <g
              v-for="node in store.subproblemGraph.layout.nodes"
              :key="node.id"
              :transform="`translate(${node.x}, ${node.y})`"
            >
              <rect
                :width="store.subproblemGraph.layout.nodeW"
                :height="store.subproblemGraph.layout.nodeH"
                rx="4"
                :fill="isNodeReturning(node) ? 'rgba(52,211,153,0.15)' : isNodeActive(node) ? 'rgba(34,211,238,0.15)' : isNodeVisited(node) ? 'rgba(100,100,120,0.06)' : 'rgba(100,100,120,0.02)'"
                :stroke="isNodeReturning(node) ? '#34d399' : isNodeActive(node) ? 'var(--accent)' : isNodeVisited(node) ? 'var(--border)' : 'rgba(100,100,120,0.1)'"
                :stroke-width="isNodeReturning(node) || isNodeActive(node) ? 2 : 1"
              />
              <text x="6" y="14" class="dag-label" :fill="isNodeReturning(node) ? '#34d399' : isNodeActive(node) ? 'var(--accent)' : 'var(--text-dim)'">
                {{ node.label }}
              </text>
              <text v-if="node.state_size != null" :x="store.subproblemGraph.layout.nodeW - 6" y="28" class="dag-state" fill="#a78bfa" text-anchor="end">
                n={{ node.state_size }}
              </text>
            </g>
          </svg>
        </div>
      </div>

      <!-- Pattern Label -->
      <div v-if="store.subproblemGraph?.complexity?.pattern_hint" class="pattern-label-box">
        <span class="pattern-label-icon">🧠</span>
        <span class="pattern-label-text">{{ store.subproblemGraph.complexity.pattern_description || patternLabel(store.subproblemGraph.complexity.pattern_hint) }}</span>
      </div>

      <!-- Auto Summary -->
      <div v-if="store.subproblemGraph?.complexity?.auto_summary" class="auto-summary">
        <div class="summary-header">Summary</div>
        <div class="summary-grid">
          <div class="summary-item">
            <span class="summary-label">Total calls</span>
            <span class="summary-value">{{ store.subproblemGraph.complexity.auto_summary.total_calls }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">Unique subproblems</span>
            <span class="summary-value">{{ store.subproblemGraph.complexity.auto_summary.unique_subproblems }}</span>
          </div>
          <div class="summary-item" v-if="store.subproblemGraph.complexity.auto_summary.repeated_calls > 0">
            <span class="summary-label">Repeated calls</span>
            <span class="summary-value summary-warn">{{ store.subproblemGraph.complexity.auto_summary.repeated_calls }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">Recursion depth</span>
            <span class="summary-value">{{ store.subproblemGraph.complexity.auto_summary.depth }}</span>
          </div>
          <div class="summary-item" v-if="store.subproblemGraph.complexity.auto_summary.branching_factor > 0">
            <span class="summary-label">Branching factor</span>
            <span class="summary-value">{{ store.subproblemGraph.complexity.auto_summary.branching_factor }}</span>
          </div>
          <div class="summary-item" v-if="store.subproblemGraph.complexity.auto_summary.operation !== 'COMBINE'">
            <span class="summary-label">Operation</span>
            <span class="summary-value summary-op">{{ store.subproblemGraph.complexity.auto_summary.operation }}</span>
          </div>
        </div>
        <div class="summary-complexity">
          <div class="summary-complexity-row">
            <span class="summary-label">Without cache</span>
            <span class="summary-value summary-bad">{{ store.subproblemGraph.complexity.auto_summary.complexity }}</span>
          </div>
          <div class="summary-complexity-row" v-if="store.subproblemGraph.complexity.auto_summary.optimized_complexity">
            <span class="summary-label">With cache</span>
            <span class="summary-value summary-good">{{ store.subproblemGraph.complexity.auto_summary.optimized_complexity.split(' --')[0] }}</span>
          </div>
          <div class="summary-complexity-row" v-if="store.subproblemGraph.complexity.auto_summary.speedup">
            <span class="summary-label">Speedup</span>
            <span class="summary-value summary-highlight">{{ store.subproblemGraph.complexity.auto_summary.speedup }}</span>
          </div>
        </div>
        <div class="summary-memo" v-if="store.subproblemGraph.complexity.auto_summary.has_memoization_benefit">
          💡 Memoization would reduce calls from {{ store.subproblemGraph.complexity.auto_summary.total_calls }} to {{ store.subproblemGraph.complexity.auto_summary.unique_subproblems }}
        </div>
      </div>

      <!-- Analysis Mode: complexity + DAG + sandbox -->
      <div v-if="subMode === 'analysis'">

      <!-- Complexity Analysis -->
      <div class="complexity-card" v-if="store.subproblemGraph.complexity">
        <div class="complexity-row" v-if="store.subproblemGraph.complexity.pattern">
          <span class="complexity-label">Pattern</span>
          <span class="complexity-value complexity-highlight">{{ patternLabel(store.subproblemGraph.complexity.pattern) }}</span>
          <span v-if="store.subproblemGraph.complexity.execution" class="execution-tag" :class="store.subproblemGraph.complexity.execution.toLowerCase()">
            {{ store.subproblemGraph.complexity.execution }}
          </span>
          <span v-if="store.subproblemGraph.complexity.shrink && store.subproblemGraph.complexity.shrink !== 'none'" class="shrink-tag">
            {{ store.subproblemGraph.complexity.shrink }}
          </span>
        </div>
        <div class="complexity-row">
          <span class="complexity-label">Recurrence</span>
          <span class="complexity-value">{{ store.subproblemGraph.complexity.recurrence }}</span>
        </div>
        <div class="complexity-row">
          <span class="complexity-label">Without cache</span>
          <span class="complexity-value complexity-bad">{{ store.subproblemGraph.complexity.without_cache }}</span>
        </div>
        <div class="complexity-row">
          <span class="complexity-label">With cache</span>
          <span class="complexity-value complexity-good">{{ store.subproblemGraph.complexity.with_cache }}</span>
        </div>
        <div class="complexity-row">
          <span class="complexity-label">Speedup</span>
          <span class="complexity-value complexity-highlight">{{ store.subproblemGraph.complexity.speedup }}</span>
        </div>
      </div>

      <!-- Semantic Explanation -->
      <div v-if="store.subproblemGraph.complexity?.semantic_explanation" class="semantic-explanation">
        <div class="semantic-header">Why this complexity?</div>
        <div class="semantic-lines">
          <div
            v-for="(line, i) in store.subproblemGraph.complexity.semantic_explanation.split('\n')"
            :key="i"
            class="semantic-line"
            :class="{ 'semantic-conclusion': line.includes('→') || line.includes('Therefore') }"
          >{{ line }}</div>
        </div>
      </div>

      <!-- DAG Visualization -->
      <div class="dag-container">
        <svg
          :width="store.subproblemGraph.layout.width"
          :height="store.subproblemGraph.layout.height"
          class="dag-svg"
        >
          <defs>
            <marker id="dag-arrow" markerWidth="6" markerHeight="5" refX="6" refY="2.5" orient="auto">
              <polygon points="0 0, 6 2.5, 0 5" fill="rgba(167,139,250,0.5)" />
            </marker>
          </defs>
          <!-- Edges -->
          <g v-for="(edge, i) in store.subproblemGraph.layout.edges" :key="'de'+i">
            <line
              :x1="edge.from_pos.x + store.subproblemGraph.layout.nodeW"
              :y1="edge.from_pos.y + store.subproblemGraph.layout.nodeH / 2"
              :x2="edge.to_pos.x"
              :y2="edge.to_pos.y + store.subproblemGraph.layout.nodeH / 2"
              stroke="rgba(167,139,250,0.35)"
              stroke-width="1.5"
              marker-end="url(#dag-arrow)"
            />
            <!-- Edge label: subproblem size -->
            <text
              v-if="edge.size_label"
              :x="(edge.from_pos.x + store.subproblemGraph.layout.nodeW + edge.to_pos.x) / 2"
              :y="(edge.from_pos.y + store.subproblemGraph.layout.nodeH / 2 + edge.to_pos.y + store.subproblemGraph.layout.nodeH / 2) / 2 - 4"
              class="edge-label"
              fill="#a78bfa"
              text-anchor="middle"
            >{{ edge.size_label }}</text>
          </g>
          <!-- Nodes -->
          <g
            v-for="node in store.subproblemGraph.layout.nodes"
            :key="node.id"
            :transform="`translate(${node.x}, ${node.y})`"
            class="dag-node"
            :class="{ 'dag-reused': node.is_reused }"
          >
            <rect
              :width="store.subproblemGraph.layout.nodeW"
              :height="store.subproblemGraph.layout.nodeH"
              rx="4"
              :fill="node.is_reused ? 'rgba(251,114,153,0.12)' : 'rgba(100,100,120,0.06)'"
              :stroke="node.is_reused ? 'var(--primary)' : 'var(--border)'"
              :stroke-width="node.is_reused ? 2 : 1"
            />
            <text x="6" y="14" class="dag-label" :fill="node.is_reused ? 'var(--primary)' : 'var(--text-dim)'">
              {{ node.label }}
            </text>
            <text v-if="node.state_size != null" :x="store.subproblemGraph.layout.nodeW - 6" y="28" class="dag-state" fill="#a78bfa" text-anchor="end">
              n={{ node.state_size }}
            </text>
            <text v-else-if="node.result != null" x="6" y="28" class="dag-result" fill="var(--text-muted)">
              → {{ String(node.result).slice(0, 12) }}
            </text>
            <!-- Reuse count badge -->
            <g v-if="node.call_count > 1">
              <circle :cx="store.subproblemGraph.layout.nodeW - 8" cy="10" r="8" fill="var(--primary)" />
              <text :x="store.subproblemGraph.layout.nodeW - 8" y="14" class="dag-count" fill="#0f172a" text-anchor="middle">
                {{ node.call_count }}
              </text>
            </g>
          </g>
        </svg>
      </div>

      <!-- Recursion Level View -->
      <div v-if="store.subproblemGraph.layout?.level_info?.length" class="level-view">
        <div class="level-header">Cost per Level</div>
        <div class="level-rows">
          <div
            v-for="lvl in store.subproblemGraph.layout.level_info"
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
        <div class="level-proof" v-if="store.subproblemGraph.complexity">
          <template v-if="isCostBalanced">
            <div class="proof-line">
              <span class="proof-icon">→</span>
              <span>Each level costs ~{{ avgLevelCost }}</span>
            </div>
            <div class="proof-line">
              <span class="proof-icon">→</span>
              <span>{{ store.subproblemGraph.layout.level_info.length }} levels total</span>
            </div>
            <div class="proof-line proof-conclusion">
              <span class="proof-icon">∴</span>
              <span>{{ avgLevelCost }} × {{ store.subproblemGraph.layout.level_info.length }} = </span>
              <span class="proof-result">{{ store.subproblemGraph.complexity.without_cache?.split(' --')[0] }}</span>
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
              <span class="proof-result">{{ store.subproblemGraph.complexity.without_cache?.split(' --')[0] }}</span>
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
              <span class="proof-result">{{ store.subproblemGraph.complexity.without_cache?.split(' --')[0] }}</span>
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
      <div v-if="store.subproblemGraph.complexity?.shared_subproblems?.length" class="shared-subs">
        <div class="shared-title">Most recomputed subproblems:</div>
        <div
          v-for="sub in store.subproblemGraph.complexity.shared_subproblems.slice(0, 5)"
          :key="sub.id"
          class="shared-item"
        >
          <span class="shared-id">{{ sub.id }}</span>
          <span class="shared-count">×{{ sub.called }}</span>
        </div>
      </div>

      <!-- Performance narrative -->
      <div v-if="store.subproblemGraph.narrative" class="perf-narrative">
        {{ store.subproblemGraph.narrative }}
      </div>

      </div><!-- end analysis mode -->
    </div>
  </div>
</template>

<style scoped>
.timeline-panel { display: flex; flex-direction: column; gap: 12px; }

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
  padding: 8px 10px;
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

/* Pattern label */
.pattern-label-box {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: rgba(251,114,153,0.06);
  border: 1px solid rgba(251,114,153,0.15);
  border-radius: 6px;
}
.pattern-label-icon {
  font-size: 14px;
}
.pattern-label-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary);
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
