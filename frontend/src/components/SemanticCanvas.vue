<script setup lang="ts">
import { ref, computed, onMounted, watch, onUnmounted, nextTick } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { getIdentity } from '../api/analysis'

const store = useAnalysisStore()

// ── State ──
const loading = ref(false)
const error = ref('')
const identities = ref<any>(null)
const normalForm = ref<any>(null)
const fingerprint = ref<any>(null)
const ontology = ref<any>(null)

const activeLayer = ref<'syntax' | 'runtime' | 'semantic' | 'algorithm'>('semantic')
const selectedNode = ref<string | null>(null)
const animStep = ref(0)
const animPlaying = ref(false)
const animSpeed = ref(400)
let animTimer: ReturnType<typeof setInterval> | null = null

// Semantic zoom level: 0=algorithm, 1=structure, 2=variables, 3=runtime
const zoomLevel = ref(2)
const ZOOM_LABELS = ['Algorithm', 'Structure', 'Variables', 'Runtime']

// Canvas transform for pan/zoom
const canvasScale = ref(1)
const canvasOffsetX = ref(0)
const canvasOffsetY = ref(0)
let isDragging = false
let dragStartX = 0
let dragStartY = 0

// ── Archetype Visual Config ──
const ARCHETYPE_VISUALS: Record<string, { shape: string; color: string; icon: string; label: string }> = {
  loop_counter:          { shape: 'circle',    color: '#3b82f6', icon: '↻',  label: 'Loop Counter' },
  accumulator:           { shape: 'diamond',   color: '#10b981', icon: '∑',  label: 'Accumulator' },
  memo_table:            { shape: 'grid',      color: '#8b5cf6', icon: '▦',  label: 'Memo Table' },
  state_transition:      { shape: 'arrow',     color: '#f59e0b', icon: '→',  label: 'State Transition' },
  boundary_condition:    { shape: 'hexagon',   color: '#ef4444', icon: '◇',  label: 'Boundary' },
  visited_set:           { shape: 'circle',    color: '#06b6d4', icon: '◉',  label: 'Visited Set' },
  dedup_guard:           { shape: 'shield',    color: '#84cc16', icon: '⊘',  label: 'Dedup Guard' },
  early_termination:     { shape: 'stop',      color: '#dc2626', icon: '■',  label: 'Early Exit' },
  convergence_check:     { shape: 'target',    color: '#7c3aed', icon: '◎',  label: 'Convergence' },
  stack_dfs:             { shape: 'stack',     color: '#6366f1', icon: '⌋',  label: 'DFS Stack' },
  queue_bfs:             { shape: 'queue',     color: '#0891b2', icon: '⇉',  label: 'BFS Queue' },
  heap_priority:         { shape: 'triangle',  color: '#d97706', icon: '△',  label: 'Heap' },
  hash_lookup:           { shape: 'bolt',      color: '#2563eb', icon: '⚡', label: 'Hash Lookup' },
  dynamic_programming:   { shape: 'layers',    color: '#7c3aed', icon: '≡',  label: 'DP' },
  greedy_selection:      { shape: 'arrow',     color: '#059669', icon: '▷',  label: 'Greedy' },
  sliding_window:        { shape: 'window',    color: '#0284c7', icon: '⊟',  label: 'Sliding Window' },
  parallel_state_transition: { shape: 'parallel', color: '#ea580c', icon: '⇄', label: 'Parallel Swap' },
  monotonic_accumulator: { shape: 'ramp',      color: '#16a34a', icon: '↗',  label: 'Mono Accum' },
  dict_state_write:      { shape: 'grid',      color: '#9333ea', icon: '✎',  label: 'Dict Write' },
}

const DEFAULT_VISUAL = { shape: 'circle', color: '#6b7280', icon: '?', label: 'Unknown' }

function getVisual(canonicalId: string) {
  return ARCHETYPE_VISUALS[canonicalId] || DEFAULT_VISUAL
}

// ── Force-Directed Layout ──
interface ForceNode {
  id: string
  x: number
  y: number
  vx: number
  vy: number
  fx: number | null
  fy: number | null
  radius: number
  canonicalId: string
  subjects: string[]
  confidence: number
  category: string
  visual: typeof DEFAULT_VISUAL
  invariants: string[]
  behaviors: string[]
}

