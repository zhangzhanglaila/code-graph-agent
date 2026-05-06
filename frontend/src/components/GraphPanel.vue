<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()
const graphContainer = ref<HTMLElement>()

// Unified data source: store.timeline
const steps = computed(() => store.timeline)

// Scheduler semantics: who unlocks whom
const unlockMap = computed(() => {
  const map = new Map<number, number[]>()
  for (const exp of store.stepExplanations) {
    map.set(exp.step, exp.affects || [])
  }
  return map
})

// Cascade: DFS from direct unlocks, depth-limited
function computeCascade(from: number, maxDepth = 2): Set<number> {
  const direct = unlockMap.value.get(from) || []
  const cascade = new Set<number>()
  const visited = new Set<number>()

  function dfs(node: number, depth: number) {
    if (visited.has(node) || depth > maxDepth) return
    visited.add(node)
    if (!direct.includes(node)) cascade.add(node)
    const children = unlockMap.value.get(node) || []
    for (const child of children) dfs(child, depth + 1)
  }

  for (const d of direct) {
    const children = unlockMap.value.get(d) || []
    for (const child of children) dfs(child, 1)
  }
  return cascade
}

// Hover state: which node the user is looking at
const hoveredNode = ref<number | null>(null)

// Effective focus: hovered node, or current step if nothing hovered
const focusNode = computed(() => hoveredNode.value ?? store.currentStep)

const directUnlocks = computed(() => {
  if (focusNode.value == null) return new Set<number>()
  return new Set(unlockMap.value.get(focusNode.value) || [])
})

const cascadeNodes = computed(() => {
  if (focusNode.value == null) return new Set<number>()
  return computeCascade(focusNode.value)
})

// Goal nodes: steps that produce the algorithm's result
const goalSteps = computed(() => {
  const goals = new Set<number>()
  for (const step of steps.value) {
    const code = step.code?.trim() || ''
    if (code.startsWith('return ')) goals.add(step.index)
  }
  // Fallback: last step is always a goal
  if (goals.size === 0 && steps.value.length > 0) {
    goals.add(steps.value[steps.value.length - 1].index)
  }
  return goals
})

// Recommended node: highest impact score
const recommended = computed(() => {
  let best: number | null = null
  let bestScore = -1
  for (const step of steps.value) {
    const unlock = unlockMap.value.get(step.index)?.length || 0
    const cascade = computeCascade(step.index).size
    const isGoal = goalSteps.value.has(step.index)
    const score = (isGoal ? 100 : 0) + unlock * 2 + cascade
    if (score > bestScore) { bestScore = score; best = step.index }
  }
  return best
})

// Recommended reason: WHY this node is recommended
const recommendedReason = computed(() => {
  const rec = recommended.value
  if (rec === null) return null
  const unlock = unlockMap.value.get(rec)?.length || 0
  const cascade = computeCascade(rec).size
  const isGoal = goalSteps.value.has(rec)
  return { step: rec, unlock, cascade, total: unlock + cascade, isGoal }
})

