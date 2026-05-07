<script setup lang="ts">
import { computed, ref, watch, onUnmounted, nextTick } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()
const canvasRef = ref<HTMLElement>()
const dsStep = ref(0)
const selectedObj = ref<number | null>(null)

const steps = computed(() => {
  const dsv = store.dsVizTimeline
  if (dsv && dsv.length > 0) return dsv
  return []
})
const totalSteps = computed(() => steps.value?.length || 0)
const currentData = computed(() => steps.value[dsStep.value] || null)

// Highlight current line in code editor (debugger-style)
watch(currentData, (d) => {
  if (d && store.activeTab === 'dsviz') {
    store.highlightedLine = d.line || 0
  }
})

// Auto-play state
const isPlaying = ref(true)
const isInternal = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

// Auto-play when data arrives OR user switches to this tab
watch([totalSteps, () => store.activeTab], ([n, tab]) => {
  if (n > 0 && tab === 'dsviz' && isPlaying.value) startAutoPlay()
}, { immediate: true })

function startAutoPlay() {
  stopAutoPlay()
  timer = setInterval(() => {
    if (!isPlaying.value) return
    if (dsStep.value >= totalSteps.value - 1) {
      dsStep.value = 0
    } else {
      dsStep.value++
    }
    isInternal.value = true
    store.currentStep = dsStep.value
    nextTick(() => { isInternal.value = false })
  }, 800)
}

function stopAutoPlay() {
  if (timer) { clearInterval(timer); timer = null }
}

// Manual step change → stop auto-play
function onManualStep() {
  isPlaying.value = false
  stopAutoPlay()
  isInternal.value = true
  store.currentStep = dsStep.value
  nextTick(() => { isInternal.value = false })
}

function prevDsStep() { dsStep.value = Math.max(0, dsStep.value - 1); onManualStep() }
function nextDsStep() { dsStep.value = Math.min(totalSteps.value - 1, dsStep.value + 1); onManualStep() }

// Canvas click → toggle play/pause
function onCanvasClick() {
  isPlaying.value = !isPlaying.value
  if (isPlaying.value) startAutoPlay()
  else stopAutoPlay()
}

// Sync from store (when user changes step in Timeline/Graph)
watch(() => store.currentStep, (s) => {
  if (isInternal.value) return
  if (store.activeTab === 'dsviz' && s < totalSteps.value && s !== dsStep.value) {
    dsStep.value = s
  }
})

// Slider change → stop + sync
function onSliderInput(e: Event) {
  dsStep.value = Number((e.target as HTMLInputElement).value)
  onManualStep()
}

onUnmounted(() => stopAutoPlay())