interface ForceEdge {
  source: string
  target: string
  type: string
}

const nodes = ref<ForceNode[]>([])
const edges = ref<ForceEdge[]>([])
let simRunning = false
let simFrame = 0

function initForceLayout() {
  if (!normalForm.value?.canonical_identities) return
  const items = normalForm.value.canonical_identities
  const cx = 400, cy = 300

  nodes.value = items.map((ci: any, i: number) => {
    const angle = (2 * Math.PI * i) / items.length - Math.PI / 2
    const r = 120 + Math.random() * 60
    return {
      id: ci.canonical_id,
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
      vx: 0, vy: 0,
      fx: null, fy: null,
      radius: 28 + (ci.confidence || 0) * 12,
      canonicalId: ci.canonical_id,
      subjects: ci.subjects || [],
      confidence: ci.confidence || 0,
      category: ci.category || 'unknown',
      visual: getVisual(ci.canonical_id),
      invariants: ci.invariants || [],
      behaviors: ci.behaviors || [],
    }
  })

  edges.value = (identities.value?.relationships || []).map((r: any) => ({
    source: r.from, target: r.to, type: r.type,
  }))

  // Run force simulation
  runForceSimulation()
}

function runForceSimulation() {
  if (simRunning) return
  simRunning = true
  simFrame = 0
  requestAnimationFrame(simStep)
}

function simStep() {
  if (simFrame > 120) { simRunning = false; return }
  simFrame++

  const alpha = 1 - simFrame / 120
  const nodeMap = new Map(nodes.value.map(n => [n.id, n]))

  // Repulsion between all nodes
  for (let i = 0; i < nodes.value.length; i++) {
    for (let j = i + 1; j < nodes.value.length; j++) {
      const a = nodes.value[i], b = nodes.value[j]
      let dx = b.x - a.x, dy = b.y - a.y
      let dist = Math.sqrt(dx * dx + dy * dy) || 1
      let force = (800 * alpha) / dist
      let fx = (dx / dist) * force, fy = (dy / dist) * force
      if (!a.fx) { a.vx -= fx; a.vy -= fy }
      if (!b.fx) { b.vx += fx; b.vy += fy }
    }
  }

  // Attraction along edges
  for (const e of edges.value) {
    const a = nodeMap.get(e.source), b = nodeMap.get(e.target)
    if (!a || !b) continue
    let dx = b.x - a.x, dy = b.y - a.y
    let dist = Math.sqrt(dx * dx + dy * dy) || 1
    let force = (dist - 150) * 0.02 * alpha
    let fx = (dx / dist) * force, fy = (dy / dist) * force
    if (!a.fx) { a.vx += fx; a.vy += fy }
    if (!b.fx) { b.vx -= fx; b.vy -= fy }
  }

  // Center gravity
  for (const n of nodes.value) {
    if (n.fx) { n.x = n.fx; n.vx = 0 } else { n.vx += (400 - n.x) * 0.002 * alpha }
    if (n.fy) { n.y = n.fy; n.vy = 0 } else { n.vy += (300 - n.y) * 0.002 * alpha }
    n.vx *= 0.85; n.vy *= 0.85
    n.x += n.vx; n.y += n.vy
    // Bounds
    n.x = Math.max(40, Math.min(760, n.x))
    n.y = Math.max(40, Math.min(560, n.y))
  }

  requestAnimationFrame(simStep)
}

// ── Drag handling ──
function onNodeDragStart(e: MouseEvent, nodeId: string) {
  const node = nodes.value.find(n => n.id === nodeId)
  if (!node) return
  node.fx = node.x
  node.fy = node.y
  isDragging = true
  selectedNode.value = nodeId
  e.preventDefault()
}

function onCanvasMouseMove(e: MouseEvent) {
  if (!isDragging || !selectedNode.value) return
  const node = nodes.value.find(n => n.id === selectedNode.value)
  if (!node || node.fx === null) return
  const svg = (e.target as SVGElement).closest('svg')
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  node.fx = ((e.clientX - rect.left) / rect.width) * 800
  node.fy = ((e.clientY - rect.top) / rect.height) * 600
  node.x = node.fx
  node.y = node.fy
}