// Recommended path: weighted BFS — causal(3) > unlock(2) > sequential(1)
const bestPath = computed(() => {
  const current = store.currentStep
  const goals = goalSteps.value
  if (!goals.size) return { nodes: new Set<number>(), edges: new Set<string>(), steps: [] as {from: number, to: number, type: string, varName: string}[] }

  // Build weighted adjacency: { to, weight, type, varName }
  const adj = new Map<number, { to: number, weight: number, type: string, varName: string }[]>()

  function addEdge(from: number, to: number, weight: number, type: string, varName: string) {
    if (!adj.has(from)) adj.set(from, [])
    adj.get(from)!.push({ to, weight, type, varName })
  }

  for (const ce of store.causalEdges) addEdge(ce.from, ce.to, 3, 'causal', ce.var)
  for (const [from, targets] of unlockMap.value) {
    for (const t of targets) addEdge(from, t, 2, 'unlock', '')
  }
  const sorted = steps.value.map(s => s.index).sort((a, b) => a - b)
  for (let i = 0; i < sorted.length - 1; i++) addEdge(sorted[i], sorted[i + 1], 1, 'sequential', '')

  // Dijkstra-like: maximize total weight (prefer causal paths)
  const dist = new Map<number, number>()
  const prev = new Map<number, { node: number, type: string, varName: string }>()
  const visited = new Set<number>()
  dist.set(current, 0)

  // Simple priority queue (sorted array — fine for small graphs)
  const queue: { node: number, cost: number }[] = [{ node: current, cost: 0 }]

  while (queue.length) {
    queue.sort((a, b) => a.cost - b.cost)
    const { node } = queue.shift()!
    if (visited.has(node)) continue
    visited.add(node)

    if (goals.has(node) && node !== current) {
      // Reconstruct path
      const path: number[] = []
      const edgeInfo: { from: number, to: number, type: string, varName: string }[] = []
      let cur = node
      while (prev.has(cur)) {
        const p = prev.get(cur)!
        path.unshift(cur)
        edgeInfo.unshift({ from: p.node, to: cur, type: p.type, varName: p.varName })
        cur = p.node
      }
      path.unshift(current)
      const pathNodes = new Set(path)
      const pathEdges = new Set<string>()
      for (let i = 0; i < path.length - 1; i++) pathEdges.add(`${path[i]}-${path[i + 1]}`)
      return { nodes: pathNodes, edges: pathEdges, steps: edgeInfo }
    }

    for (const edge of (adj.get(node) || [])) {
      if (visited.has(edge.to)) continue
      const newCost = (dist.get(node) || 0) + (10 - edge.weight) // lower cost = higher weight preferred
      if (!dist.has(edge.to) || newCost < dist.get(edge.to)!) {
        dist.set(edge.to, newCost)
        prev.set(edge.to, { node, type: edge.type, varName: edge.varName })
        queue.push({ node: edge.to, cost: newCost })
      }
    }
  }

  return { nodes: new Set<number>(), edges: new Set<string>(), steps: [] }
})

// Layer visibility toggles
const showDependency = ref(false)
const showCascade = ref(false)

// Path explanation: human-readable WHY
const pathExplanation = computed(() => {
  const p = bestPath.value
  if (!p.steps.length) return []
  return p.steps.map(s => {
    const fromCode = steps.value.find(st => st.index === s.from)?.code?.trim()?.slice(0, 30) || `Step ${s.from}`
    const toCode = steps.value.find(st => st.index === s.to)?.code?.trim()?.slice(0, 30) || `Step ${s.to}`
    if (s.type === 'causal' && s.varName) {
      return { text: `${fromCode} produces \`${s.varName}\` → used by ${toCode}`, type: 'causal' }
    }
    if (s.type === 'unlock') {
      return { text: `${fromCode} unlocks → ${toCode}`, type: 'unlock' }
    }
    return { text: `${fromCode} → ${toCode}`, type: 'sequential' }
  })
})

// Summary hover: which segment the user is pointing at
const summaryHover = ref<number | null>(null)

// Structured summary segments: each segment has text + optional step index for highlighting
interface SummarySegment { text: string; step?: number }
const pathSummary = computed<{ label: string; segments: SummarySegment[] } | null>(() => {
  const p = bestPath.value
  if (!p.steps.length) return null

  // Collect causal edges with variable names and their step indices
  const causalEdges = p.steps
    .filter(s => s.type === 'causal' && s.varName)
    .map(s => ({ varName: s.varName, from: s.from, to: s.to }))

  const goalStep = p.steps[p.steps.length - 1]
  const goalIdx = goalStep?.to

  if (causalEdges.length >= 2) {
    const segments: SummarySegment[] = []
    for (let i = 0; i < causalEdges.length; i++) {
      if (i > 0) segments.push({ text: ' → ' })
      segments.push({ text: causalEdges[i].varName, step: causalEdges[i].from })
    }
    segments.push({ text: ' → result', step: goalIdx })
    return { label: 'Data flows:', segments }
  }
  if (causalEdges.length === 1) {
    return {
      label: 'Key variable:',
      segments: [
        { text: causalEdges[0].varName, step: causalEdges[0].from },
        { text: ' drives the result', step: goalIdx },
      ],
    }
  }
  return {
    label: '',
    segments: [{ text: `Sequential execution (${p.steps.length} steps)`, step: goalIdx }],
  }
})

// Selected node (clicked)
const selectedNode = ref<number | null>(null)

const selectedNodeInfo = computed(() => {
  const idx = selectedNode.value
  if (idx === null) return null
  const step = steps.value.find(s => s.index === idx)
  if (!step) return null
  const unlock = unlockMap.value.get(idx)?.length || 0
  const cascade = computeCascade(idx).size
  const isGoal = goalSteps.value.has(idx)
  const isRec = recommended.value === idx
  return {
    step: idx,
    code: step.code?.trim() || '',
    changed: step.changed || [],
    unlock,
    cascade,
    total: unlock + cascade,
    isGoal,
    isRecommended: isRec,
  }
})