// Variable diff
function tryParse(raw: string): any {
  if (!raw || typeof raw !== 'string') return null
  if (raw.startsWith('[') || raw.startsWith('{')) {
    try { return JSON.parse(raw) } catch {}
  }
  if (raw.startsWith("{'") || raw.startsWith('{"')) {
    try { return JSON.parse(raw.replace(/'/g, '"')) } catch {}
  }
  return null
}

const varDiff = computed(() => {
  const timeline = store.timeline
  const idx = dsStep.value
  const curr = timeline[idx]
  const prev = idx > 0 ? timeline[idx - 1] : null
  if (!curr) return { added: [] as string[], modified: [] as string[], removed: [] as string[], details: {} as Record<string, string> }

  const currVars = curr.vars || {}
  const prevVars = prev?.vars || {}
  const added: string[] = []
  const modified: string[] = []
  const removed: string[] = []
  const details: Record<string, string> = {}

  for (const name of Object.keys(currVars)) {
    if (!(name in prevVars)) {
      added.push(name)
    } else if (currVars[name].value !== prevVars[name].value) {
      modified.push(name)
      const prevParsed = tryParse(prevVars[name].value)
      const currParsed = tryParse(currVars[name].value)

      if (Array.isArray(prevParsed) && Array.isArray(currParsed)) {
        const lenDiff = currParsed.length - prevParsed.length
        const changedIdx: number[] = []
        for (let i = 0; i < Math.min(prevParsed.length, currParsed.length); i++) {
          if (JSON.stringify(prevParsed[i]) !== JSON.stringify(currParsed[i])) changedIdx.push(i)
        }
        const parts: string[] = []
        if (lenDiff > 0) parts.push(`+${lenDiff} at end`)
        if (lenDiff < 0) parts.push(`${lenDiff} removed`)
        if (changedIdx.length) parts.push(`changed [${changedIdx.join(',')}]`)
        details[name] = parts.join(', ') || 'modified'
      } else if (prevParsed && currParsed && typeof prevParsed === 'object' && typeof currParsed === 'object' && !Array.isArray(prevParsed)) {
        const prevKeys = new Set(Object.keys(prevParsed))
        const currKeys = new Set(Object.keys(currParsed))
        const addedKeys = [...currKeys].filter(k => !prevKeys.has(k))
        const removedKeys = [...prevKeys].filter(k => !currKeys.has(k))
        const changedKeys = [...currKeys].filter(k => prevKeys.has(k) && JSON.stringify(prevParsed[k]) !== JSON.stringify(currParsed[k]))
        const parts: string[] = []
        if (addedKeys.length) parts.push(`+${addedKeys.join(',')}`)
        if (removedKeys.length) parts.push(`-${removedKeys.join(',')}`)
        if (changedKeys.length) parts.push(`~${changedKeys.join(',')}`)
        details[name] = parts.join(', ') || 'modified'
      } else {
        details[name] = `${String(prevVars[name].value).slice(0, 15)} → ${String(currVars[name].value).slice(0, 15)}`
      }
    }
  }
  for (const name of Object.keys(prevVars)) {
    if (!(name in currVars)) removed.push(name)
  }
  return { added, modified, removed, details }
})

// Force-directed layout
interface LayoutNode {
  id: number; x: number; y: number; vx: number; vy: number
  type: string; val: string; fullVal: string; attrs: Record<string, string>
  refs: Record<string, number>; changed: boolean; varNames: string[]
}

function computeLayout(data: any): LayoutNode[] {
  if (!data) return []
  const nodes: LayoutNode[] = []
  const varByObj: Record<number, string[]> = {}

  for (const [varName, objId] of Object.entries(data.var_bindings || {})) {
    if (!varByObj[objId as number]) varByObj[objId as number] = []
    varByObj[objId as number].push(varName)
  }

  for (const [, node] of Object.entries(data.nodes || {})) {
    const n = node as any
    const attrs = n.attrs || {}
    // Build full-chain string for tooltip: e.g. "1 → 2 → 3 → None"
    const parts: string[] = [n.val]
    if (attrs.next && !attrs.next.startsWith('<')) parts.push(attrs.next)
    nodes.push({
      id: n.id, x: 0, y: 0, vx: 0, vy: 0,
      type: n.type, val: n.val, fullVal: parts.join(' → '),
      attrs, refs: n.refs || {}, changed: n.changed, varNames: varByObj[n.id] || [],
    })
  }

  const W = 600, H = 400, cx = W / 2, cy = H / 2
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(nodes.length, 1)
    const r = Math.min(W, H) * 0.3
    n.x = cx + r * Math.cos(angle)
    n.y = cy + r * Math.sin(angle)
  })

  const edges: { from: number; to: number }[] = (data.edges || []).map((e: any) => ({ from: e.from, to: e.to }))

  for (let iter = 0; iter < 80; iter++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[j].x - nodes[i].x, dy = nodes[j].y - nodes[i].y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const force = 2000 / (dist * dist)
        nodes[i].vx -= (dx / dist) * force; nodes[i].vy -= (dy / dist) * force
        nodes[j].vx += (dx / dist) * force; nodes[j].vy += (dy / dist) * force
      }
    }
    for (const e of edges) {
      const a = nodes.find(n => n.id === e.from), b = nodes.find(n => n.id === e.to)
      if (!a || !b) continue
      const dx = b.x - a.x, dy = b.y - a.y, dist = Math.sqrt(dx * dx + dy * dy) || 1
      const force = (dist - 100) * 0.05
      a.vx += (dx / dist) * force; a.vy += (dy / dist) * force
      b.vx -= (dx / dist) * force; b.vy -= (dy / dist) * force
    }
    for (const n of nodes) {
      n.vx += (cx - n.x) * 0.01; n.vy += (cy - n.y) * 0.01
      n.vx *= 0.8; n.vy *= 0.8; n.x += n.vx; n.y += n.vy
      n.x = Math.max(40, Math.min(W - 40, n.x)); n.y = Math.max(40, Math.min(H - 40, n.y))
    }
  }
  return nodes
}

const layoutNodes = computed(() => computeLayout(currentData.value))

function getNodeCenter(id: number) {
  const n = layoutNodes.value.find(n => n.id === id)
  return n ? { x: n.x, y: n.y } : { x: 0, y: 0 }
}

function selectObj(id: number) { selectedObj.value = selectedObj.value === id ? null : id }