function onCanvasMouseUp() {
  if (selectedNode.value) {
    const node = nodes.value.find(n => n.id === selectedNode.value)
    if (node) { node.fx = null; node.fy = null }
  }
  isDragging = false
}

// ── Canvas pan/zoom ──
function onCanvasWheel(e: WheelEvent) {
  e.preventDefault()
  const delta = e.deltaY > 0 ? 0.9 : 1.1
  canvasScale.value = Math.max(0.3, Math.min(3, canvasScale.value * delta))
}

// ── Semantic Zoom ──
const visibleNodes = computed(() => {
  const level = zoomLevel.value
  return nodes.value.filter(n => {
    if (level === 0) return n.category === 'algorithm'
    if (level === 1) return n.category === 'algorithm' || n.category === 'structure' || n.category === 'control'
    return true // level 2+: show all
  })
})

const visibleEdges = computed(() => {
  const ids = new Set(visibleNodes.value.map(n => n.id))
  return edges.value.filter(e => ids.has(e.source) && ids.has(e.target))
})

// ── Animation data ──
const animVars = computed(() => {
  const tl = store.timeline
  if (!tl || !tl.length) return {}
  return tl[Math.min(animStep.value, tl.length - 1)]?.vars || {}
})

const animChanged = computed(() => {
  const tl = store.timeline
  if (!tl || !tl.length) return []
  return tl[Math.min(animStep.value, tl.length - 1)]?.changed || []
})

const animCode = computed(() => {
  const tl = store.timeline
  if (!tl || !tl.length) return ''
  return tl[Math.min(animStep.value, tl.length - 1)]?.code || ''
})

// ── Layer data ──
const syntaxNodes = computed(() => {
  const tl = store.timeline
  if (!tl) return []
  const byLine = new Map<number, number[]>()
  tl.forEach((s: any, i: number) => {
    const line = s.line || 0
    if (!byLine.has(line)) byLine.set(line, [])
    byLine.get(line)!.push(i)
  })
  return Array.from(byLine.entries()).map(([line, steps]) => ({
    line, steps, code: tl[steps[0]]?.code || '',
  }))
})

// ── Animation ──
function toggleAnim() { animPlaying.value ? stopAnim() : startAnim() }
function startAnim() {
  animPlaying.value = true
  animTimer = setInterval(() => {
    const tl = store.timeline
    if (!tl || !tl.length) { stopAnim(); return }
    animStep.value = (animStep.value + 1) % tl.length
  }, animSpeed.value)
}
function stopAnim() { animPlaying.value = false; if (animTimer) { clearInterval(animTimer); animTimer = null } }
function resetAnim() { stopAnim(); animStep.value = 0 }

onUnmounted(() => stopAnim())

// ── Data Loading ──
async function loadIdentityData() {
  if (!store.code.trim()) return
  loading.value = true; error.value = ''
  try {
    const res = await getIdentity(store.code, store.funcName, store.language)
    if (res.success) {
      identities.value = (res as any).identities || null
      normalForm.value = (res as any).normal_form || null
      fingerprint.value = (res as any).fingerprint || null
      ontology.value = (res as any).ontology || null
      await nextTick()
      initForceLayout()
    } else { error.value = res.error || 'Failed to load identity' }
  } catch (e: any) { error.value = e.message }
  finally { loading.value = false }
}

onMounted(loadIdentityData)
watch(() => store.hasResults, (has) => { if (has) loadIdentityData() })
</script>