onMounted(() => {
  if (steps.value.length) renderGraph()
})

watch(steps, () => {
  if (steps.value.length) renderGraph()
})

watch([() => store.currentStep, focusNode, summaryHover], () => {
  if (steps.value.length) renderGraph()
})

async function renderGraph() {
  if (!graphContainer.value || !steps.value.length) return

  const cytoscape = (await import('cytoscape')).default
  const dagre = (await import('cytoscape-dagre')).default
  cytoscape.use(dagre)

  const timeline = steps.value
  const unlocks = directUnlocks.value
  const cascade = cascadeNodes.value
  const focus = focusNode.value
  const goals = goalSteps.value
  const path = bestPath.value

  // Build elements
  const elements: any[] = []

  const rec = recommended.value

  for (const step of timeline) {
    const isActive = step.index === store.currentStep
    const isUnlock = unlocks.has(step.index)
    const isCascade = cascade.has(step.index) && showCascade.value
    const isFocus = step.index === focus
    const isGoal = goals.has(step.index)
    const isRecommended = step.index === rec
    const isOnPath = path.nodes.has(step.index) && !isActive
    const isSummaryHover = summaryHover.value === step.index

    let rawCode = step.code?.trim() || ''
    if (/^[A-Z]:\\|^\/|:\d+$/.test(rawCode)) rawCode = ''
    let label = rawCode || `Step ${step.index}`
    if (label.length > 30) label = label.slice(0, 27) + '...'
    // Semantic markers (priority: active > path > recommended > focus > unlock > cascade)
    if (isActive) label = `▶ ${label}`
    else if (isOnPath) label = `▸ ${label}`
    else if (isRecommended) label = `✓ ${label}`
    else if (isFocus) label = `◎ ${label}`
    else if (isUnlock) label = `→ ${label}`
    else if (isCascade) label = `↠ ${label}`
    if (isGoal) label = `★ ${label}`

    elements.push({
      data: {
        id: String(step.index),
        label,
        isActive,
        isUnlock,
        isCascade,
        isFocus,
        isGoal,
        isRecommended,
        isOnPath,
        isSummaryHover,
        code: step.code?.trim(),
        changed: step.changed?.join(', ') || '',
      },
    })
  }

  // Data flow edges (from stepExplanations.affects)
  for (const exp of store.stepExplanations) {
    for (const target of (exp.affects || [])) {
      if (timeline.some(s => s.index === exp.step) && timeline.some(s => s.index === target)) {
        const isUnlockEdge = unlocks.has(target) && exp.step === focus
        const isCascadeEdge = cascade.has(target) && (unlocks.has(exp.step) || cascade.has(exp.step))
        if (isCascadeEdge && !showCascade.value) continue
        const edgeKey = `${exp.step}-${target}`
        elements.push({
          data: {
            source: String(exp.step),
            target: String(target),
            edgeType: 'data',
            isUnlockEdge,
            isCascadeEdge,
            isPathEdge: path.edges.has(edgeKey),
          },
        })
      }
    }
  }

  // Control flow edges
  for (const ce of store.controlEdges) {
    if (timeline.some(s => s.index === ce.from) && timeline.some(s => s.index === ce.to)) {
      const isUnlockEdge = unlocks.has(ce.to) && ce.from === focus
      const edgeKey = `${ce.from}-${ce.to}`
      elements.push({
        data: {
          source: String(ce.from),
          target: String(ce.to),
          edgeType: 'control',
          isUnlockEdge,
          isCascadeEdge: false,
          isPathEdge: path.edges.has(edgeKey),
        },
      })
    }
  }

  // Causal edges (data dependency: who writes → who reads)
  if (showDependency.value) {
    for (const ce of store.causalEdges) {
      if (timeline.some(s => s.index === ce.from) && timeline.some(s => s.index === ce.to)) {
        const edgeKey = `${ce.from}-${ce.to}`
        elements.push({
          data: {
            source: String(ce.from),
            target: String(ce.to),
            edgeType: 'causal',
            label: ce.var,
            isUnlockEdge: false,
            isCascadeEdge: false,
            isPathEdge: path.edges.has(edgeKey),
          },
        })
      }
    }
  }

  const cy = cytoscape({
    container: graphContainer.value,
    elements,
    style: [
      {
        selector: 'node',
        style: {
          'background-color': (ele: any) => {
            if (ele.data('isSummaryHover')) return '#f59e0b'  // amber: summary highlight
            if (ele.data('isActive')) return '#10b981'      // green: computing now
            if (ele.data('isOnPath')) return '#3b82f6'      // blue: on recommended path
            if (ele.data('isRecommended')) return '#0284c7'  // B站蓝 deep: recommended
            if (ele.data('isGoal')) return '#d97706'        // gold deep: goal
            if (ele.data('isUnlock')) return '#fb7185'      // B站 pink: direct unlock
            if (ele.data('isCascade')) return '#9a3412'     // dark orange deep: cascade
            return '#e2e8f0'                                  // gray: idle
          },
          'border-color': (ele: any) => {
            if (ele.data('isSummaryHover')) return '#d97706'
            if (ele.data('isActive')) return '#059669'
            if (ele.data('isOnPath')) return '#2563eb'
            if (ele.data('isRecommended')) return '#0369a1'
            if (ele.data('isGoal')) return '#b45309'
            if (ele.data('isUnlock')) return '#e11d48'
            if (ele.data('isCascade')) return '#7c2d12'
            return '#94a3b8'
          },
          'border-width': (ele: any) => ele.data('isSummaryHover') || ele.data('isActive') || ele.data('isOnPath') || ele.data('isRecommended') || ele.data('isUnlock') || ele.data('isGoal') ? 2.5 : 1.5,
          'label': 'data(label)',
          'font-size': '10px',
          'color': '#1e293b',
          'text-outline-color': '#ffffff',
          'text-outline-width': 2,
          'width': (ele: any) => ele.data('isSummaryHover') ? 42 : ele.data('isOnPath') ? 36 : ele.data('isRecommended') ? 40 : ele.data('isUnlock') || ele.data('isGoal') ? 38 : 30,
          'height': (ele: any) => ele.data('isSummaryHover') ? 42 : ele.data('isOnPath') ? 36 : ele.data('isRecommended') ? 40 : ele.data('isUnlock') || ele.data('isGoal') ? 38 : 30,
          'text-valign': 'bottom',
          'text-margin-y': 5,
        } as any,
      },
      {
        selector: 'edge',
        style: {
          'width': (ele: any) => ele.data('isPathEdge') ? 3 : ele.data('isUnlockEdge') ? 2.5 : ele.data('isCascadeEdge') ? 1.8 : 1,
          'line-color': (ele: any) => {
            if (ele.data('isPathEdge')) return '#3b82f6'
            if (ele.data('isUnlockEdge')) return '#fb7185'
            if (ele.data('isCascadeEdge')) return 'rgba(154,52,18,0.6)'
            if (ele.data('edgeType') === 'causal') return '#7c3aed'
            return 'rgba(100,116,139,0.4)'
          },
          'target-arrow-color': (ele: any) => {
            if (ele.data('isPathEdge')) return '#3b82f6'
            if (ele.data('isUnlockEdge')) return '#fb7185'
            if (ele.data('isCascadeEdge')) return 'rgba(154,52,18,0.6)'
            if (ele.data('edgeType') === 'causal') return '#7c3aed'
            return 'rgba(100,116,139,0.4)'
          },
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'arrow-scale': 0.8,
          'line-style': (ele: any) => {
            if (ele.data('edgeType') === 'control') return 'dashed'
            if (ele.data('edgeType') === 'causal') return 'dotted'
            return 'solid'
          },
          'label': (ele: any) => ele.data('label') || '',
          'font-size': '8px',
          'color': '#7c3aed',
          'text-rotation': 'autorotate',
          'text-margin-y': -6,
        } as any,
      },
    ],
    layout: {
      name: 'dagre',
      rankDir: 'LR',
      spacingFactor: 1.2,
    } as any,
    userZoomingEnabled: true,
    userPanningEnabled: true,
  })

  // Click node → show detail card
  cy.on('tap', 'node', (evt: any) => {
    const idx = parseInt(evt.target.id())
    selectedNode.value = selectedNode.value === idx ? null : idx
  })

  // Click background → deselect
  cy.on('tap', (evt: any) => {
    if (evt.target === cy) selectedNode.value = null
  })
}