function getPrevVal(name: string): string {
  const prev = dsStep.value > 0 ? store.timeline[dsStep.value - 1] : null
  return String(prev?.vars?.[name]?.value ?? '').slice(0, 20)
}
function getCurrVal(name: string): string {
  return String(store.timeline[dsStep.value]?.vars?.[name]?.value ?? '').slice(0, 20)
}

const selectedNode = computed(() => {
  if (selectedObj.value === null) return null
  return layoutNodes.value.find(n => n.id === selectedObj.value) || null
})

// Event type from timeline
const currentEventType = computed(() => {
  const step = store.timeline[dsStep.value]
  return step?.event_type || store.semanticEventTypes[dsStep.value] || 'unknown'
})

const EVENT_LABELS: Record<string, string> = {
  assignment: '赋值', condition: '判断', recursive_call: '递归调用',
  return: '返回', pointer_move: '指针移动', pointer_update: '指针更新',
  list_op: '列表操作', loop: '循环', function_call: '函数调用',
  class_def: '类定义', function_def: '函数定义', pass: '跳过',
  break: '跳出', continue: '继续',
}
const eventLabel = computed(() => EVENT_LABELS[currentEventType.value] || currentEventType.value)

// Current pointer move
const currentPointerMove = computed(() => {
  const step = store.timeline[dsStep.value]
  if (step?.pointer_move) return step.pointer_move
  // Fallback: detect from code
  const code = step?.code || ''
  const m = code.match(/(\w+)\s*=\s*(\w+)\.(next|prev|left|right)/)
  if (m) return { pointer: m[1], via: m[3] }
  return null
})
</script>