<template>
  <div class="semantic-canvas">
    <!-- Toolbar -->
    <div class="canvas-toolbar">
      <div class="layer-toggle">
        <button v-for="layer in (['syntax', 'runtime', 'semantic', 'algorithm'] as const)" :key="layer"
          :class="['layer-btn', { active: activeLayer === layer }]" @click="activeLayer = layer">
          {{ layer === 'syntax' ? 'Syntax' : layer === 'runtime' ? 'Runtime' : layer === 'semantic' ? 'Semantic' : 'Algorithm' }}
        </button>
      </div>

      <!-- Zoom controls -->
      <div class="zoom-controls" v-if="activeLayer === 'semantic'">
        <button class="zoom-btn" @click="zoomLevel = Math.max(0, zoomLevel - 1)">-</button>
        <span class="zoom-label">{{ ZOOM_LABELS[zoomLevel] }}</span>
        <button class="zoom-btn" @click="zoomLevel = Math.min(3, zoomLevel + 1)">+</button>
      </div>

      <!-- Playback controls -->
      <div class="playback" v-if="store.timeline?.length && (activeLayer === 'runtime' || activeLayer === 'semantic')">
        <button class="pb-btn" @click="resetAnim" title="Reset">⏮</button>
        <button class="pb-btn" @click="toggleAnim" :title="animPlaying ? 'Pause' : 'Play'">
          {{ animPlaying ? '⏸' : '▶' }}
        </button>
        <span class="pb-step">{{ animStep + 1 }} / {{ store.timeline.length }}</span>
        <input type="range" v-model.number="animStep" :min="0" :max="store.timeline.length - 1" class="pb-slider" />
        <select v-model.number="animSpeed" class="pb-speed">
          <option :value="800">0.5x</option>
          <option :value="400">1x</option>
          <option :value="200">2x</option>
          <option :value="100">4x</option>
        </select>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="canvas-loading">
      <div class="spinner"></div>
      <span>Analyzing semantic identity...</span>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="canvas-error">{{ error }}</div>

    <!-- Empty -->
    <div v-else-if="!store.hasResults" class="canvas-empty">
      <div class="empty-icon">◈</div>
      <p>Run analysis to see the semantic canvas</p>
    </div>

    <!-- Canvas Content -->
    <div v-else class="canvas-content">
      <!-- SEMANTIC LAYER -->
      <div v-if="activeLayer === 'semantic'" class="canvas-svg-wrap">
        <svg viewBox="0 0 800 600" class="canvas-svg"
          @mousemove="onCanvasMouseMove" @mouseup="onCanvasMouseUp" @mouseleave="onCanvasMouseUp"
          @wheel.prevent="onCanvasWheel">
          <g :transform="`translate(${canvasOffsetX}, ${canvasOffsetY}) scale(${canvasScale})`">
            <!-- Animated edges -->
            <line v-for="edge in visibleEdges" :key="`${edge.source}-${edge.target}`"
              :x1="nodes.find(n => n.id === edge.source)?.x || 0"
              :y1="nodes.find(n => n.id === edge.source)?.y || 0"
              :x2="nodes.find(n => n.id === edge.target)?.x || 0"
              :y2="nodes.find(n => n.id === edge.target)?.y || 0"
              stroke="#64748b" stroke-width="2.2" stroke-dasharray="5,4" class="animated-edge" />

            <!-- Edge labels -->
            <text v-for="edge in visibleEdges" :key="`label-${edge.source}-${edge.target}`"
              :x="((nodes.find(n => n.id === edge.source)?.x || 0) + (nodes.find(n => n.id === edge.target)?.x || 0)) / 2"
              :y="((nodes.find(n => n.id === edge.source)?.y || 0) + (nodes.find(n => n.id === edge.target)?.y || 0)) / 2 - 6"
              text-anchor="middle" font-size="11" font-weight="700" fill="#334155" stroke="#ffffff" stroke-width="3" paint-order="stroke">{{ edge.type }}</text>

            <!-- Nodes -->
            <g v-for="node in visibleNodes" :key="node.id"
              :transform="`translate(${node.x}, ${node.y})`"
              :class="['canvas-node', { selected: selectedNode === node.id }]"
              @mousedown="(e) => onNodeDragStart(e, node.id)"
              style="cursor: grab">
              <!-- Shape -->
              <circle v-if="node.visual.shape === 'circle'" :r="node.radius"
                :fill="node.visual.color + '2e'" :stroke="node.visual.color" stroke-width="2.6" />
              <rect v-else-if="node.visual.shape === 'grid'"
                :x="-node.radius" :y="-node.radius" :width="node.radius * 2" :height="node.radius * 2" rx="6"
                :fill="node.visual.color + '2e'" :stroke="node.visual.color" stroke-width="2.6" />
              <polygon v-else-if="node.visual.shape === 'diamond'"
                :points="`0,${-node.radius} ${node.radius},0 0,${node.radius} ${-node.radius},0`"
                :fill="node.visual.color + '2e'" :stroke="node.visual.color" stroke-width="2.6" />
              <polygon v-else-if="node.visual.shape === 'hexagon'"
                :points="`${node.radius*0.87},${-node.radius*0.5} ${node.radius*0.87},${node.radius*0.5} 0,${node.radius} ${-node.radius*0.87},${node.radius*0.5} ${-node.radius*0.87},${-node.radius*0.5} 0,${-node.radius}`"
                :fill="node.visual.color + '2e'" :stroke="node.visual.color" stroke-width="2.6" />
              <polygon v-else-if="node.visual.shape === 'triangle'"
                :points="`0,${-node.radius} ${node.radius*0.87},${node.radius*0.5} ${-node.radius*0.87},${node.radius*0.5}`"
                :fill="node.visual.color + '2e'" :stroke="node.visual.color" stroke-width="2.6" />
              <rect v-else
                :x="-node.radius + 2" :y="-node.radius * 0.75" :width="(node.radius - 2) * 2" :height="node.radius * 1.5" rx="8"
                :fill="node.visual.color + '2e'" :stroke="node.visual.color" stroke-width="2.6" />

              <!-- Icon -->
              <text text-anchor="middle" dy="4" font-size="20" :fill="node.visual.color" font-weight="800">
                {{ node.visual.icon }}
              </text>

              <!-- Label -->
              <text text-anchor="middle" :dy="node.radius + 18" font-size="12" font-weight="800" fill="#0f172a" stroke="#ffffff" stroke-width="3" paint-order="stroke">
                {{ node.visual.label }}
              </text>

              <!-- Confidence bar -->
              <rect :x="-22" :y="node.radius + 4" :width="44 * node.confidence" height="4" rx="2" :fill="node.visual.color" opacity="0.95" />
              <rect :x="-22" :y="node.radius + 4" width="44" height="4" rx="2" fill="none" stroke="#94a3b8" stroke-width="0.8" />

              <!-- Subjects (zoom level 2+) -->
              <template v-if="zoomLevel >= 2">
                <text v-for="(subj, si) in node.subjects.slice(0, 3)" :key="subj"
                  text-anchor="middle" :dy="node.radius + 31 + si * 13"
                  font-size="10" font-weight="700" font-family="monospace" :fill="node.visual.color" stroke="#ffffff" stroke-width="2" paint-order="stroke">{{ subj }}</text>
              </template>
            </g>

            <!-- Execution pulse -->
            <circle v-if="animPlaying && visibleNodes.length"
              :cx="visibleNodes[animStep % visibleNodes.length]?.x || 0"
              :cy="visibleNodes[animStep % visibleNodes.length]?.y || 0"
              r="34" fill="none"
              :stroke="visibleNodes[animStep % visibleNodes.length]?.visual.color || '#888'"
              stroke-width="2" opacity="0.4" class="pulse-ring" />
          </g>
        </svg>

        <!-- Node detail panel -->
        <div v-if="selectedNode" class="node-detail">
          <div class="detail-header" :style="{ borderLeftColor: getVisual(selectedNode).color }">
            <span class="detail-icon" :style="{ background: getVisual(selectedNode).color }">
              {{ getVisual(selectedNode).icon }}
            </span>
            <div>
              <div class="detail-label">{{ getVisual(selectedNode).label }}</div>
              <div class="detail-id">{{ selectedNode }}</div>
            </div>
          </div>
          <div class="detail-section" v-if="nodes.find(n => n.id === selectedNode)?.subjects.length">
            <div class="detail-title">Variables</div>
            <span v-for="s in nodes.find(n => n.id === selectedNode)?.subjects" :key="s" class="var-chip">{{ s }}</span>
          </div>
          <div class="detail-section" v-if="nodes.find(n => n.id === selectedNode)?.invariants.length">
            <div class="detail-title">Invariants</div>
            <div v-for="inv in nodes.find(n => n.id === selectedNode)?.invariants" :key="inv" class="inv-line">{{ inv }}</div>
          </div>
          <div class="detail-section" v-if="nodes.find(n => n.id === selectedNode)?.behaviors.length">
            <div class="detail-title">Behaviors</div>
            <div v-for="b in nodes.find(n => n.id === selectedNode)?.behaviors" :key="b" class="beh-line">{{ b }}</div>
          </div>
        </div>
      </div>

      <!-- ALGORITHM LAYER -->
      <div v-else-if="activeLayer === 'algorithm'" class="algo-layer">
        <div v-if="fingerprint" class="algo-content">
          <div class="algo-header">
            <div class="algo-hash">{{ fingerprint.hash }}</div>
            <div class="algo-name">{{ fingerprint.algorithm }}</div>
            <div class="algo-conf">{{ (fingerprint.algorithm_confidence * 100).toFixed(0) }}% confidence</div>
          </div>
          <div class="algo-structures">
            <h4>Data Structures</h4>
            <div class="struct-chips">
              <span v-for="s in fingerprint.structures" :key="s" class="struct-chip" :style="{ borderColor: getVisual(s).color, color: getVisual(s).color }">
                {{ getVisual(s).icon }} {{ s }}
              </span>
              <span v-if="!fingerprint.structures?.length" class="empty-hint">none detected</span>
            </div>
          </div>
          <div class="algo-control">
            <h4>Control Flow</h4>
            <div class="struct-chips">
              <span v-for="c in fingerprint.control" :key="c" class="struct-chip" :style="{ borderColor: getVisual(c).color, color: getVisual(c).color }">
                {{ getVisual(c).icon }} {{ c }}
              </span>
              <span v-if="!fingerprint.control?.length" class="empty-hint">none detected</span>
            </div>
          </div>
          <div class="algo-complexity">
            <h4>Complexity Shape</h4>
            <div class="complexity-badge">{{ fingerprint.complexity }}</div>
          </div>
          <div class="algo-invariants" v-if="fingerprint.invariant_set?.length">
            <h4>Invariant Set</h4>
            <div class="inv-badges">
              <span v-for="inv in fingerprint.invariant_set" :key="inv" class="inv-badge">{{ inv }}</span>
            </div>
          </div>
        </div>
        <div v-else class="canvas-empty"><p>No algorithm identity available</p></div>
      </div>

      <!-- RUNTIME LAYER -->
      <div v-else-if="activeLayer === 'runtime'" class="runtime-layer">
        <div class="runtime-header">
          <div class="rt-code-line">{{ animCode }}</div>
          <div class="rt-step-badge">Step {{ animStep + 1 }}</div>
        </div>
        <div class="runtime-vars">
          <div v-for="(info, name) in animVars" :key="name"
            :class="['rt-var-card', { changed: animChanged.includes(name) }]">
            <div class="rt-var-name">{{ name }}</div>
            <div class="rt-var-val">{{ typeof info === 'object' ? (info.value ?? JSON.stringify(info)) : info }}</div>
            <div class="rt-var-type" v-if="typeof info === 'object' && info.type">{{ info.type }}</div>
          </div>
        </div>
        <div class="runtime-timeline">
          <div v-for="(step, i) in store.timeline" :key="i"
            :class="['rt-tick', { active: i === animStep, changed: step.changed?.length }]"
            :style="{ left: `${(Number(i) / Math.max(store.timeline.length - 1, 1)) * 100}%` }"
            @click="animStep = Number(i)"></div>
        </div>
      </div>

      <!-- SYNTAX LAYER -->
      <div v-else-if="activeLayer === 'syntax'" class="syntax-layer">
        <div v-for="group in syntaxNodes" :key="group.line"
          :class="['syn-line', { active: store.highlightedLine === group.line }]">
          <span class="syn-line-no">{{ group.line }}</span>
          <span class="syn-code">{{ group.code }}</span>
          <span class="syn-hits">{{ group.steps.length }}x</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.semantic-canvas {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  font-size: 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: var(--shadow);
}