function onNodeHover(stepIndex: number) {
  hoveredNode.value = stepIndex
}

function onNodeLeave() {
  hoveredNode.value = null
}
</script>

<template>
  <div class="graph-panel animate-slide-up">
    <!-- Controls -->
    <div class="graph-controls">
      <label class="toggle-label">
        <input type="checkbox" v-model="showDependency" />
        <span>Show Dependency</span>
      </label>
      <label class="toggle-label">
        <input type="checkbox" v-model="showCascade" />
        <span>Show Cascade</span>
      </label>
      <span v-if="bestPath.nodes.size > 1" class="path-info">
        Path to goal: {{ bestPath.nodes.size }} steps
      </span>
    </div>

    <!-- Legend -->
    <div class="legend">
      <span class="legend-item">
        <span class="legend-dot" style="background:#10b981"></span>
        computing now
      </span>
      <span class="legend-item">
        <span class="legend-dot" style="background:#3b82f6"></span>
        path to goal
      </span>
      <span class="legend-item">
        <span class="legend-dot" style="background:#0284c7"></span>
        recommended
      </span>
      <span class="legend-item">
        <span class="legend-dot" style="background:#d97706"></span>
        goal
      </span>
      <span class="legend-item">
        <span class="legend-dot" style="background:#fb7185"></span>
        unlocks if picked
      </span>
      <span class="legend-item">
        <span class="legend-dot" style="background:#9a3412"></span>
        cascade effect
      </span>
      <span class="legend-item">
        <span class="legend-line" style="background:#fb7185"></span>
        direct unlock
      </span>
      <span class="legend-item">
        <span class="legend-line" style="background:rgba(154,52,18,0.6)"></span>
        cascade chain
      </span>
      <span class="legend-item">
        <span class="legend-line" style="background:#7c3aed; border-top: 2px dotted #7c3aed"></span>
        data dependency
      </span>
    </div>

    <!-- Graph -->
    <div ref="graphContainer" class="graph-container"></div>

    <!-- Stats -->
    <div v-if="steps.length" class="stats">
      {{ steps.length }} steps | {{ goalSteps.size }} goal{{ goalSteps.size > 1 ? 's' : '' }}
      <template v-if="focusNode != null">
        | Step {{ focusNode }} unlocks {{ directUnlocks.size }}
        <template v-if="cascadeNodes.size > 0"> → cascades to {{ cascadeNodes.size }}</template>
        | impact {{ directUnlocks.size + cascadeNodes.size }}
      </template>
    </div>

    <!-- Path explanation -->
    <div v-if="pathExplanation.length" class="path-explain animate-slide-up">
      <div class="path-title">Why this path?</div>
      <div v-if="pathSummary" class="path-summary" @mouseleave="summaryHover = null">
        <span class="summary-label">{{ pathSummary.label }}</span>
        <span
          v-for="(seg, i) in pathSummary.segments"
          :key="i"
          :class="['summary-seg', { 'summary-link': seg.step != null, 'summary-active': seg.step != null && summaryHover === seg.step }]"
          @mouseenter="seg.step != null ? summaryHover = seg.step : null"
        >{{ seg.text }}</span>
      </div>
      <div class="path-desc">This path follows how data flows to the final result:</div>
      <div class="path-steps">
        <div v-for="(step, i) in pathExplanation" :key="i" :class="['path-step', `path-${step.type}`]">
          <span class="path-num">{{ i + 1 }}</span>
          <span class="path-text">{{ step.text }}</span>
          <span v-if="step.type === 'causal'" class="path-badge causal">data</span>
          <span v-else-if="step.type === 'unlock'" class="path-badge unlock">unlock</span>
        </div>
      </div>
    </div>

    <!-- Node detail card -->
    <div v-if="selectedNodeInfo" class="node-detail animate-slide-up">
      <div class="detail-top">
        <span class="detail-step">Step {{ selectedNodeInfo.step }}</span>
        <span v-if="selectedNodeInfo.isRecommended" class="detail-badge rec">RECOMMENDED</span>
        <span v-if="selectedNodeInfo.isGoal" class="detail-badge goal">GOAL</span>
        <button class="detail-close" @click="selectedNode = null">&times;</button>
      </div>
      <code class="detail-code">{{ selectedNodeInfo.code }}</code>
      <div v-if="selectedNodeInfo.changed.length" class="detail-changed">
        changed: {{ selectedNodeInfo.changed.join(', ') }}
      </div>
      <div class="detail-impact">
        <span class="impact-item"><b>{{ selectedNodeInfo.unlock }}</b> direct unlock</span>
        <span class="impact-sep">→</span>
        <span class="impact-item"><b>{{ selectedNodeInfo.cascade }}</b> cascade</span>
        <span class="impact-sep">|</span>
        <span class="impact-item"><b>{{ selectedNodeInfo.total }}</b> total impact</span>
      </div>
      <div v-if="selectedNodeInfo.isRecommended && recommendedReason" class="detail-why">
        <div class="why-title">Why recommended:</div>
        <div class="why-line">
          <span v-if="recommendedReason.unlock">Unlocks {{ recommendedReason.unlock }} direct steps</span>
          <span v-if="recommendedReason.unlock && recommendedReason.cascade">, </span>
          <span v-if="recommendedReason.cascade">cascades to {{ recommendedReason.cascade }} more</span>
          <span v-if="recommendedReason.isGoal">, leads to goal</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.graph-panel { display: flex; flex-direction: column; height: 100%; }