<template>
  <div class="ds-panel animate-slide-up">
    <div v-if="totalSteps === 0" class="ds-empty">
      <div class="empty-icon">📭</div>
      <p>此执行中无状态变化</p>
    </div>

    <template v-else>
      <!-- Controls -->
      <div class="ds-controls">
        <button class="ctrl-btn play-btn" @click="onCanvasClick" :title="isPlaying ? 'Pause' : 'Play'">
          {{ isPlaying ? '⏸' : '▶' }}
        </button>
        <button class="ctrl-btn" @click="prevDsStep" :disabled="dsStep === 0">&larr;</button>
        <span class="step-label">Step {{ dsStep + 1 }} / {{ totalSteps }}</span>
        <input type="range" :min="0" :max="Math.max(0, totalSteps - 1)" :value="dsStep" @input="onSliderInput" class="step-slider" />
        <button class="ctrl-btn" @click="nextDsStep" :disabled="dsStep >= Math.max(0, totalSteps - 1)">&rarr;</button>
      </div>

      <!-- Code line + narration -->
      <div class="ds-code" v-if="currentData">
        <span class="ds-code-file">line {{ currentData.line }}</span>
        <code>{{ currentData.code }}</code>
      </div>
      <div v-if="store.currentNarration" class="ds-narration">
        <span class="narration-icon">💡</span>
        <span>{{ store.currentNarration }}</span>
        <span v-if="currentEventType && currentEventType !== 'unknown'" :class="['event-badge', `evt-${currentEventType}`]">{{ eventLabel }}</span>
      </div>

      <!-- Pointer transition indicator -->
      <div v-if="currentPointerMove" class="pointer-indicator">
        <span class="ptr-icon">➜</span>
        <span class="ptr-text">{{ currentPointerMove.pointer }} → .{{ currentPointerMove.via }}</span>
      </div>

      <!-- Variable diff -->
      <div class="ds-diff" v-if="varDiff.added.length || varDiff.modified.length || varDiff.removed.length">
        <span v-for="name in varDiff.added" :key="'a'+name" class="diff-tag diff-added">{{ name }}: new</span>
        <span v-for="name in varDiff.modified" :key="'m'+name" class="diff-tag diff-modified">
          {{ name }}: {{ varDiff.details[name] || (getPrevVal(name) + ' → ' + getCurrVal(name)) }}
        </span>
        <span v-for="name in varDiff.removed" :key="'r'+name" class="diff-tag diff-removed">{{ name }}: removed</span>
      </div>

      <!-- Canvas area (click to toggle play) -->
      <div class="ds-canvas" ref="canvasRef" @click="onCanvasClick">
        <svg class="edge-svg">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="28" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
            </marker>
            <marker id="arrow-changed" viewBox="0 0 10 10" refX="28" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#fb7299" />
            </marker>
          </defs>
          <g v-for="edge in (currentData?.edges || [])" :key="`${edge.from}-${edge.to}-${edge.label}`">
            <line
              :x1="getNodeCenter(edge.from).x" :y1="getNodeCenter(edge.from).y"
              :x2="getNodeCenter(edge.to).x" :y2="getNodeCenter(edge.to).y"
              :stroke="edge.changed ? '#fb7299' : '#475569'"
              :stroke-width="edge.changed ? 2.5 : 1.5"
              :stroke-dasharray="edge.changed ? '6,3' : 'none'"
              marker-end="url(#arrow-changed)"
            />
            <text
              :x="(getNodeCenter(edge.from).x + getNodeCenter(edge.to).x) / 2"
              :y="(getNodeCenter(edge.from).y + getNodeCenter(edge.to).y) / 2 - 6"
              fill="#94a3b8" font-size="10" text-anchor="middle"
            >{{ edge.label }}</text>
          </g>
        </svg>

        <div
          v-for="node in layoutNodes" :key="node.id"
          class="ds-node"
          :class="{ changed: node.changed, selected: selectedObj === node.id }"
          :style="{ left: node.x - 36 + 'px', top: node.y - 36 + 'px' }"
          @click.stop="selectObj(node.id)"
        >
          <div class="node-circle" :title="(node.varNames.length ? node.varNames[0] + ' = ' + node.fullVal : node.fullVal) || ''">
            <span class="node-var-name" v-if="node.varNames.length">{{ node.varNames[0] }}</span>
            <span class="node-eq" v-if="node.varNames.length">=</span>
            <span class="node-val">{{ node.val.length > 6 ? node.val.slice(0, 6) + '..' : node.val }}</span>
          </div>
          <div class="node-type">{{ node.type }}</div>
        </div>
      </div>

      <!-- Detail panel -->
      <div v-if="selectedNode" class="ds-detail">
        <div class="detail-header">
          <span class="detail-type">{{ selectedNode.type }}</span>
          <span class="detail-id">#{{ selectedNode.id }}</span>
          <span v-if="selectedNode.changed" class="detail-changed">已变更</span>
        </div>
        <div class="detail-val">{{ selectedNode.val }}</div>
        <div class="detail-attrs" v-if="Object.keys(selectedNode.attrs).length">
          <div v-for="(attrType, name) in selectedNode.attrs" :key="name" class="attr-row">
            <span class="attr-name">{{ name }}</span>
            <span class="attr-type">{{ attrType }}</span>
          </div>
        </div>
        <div class="detail-refs" v-if="Object.keys(selectedNode.refs).length">
          <div class="detail-section-title">References &rarr;</div>
          <div v-for="(targetId, attr) in selectedNode.refs" :key="attr" class="ref-row">
            <span class="ref-attr">.{{ attr }}</span>
            <span class="ref-arrow">&rarr;</span>
            <span class="ref-target">#{{ targetId }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ds-panel { display: flex; flex-direction: column; height: 100%; gap: 8px; }

.ds-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: 100%; color: var(--text-muted); gap: 8px;
}
.empty-icon { font-size: 28px; opacity: 0.5; }
.ds-empty p { font-size: 13px; }

.ds-controls {
  display: flex; align-items: center; gap: 10px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 14px;
}

.ctrl-btn {
  background: rgba(255,255,255,0.06); border: 1px solid var(--border);
  color: var(--text); border-radius: 6px; padding: 4px 12px;
  cursor: pointer; font-size: 14px;
}
.ctrl-btn:disabled { opacity: 0.3; cursor: default; }
.ctrl-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }

.play-btn {
  font-size: 16px; min-width: 36px; text-align: center;
  background: rgba(251,114,153,0.08);
}
.play-btn:hover { background: rgba(251,114,153,0.15); }

.step-label { font-size: 12px; color: var(--text-dim); min-width: 90px; text-align: center; }
.step-slider { flex: 1; accent-color: var(--primary); }

.ds-code {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 14px;
  font-size: 13px; color: var(--text-dim);
}
.ds-code code { color: var(--text); margin-left: 8px; }
.ds-code-file { color: var(--primary); font-size: 11px; }

.ds-narration {
  display: flex; align-items: center; gap: 6px;
  background: linear-gradient(135deg, rgba(59,130,246,0.06), rgba(124,58,237,0.06));
  border: 1px solid rgba(59,130,246,0.15);
  border-left: 3px solid #3b82f6;
  border-radius: 6px; padding: 6px 12px;
  font-size: 12px; color: var(--text);
}
.narration-icon { font-size: 13px; }