/* ── Toolbar ── */
.canvas-toolbar { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-bottom: 1px solid var(--border, #e5e7eb); flex-shrink: 0; background: var(--bg-card); overflow-x: auto; }
.layer-toggle { display: flex; gap: 0; border: 1px solid var(--border, #e5e7eb); border-radius: 6px; overflow: hidden; }
.layer-btn { padding: 7px 14px; font-size: 14px; font-weight: 700; border: none; background: white; cursor: pointer; color: var(--text-dim, #888); transition: all 0.15s; white-space: nowrap; }
.layer-btn:not(:last-child) { border-right: 1px solid var(--border, #e5e7eb); }
.layer-btn:hover { background: #f9fafb; color: var(--text, #333); }
.layer-btn.active { background: var(--primary, #4f46e5); color: white; }

.zoom-controls { display: flex; align-items: center; gap: 6px; margin-left: 8px; }
.zoom-btn { width: 28px; height: 28px; border: 1px solid var(--border, #e5e7eb); border-radius: 4px; background: white; cursor: pointer; font-size: 16px; font-weight: 800; display: flex; align-items: center; justify-content: center; }
.zoom-btn:hover { background: #f3f4f6; }
.zoom-label { font-size: 14px; font-weight: 700; color: var(--text, #333); min-width: 76px; text-align: center; }

.playback { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.pb-btn { width: 30px; height: 30px; border: 1px solid var(--border, #e5e7eb); border-radius: 4px; background: white; cursor: pointer; font-size: 14px; display: flex; align-items: center; justify-content: center; }
.pb-btn:hover { background: #f3f4f6; }
.pb-step { font-family: monospace; font-size: 14px; font-weight: 700; color: var(--text, #333); min-width: 60px; }
.pb-slider { width: 120px; accent-color: var(--primary, #4f46e5); }
.pb-speed { font-size: 14px; padding: 4px 6px; border: 1px solid var(--border, #e5e7eb); border-radius: 4px; background: white; color: var(--text); }

/* ── States ── */
.canvas-loading, .canvas-error, .canvas-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 48px; color: var(--text-dim, #888); gap: 8px; }
.spinner { width: 24px; height: 24px; border: 2px solid var(--border, #ddd); border-top-color: var(--primary, #4f46e5); border-radius: 50%; animation: spin 0.7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.canvas-error { color: #dc2626; }
.empty-icon { font-size: 36px; opacity: 0.3; }

/* ── Canvas ── */
.canvas-content { flex: 1; overflow: auto; position: relative; background: #f8fafc; }
.canvas-svg-wrap { position: relative; min-height: 560px; }
.canvas-svg { width: 100%; height: 560px; background: #f8fafc; }
.canvas-node { transition: filter 0.15s; }
.canvas-node:hover { filter: brightness(1.08) drop-shadow(0 3px 7px rgba(15,23,42,0.18)); }
.canvas-node.selected { filter: drop-shadow(0 0 10px rgba(37,99,235,0.55)); }

.animated-edge { stroke-dashoffset: 0; animation: dash-flow 2s linear infinite; }
@keyframes dash-flow { to { stroke-dashoffset: -16; } }

.pulse-ring { animation: pulse 1.2s ease-out infinite; }
@keyframes pulse { 0% { r: 34; opacity: 0.4; } 100% { r: 50; opacity: 0; } }

/* ── Node Detail ── */
.node-detail { position: absolute; top: 12px; right: 12px; width: 280px; background: white; border: 1px solid var(--border-strong, #94a3b8); border-radius: 8px; padding: 12px; box-shadow: 0 12px 28px rgba(15,23,42,0.16); font-size: 14px; }
.detail-header { display: flex; align-items: center; gap: 8px; padding-bottom: 8px; border-left: 3px solid #888; padding-left: 8px; margin-bottom: 8px; }
.detail-icon { width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; border-radius: 6px; color: white; font-size: 14px; }
.detail-label { font-weight: 700; font-size: 14px; }
.detail-id { font-family: monospace; font-size: 14px; color: var(--text-muted, #475569); word-break: break-all; }
.detail-section { margin-top: 8px; }
.detail-title { font-size: 14px; font-weight: 800; color: var(--text-dim, #334155); text-transform: uppercase; margin-bottom: 4px; }
.var-chip { display: inline-block; font-family: monospace; font-size: 14px; padding: 2px 7px; background: rgba(59,130,246,0.12); color: #1d4ed8; border: 1px solid rgba(59,130,246,0.22); border-radius: 4px; margin: 2px 4px 2px 0; }
.inv-line, .beh-line { font-size: 14px; padding: 2px 0; color: var(--text, #333); }

/* ── Algorithm Layer ── */
.algo-layer { padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.algo-content { display: flex; flex-direction: column; gap: 16px; }
.algo-header { text-align: center; padding: 16px; background: linear-gradient(135deg, rgba(139,92,246,0.05), rgba(59,130,246,0.05)); border: 1px solid var(--border, #e5e7eb); border-radius: 8px; }
.algo-hash { font-family: monospace; font-size: 20px; font-weight: 800; color: #8b5cf6; letter-spacing: 2px; }
.algo-name { font-size: 16px; font-weight: 700; margin-top: 4px; }
.algo-conf { font-size: 14px; color: var(--text-dim, #888); }
.algo-structures h4, .algo-control h4, .algo-complexity h4, .algo-invariants h4 { font-size: 14px; font-weight: 700; margin: 0 0 6px; color: var(--text-dim, #888); }
.struct-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.struct-chip { font-size: 14px; padding: 3px 10px; border: 1px solid; border-radius: 20px; font-weight: 600; }
.complexity-badge { display: inline-block; font-family: monospace; font-size: 14px; font-weight: 700; padding: 4px 14px; background: rgba(245,158,11,0.08); color: #d97706; border-radius: 6px; }
.inv-badges { display: flex; flex-wrap: wrap; gap: 4px; }
.inv-badge { font-size: 14px; padding: 2px 8px; background: rgba(16,185,129,0.08); color: #059669; border-radius: 4px; font-weight: 600; }
.empty-hint { font-size: 14px; color: var(--text-dim, #9ca3af); font-style: italic; }

/* ── Runtime Layer ── */
.runtime-layer { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.runtime-header { display: flex; align-items: center; gap: 12px; }
.rt-code-line { flex: 1; font-family: monospace; font-size: 14px; padding: 8px 12px; background: #1e1e1e; color: #d4d4d4; border-radius: 6px; }
.rt-step-badge { font-size: 14px; font-weight: 700; padding: 4px 10px; background: rgba(99,102,241,0.1); color: #6366f1; border-radius: 4px; }
.runtime-vars { display: flex; flex-wrap: wrap; gap: 8px; }
.rt-var-card { padding: 8px 12px; border: 1px solid var(--border, #e5e7eb); border-radius: 6px; min-width: 80px; transition: all 0.2s; }
.rt-var-card.changed { border-color: #f59e0b; background: rgba(245,158,11,0.04); box-shadow: 0 0 0 2px rgba(245,158,11,0.15); }
.rt-var-name { font-family: monospace; font-size: 14px; font-weight: 700; color: #3b82f6; }
.rt-var-val { font-family: monospace; font-size: 14px; font-weight: 600; margin-top: 2px; }
.rt-var-type { font-size: 14px; color: var(--text-dim, #888); }
.runtime-timeline { position: relative; height: 20px; background: rgba(0,0,0,0.03); border-radius: 10px; margin-top: 8px; }
.rt-tick { position: absolute; top: 50%; transform: translate(-50%, -50%); width: 6px; height: 6px; border-radius: 50%; background: #d1d5db; cursor: pointer; transition: all 0.15s; }
.rt-tick:hover { transform: translate(-50%, -50%) scale(1.5); }
.rt-tick.active { background: #6366f1; width: 10px; height: 10px; }
.rt-tick.changed { background: #f59e0b; }

/* ── Syntax Layer ── */
.syntax-layer { padding: 12px; font-family: monospace; font-size: 14px; }
.syn-line { display: flex; align-items: center; gap: 8px; padding: 3px 8px; border-radius: 4px; transition: background 0.15s; }
.syn-line:hover { background: rgba(0,0,0,0.02); }
.syn-line.active { background: rgba(99,102,241,0.08); }
.syn-line-no { width: 32px; text-align: right; color: var(--text-dim, #9ca3af); font-size: 14px; }
.syn-code { flex: 1; }
.syn-hits { font-size: 14px; padding: 1px 6px; background: rgba(0,0,0,0.04); border-radius: 3px; color: var(--text-dim, #888); }
</style>