.graph-controls {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 6px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 8px;
  font-size: 12px;
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-dim);
  cursor: pointer;
}

.toggle-label input[type="checkbox"] {
  accent-color: var(--primary);
}

.path-info {
  margin-left: auto;
  color: #3b82f6;
  font-weight: 600;
  font-size: 11px;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 8px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 8px;
}

.legend-item { display: flex; align-items: center; gap: 4px; font-size: 10px; color: var(--text-dim); }

.legend-line {
  width: 16px;
  height: 2px;
  border-top: 2px solid;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.graph-container {
  flex: 1;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  min-height: 400px;
}

.stats {
  font-size: 11px;
  color: var(--text-muted);
  padding: 6px 0;
  text-align: center;
}

.node-detail {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-top: 8px;
}

.detail-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.detail-step {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}

.detail-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: 0.5px;
}
.detail-badge.rec {
  background: rgba(0,161,214,0.1);
  color: #00a1d6;
}
.detail-badge.goal {
  background: rgba(251,191,36,0.1);
  color: #d97706;
}

.detail-close {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
}
.detail-close:hover { color: var(--text); }

.detail-code {
  display: block;
  font-size: 12px;
  color: var(--text);
  background: rgba(0,0,0,0.03);
  padding: 6px 10px;
  border-radius: 4px;
  margin-bottom: 8px;
  white-space: pre-wrap;
  word-break: break-all;
}