.event-badge {
  margin-left: auto; font-size: 10px; font-weight: 700;
  padding: 1px 8px; border-radius: 4px; white-space: nowrap;
}
.evt-assignment { background: rgba(148,163,184,0.12); color: #64748b; }
.evt-condition { background: rgba(234,179,8,0.12); color: #ca8a04; }
.evt-recursive_call { background: rgba(124,58,237,0.12); color: #7c3aed; }
.evt-return { background: rgba(34,197,94,0.12); color: #16a34a; }
.evt-pointer_move { background: rgba(251,114,153,0.12); color: #e11d48; }
.evt-pointer_update { background: rgba(251,114,153,0.12); color: #e11d48; }
.evt-list_op { background: rgba(0,161,214,0.12); color: #00a1d6; }
.evt-loop { background: rgba(251,191,36,0.12); color: #d97706; }
.evt-function_call { background: rgba(59,130,246,0.12); color: #2563eb; }

.pointer-indicator {
  display: flex; align-items: center; gap: 6px;
  background: rgba(251,114,153,0.06);
  border: 1px solid rgba(251,114,153,0.2);
  border-left: 3px solid #e11d48;
  border-radius: 6px; padding: 5px 12px;
  font-size: 12px; animation: ptrPulse 0.6s ease;
}
.ptr-icon { color: #e11d48; font-weight: 700; }
.ptr-text { color: var(--text); font-family: monospace; }
@keyframes ptrPulse {
  0% { background: rgba(251,114,153,0.15); }
  100% { background: rgba(251,114,153,0.06); }
}

.ds-canvas {
  flex: 1; position: relative; min-height: 300px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; overflow: hidden; cursor: pointer;
}

.edge-svg {
  position: absolute; inset: 0; width: 100%; height: 100%;
  pointer-events: none;
}

.ds-node {
  position: absolute; display: flex; flex-direction: column;
  align-items: center; cursor: pointer; z-index: 2;
  transition: transform 0.15s;
}
.ds-node:hover { transform: scale(1.12); }

.node-circle {
  min-width: 48px; height: 36px; border-radius: 10px;
  padding: 0 10px;
  background: var(--bg-card); border: 2px solid var(--border);
  display: flex; align-items: center; justify-content: center; gap: 3px;
  transition: all 0.2s ease;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  white-space: nowrap;
}

.ds-node.changed .node-circle {
  border-color: var(--primary);
  background: rgba(251,114,153,0.1);
  box-shadow: 0 4px 16px rgba(251,114,153,0.25);
}

.ds-node.selected .node-circle {
  border-color: var(--highlight);
  box-shadow: 0 4px 16px rgba(0,161,214,0.25);
}

.node-var-name { font-size: 10px; color: var(--highlight); font-weight: 600; font-family: monospace; }
.node-eq { font-size: 10px; color: var(--text-muted); }
.node-val { font-size: 12px; color: var(--text); font-weight: 700; font-family: monospace; }
.node-type { font-size: 9px; color: var(--text-muted); margin-top: 3px; }

.ds-diff {
  display: flex; flex-wrap: wrap; gap: 6px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 12px;
}

.diff-tag {
  font-size: 11px; font-family: monospace;
  padding: 2px 8px; border-radius: 4px; font-weight: 600;
}
.diff-added { background: rgba(34,197,94,0.1); color: #16a34a; border: 1px solid rgba(34,197,94,0.2); }
.diff-modified { background: rgba(234,179,8,0.1); color: #ca8a04; border: 1px solid rgba(234,179,8,0.2); }
.diff-removed { background: rgba(239,68,68,0.1); color: #dc2626; border: 1px solid rgba(239,68,68,0.2); }

.ds-detail {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 16px;
}
.detail-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.detail-type { font-size: 12px; color: var(--primary); font-weight: 600; }
.detail-id { font-size: 11px; color: var(--text-muted); }
.detail-changed {
  font-size: 9px; background: rgba(251,114,153,0.15);
  color: #fb7299; padding: 2px 8px; border-radius: 4px; font-weight: 700;
}
.detail-val { font-size: 13px; color: var(--text); font-family: monospace; margin-bottom: 8px; }
.detail-section-title { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }
.attr-row, .ref-row { display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 2px 0; }
.attr-name { color: var(--accent); font-family: monospace; }
.attr-type { color: var(--text-muted); font-size: 10px; }
.ref-attr { color: var(--accent); font-family: monospace; }
.ref-arrow { color: var(--text-muted); }
.ref-target { color: var(--highlight); }
</style>