.detail-changed {
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 8px;
}

.detail-impact {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-dim);
}
.impact-item b {
  color: var(--text);
  font-weight: 700;
}
.impact-sep { color: var(--text-muted); }

.detail-why {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.why-title {
  font-size: 11px;
  font-weight: 700;
  color: #00a1d6;
  margin-bottom: 4px;
}

.why-line {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.5;
}

.path-explain {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-top: 8px;
}

.path-title {
  font-size: 13px;
  font-weight: 700;
  color: #3b82f6;
  margin-bottom: 4px;
}

.path-summary {
  font-size: 13px;
  color: var(--text);
  background: linear-gradient(135deg, rgba(59,130,246,0.06), rgba(124,58,237,0.06));
  padding: 8px 12px;
  border-radius: 6px;
  border-left: 3px solid #3b82f6;
  margin-bottom: 8px;
  line-height: 1.5;
}

.summary-label {
  font-weight: 700;
  color: #3b82f6;
  margin-right: 4px;
}

.summary-seg {
  font-family: monospace;
  font-weight: 600;
  transition: all 0.15s;
}

.summary-link {
  cursor: pointer;
  border-bottom: 1px dashed transparent;
}

.summary-link:hover,
.summary-active {
  color: #d97706;
  border-bottom-color: #d97706;
  background: rgba(245,158,11,0.08);
  border-radius: 2px;
}

.path-desc {
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 8px;
}

.path-steps {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.path-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 4px;
  background: rgba(59,130,246,0.04);
}

.path-step.path-causal {
  background: rgba(124,58,237,0.06);
  border-left: 2px solid #7c3aed;
}

.path-step.path-unlock {
  background: rgba(251,113,133,0.06);
  border-left: 2px solid #fb7185;
}

.path-num {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
  min-width: 16px;
}

.path-text {
  color: var(--text-dim);
  font-family: monospace;
  font-size: 10px;
  flex: 1;
}

.path-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
}

.path-badge.causal {
  background: rgba(124,58,237,0.1);
  color: #7c3aed;
}

.path-badge.unlock {
  background: rgba(251,113,133,0.1);
  color: #e11d48;
}
</style>
