<script setup lang="ts">
import { ref, computed, watch, onUnmounted, nextTick } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()

// ─── Playback state ───────────────────────────────────────────────
const replayStep = ref(0)
const isPlaying = ref(false)
const playSpeed = ref(600)  // ms per step
const isInternal = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

const steps = computed(() => store.timeline || [])
const totalSteps = computed(() => steps.value.length)
const currentStep = computed(() => steps.value[replayStep.value] || null)
const prevStep = computed(() => replayStep.value > 0 ? steps.value[replayStep.value - 1] : null)

// ─── Variable state diff ──────────────────────────────────────────
interface VarChange {
  name: string
  type: 'new' | 'changed' | 'removed' | 'unchanged'
  prevValue: string
  currValue: string
  prevType: string
  currType: string
  flash: boolean  // animate on change
}

const varChanges = computed<VarChange[]>(() => {
  const curr = currentStep.value
  const prev = prevStep.value
  if (!curr) return []

  const currVars = curr.vars || {}
  const prevVars = prev?.vars || {}
  const changes: VarChange[] = []

  for (const [name, currSnap] of Object.entries(currVars)) {
    const snap = currSnap as any
    const prevSnap = prevVars[name]
    if (!prevSnap) {
      changes.push({
        name, type: 'new',
        prevValue: '', currValue: snap.value,
        prevType: '', currType: snap.type || '',
        flash: true
      })
    } else if (snap.value !== prevSnap.value || snap.changed) {
      changes.push({
        name, type: 'changed',
        prevValue: prevSnap.value, currValue: snap.value,
        prevType: prevSnap.type || '', currType: snap.type || '',
        flash: true
      })
    } else {
      changes.push({
        name, type: 'unchanged',
        prevValue: prevSnap.value, currValue: snap.value,
        prevType: prevSnap.type || '', currType: snap.type || '',
        flash: false
      })
    }
  }

  // Removed vars
  for (const name of Object.keys(prevVars)) {
    if (!(name in currVars)) {
      changes.push({
        name, type: 'removed',
        prevValue: prevVars[name].value, currValue: '',
        prevType: prevVars[name].type || '', currType: '',
        flash: true
      })
    }
  }

  // Sort: new/changed first, then unchanged
  return changes.sort((a, b) => {
    const order = { new: 0, changed: 1, removed: 2, unchanged: 3 }
    return (order[a.type] ?? 4) - (order[b.type] ?? 4)
  })
})

// ─── Control flow ─────────────────────────────────────────────────
const lineJumps = computed(() => {
  const curr = currentStep.value
  const prev = prevStep.value
  if (!curr || !prev) return { from: 0, to: curr?.line || 0, isJump: false }

  const fromLine = prev.line || 0
  const toLine = curr.line || 0
  // Jump = not sequential (more than 1 line difference, or backward)
  const isJump = Math.abs(toLine - fromLine) > 1 || toLine < fromLine
  return { from: fromLine, to: toLine, isJump }
})

// ─── Event narration ──────────────────────────────────────────────
const eventNarration = computed(() => {
  const step = currentStep.value
  if (!step) return null
  return {
    type: step.event_type || 'unknown',
    narration: step.narration || '',
    tags: step.semantic_tags || [],
    priority: step.visual_priority || 0,
    pointerMove: step.pointer_move || null,
  }
})

const EVENT_LABELS: Record<string, string> = {
  assignment: '赋值', condition: '判断', recursive_call: '递归调用',
  return: '返回', pointer_move: '指针移动', pointer_update: '指针更新',
  list_op: '列表操作', loop: '循环', function_call: '函数调用',
  class_def: '类定义', function_def: '函数定义', pass: '跳过',
  break: '跳出', continue: '继续', unknown: '',
}

const EVENT_COLORS: Record<string, string> = {
  assignment: '#3b82f6', condition: '#f59e0b', recursive_call: '#8b5cf6',
  return: '#10b981', pointer_move: '#ec4899', pointer_update: '#ec4899',
  list_op: '#06b6d4', loop: '#f97316', function_call: '#6366f1',
}

// ─── Execution stats ──────────────────────────────────────────────
const execStats = computed(() => {
  const s = steps.value
  if (!s.length) return { totalVars: 0, totalChanges: 0, maxDepth: 0, functions: new Set<string>() }

  let totalChanges = 0
  let maxDepth = 0
  const functions = new Set<string>()
  for (const step of s) {
    totalChanges += (step.changed || []).length + (step.new_vars || []).length
    maxDepth = Math.max(maxDepth, step.depth || 0)
    if (step.func) functions.add(step.func)
  }
  return { totalVars: Object.keys(s[s.length - 1]?.vars || {}).length, totalChanges, maxDepth, functions }
})

// ─── Playback controls ────────────────────────────────────────────
function startPlay() {
  stopPlay()
  isPlaying.value = true
  timer = setInterval(() => {
    if (replayStep.value >= totalSteps.value - 1) {
      replayStep.value = 0  // loop
    } else {
      replayStep.value++
    }
    isInternal.value = true
    store.currentStep = replayStep.value
    store.highlightedLine = currentStep.value?.line || 0
    nextTick(() => { isInternal.value = false })
  }, playSpeed.value)
}

function stopPlay() {
  isPlaying.value = false
  if (timer) { clearInterval(timer); timer = null }
}

function togglePlay() {
  if (isPlaying.value) stopPlay()
  else startPlay()
}

function stepForward() {
  stopPlay()
  if (replayStep.value < totalSteps.value - 1) replayStep.value++
  syncToStore()
}

function stepBackward() {
  stopPlay()
  if (replayStep.value > 0) replayStep.value--
  syncToStore()
}

function goToStart() { stopPlay(); replayStep.value = 0; syncToStore() }
function goToEnd() { stopPlay(); replayStep.value = totalSteps.value - 1; syncToStore() }

function onSliderInput(e: Event) {
  stopPlay()
  replayStep.value = Number((e.target as HTMLInputElement).value)
  syncToStore()
}

function syncToStore() {
  isInternal.value = true
  store.currentStep = replayStep.value
  store.highlightedLine = currentStep.value?.line || 0
  nextTick(() => { isInternal.value = false })
}

// Speed control
const speedOptions = [
  { label: '0.25x', value: 2400 },
  { label: '0.5x', value: 1200 },
  { label: '1x', value: 600 },
  { label: '2x', value: 300 },
  { label: '4x', value: 150 },
]

function setSpeed(ms: number) {
  playSpeed.value = ms
  if (isPlaying.value) startPlay()  // restart with new speed
}

// Keyboard shortcuts
function onKeydown(e: KeyboardEvent) {
  if (store.activeTab !== 'replay') return
  if (e.key === ' ') { e.preventDefault(); togglePlay() }
  if (e.key === 'ArrowRight') { e.preventDefault(); stepForward() }
  if (e.key === 'ArrowLeft') { e.preventDefault(); stepBackward() }
  if (e.key === 'Home') { e.preventDefault(); goToStart() }
  if (e.key === 'End') { e.preventDefault(); goToEnd() }
}

// Auto-start when data arrives
watch([totalSteps, () => store.activeTab], ([n, tab]) => {
  if (n > 0 && tab === 'replay' && isPlaying.value) startPlay()
}, { immediate: true })

// Sync from store
watch(() => store.currentStep, (s) => {
  if (isInternal.value) return
  if (store.activeTab === 'replay' && s < totalSteps.value && s !== replayStep.value) {
    replayStep.value = s
  }
})

onUnmounted(() => stopPlay())

// ─── Failure Attribution ──────────────────────────────────────────
const attribution = computed(() => store.failureAttribution)
const findings = computed(() => attribution.value?.findings || [])
const severity = computed(() => attribution.value?.severity || 'healthy')

const SEVERITY_COLORS: Record<string, string> = {
  healthy: '#10b981', warning: '#f59e0b', error: '#ef4444', critical: '#dc2626',
}
const SEVERITY_LABELS: Record<string, string> = {
  healthy: '健康', warning: '警告', error: '错误', critical: '严重',
}

const FINDING_ICONS: Record<string, string> = {
  infinite_loop: '∞', recursion_no_base: '↩', deep_recursion: '↕',
  stale_mutation: '♻', type_instability: '~', performance: '⚡',
}

function findingStepsInRange(finding: any): boolean {
  if (!finding.steps?.length) return false
  return finding.steps.includes(replayStep.value)
}

// ─── Causal Chain ────────────────────────────────────────────────
const causal = computed(() => store.causalChain)
const causalChainLinks = computed(() => causal.value?.causal_chain || [])
const causalSentences = computed(() => causal.value?.causal_sentences || [])
const causalDistance = computed(() => causal.value?.causal_distance || 0)
const divergencePoint = computed(() => causal.value?.divergence_point)

function isCausalStep(stepIdx: number): boolean {
  return causalChainLinks.value.some((l: any) => l.step === stepIdx)
}

function getCausalRole(stepIdx: number): string {
  const link = causalChainLinks.value.find((l: any) => l.step === stepIdx)
  return link?.role || ''
}
</script>

<template>
  <div class="replay-panel">
    <!-- Empty state -->
    <div v-if="totalSteps === 0" class="replay-empty">
      <div class="empty-icon">▶</div>
      <p>No execution data to replay</p>
    </div>

    <template v-else>
      <!-- Header: execution stats -->
      <div class="replay-header">
        <div class="stat-row">
          <span class="stat">
            <span class="stat-value">{{ totalSteps }}</span>
            <span class="stat-label">steps</span>
          </span>
          <span class="stat">
            <span class="stat-value">{{ execStats.totalVars }}</span>
            <span class="stat-label">variables</span>
          </span>
          <span class="stat">
            <span class="stat-value">{{ execStats.totalChanges }}</span>
            <span class="stat-label">mutations</span>
          </span>
          <span class="stat">
            <span class="stat-value">{{ execStats.maxDepth }}</span>
            <span class="stat-label">max depth</span>
          </span>
        </div>
      </div>

      <!-- Playback controls -->
      <div class="playback-bar">
        <div class="transport-controls">
          <button class="transport-btn" @click="goToStart" title="Start (Home)">⏮</button>
          <button class="transport-btn" @click="stepBackward" title="Step ← (←)">⏪</button>
          <button class="transport-btn play-btn" :class="{ playing: isPlaying }" @click="togglePlay" title="Play/Pause (Space)">
            {{ isPlaying ? '⏸' : '▶' }}
          </button>
          <button class="transport-btn" @click="stepForward" title="Step → (→)">⏩</button>
          <button class="transport-btn" @click="goToEnd" title="End (End)">⏭</button>
        </div>

        <!-- Timeline scrubber -->
        <div class="scrubber-row">
          <span class="step-counter">{{ replayStep + 1 }} / {{ totalSteps }}</span>
          <input
            type="range"
            :min="0"
            :max="Math.max(0, totalSteps - 1)"
            :value="replayStep"
            @input="onSliderInput"
            class="scrubber"
          />
          <!-- Line markers on scrubber -->
          <div class="scrubber-markers">
            <div
              v-for="(s, i) in steps"
              :key="i"
              class="marker"
              :class="{ changed: (s.changed || []).length > 0 || (s.new_vars || []).length > 0 }"
              :style="{ left: `${(Number(i) / Math.max(1, totalSteps - 1)) * 100}%` }"
            />
          </div>
        </div>

        <!-- Speed control -->
        <div class="speed-control">
          <button
            v-for="opt in speedOptions"
            :key="opt.value"
            :class="['speed-btn', { active: playSpeed === opt.value }]"
            @click="setSpeed(opt.value)"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>

      <!-- Main content: 3-column layout -->
      <div class="replay-content">
        <!-- Column 1: Code with line highlighting -->
        <div class="code-column">
          <div class="column-header">
            <span class="column-title">Control Flow</span>
            <span v-if="lineJumps.isJump" class="jump-badge">
              JUMP: L{{ lineJumps.from }} → L{{ lineJumps.to }}
            </span>
          </div>
          <div class="code-view">
            <div
              v-for="(line, i) in (store.code || '').split('\n')"
              :key="i"
              :class="['code-line', {
                active: currentStep?.line === i + 1,
                prev: prevStep?.line === i + 1 && currentStep?.line !== i + 1,
                jumpTarget: lineJumps.isJump && lineJumps.to === i + 1,
                jumpSource: lineJumps.isJump && lineJumps.from === i + 1,
                causalRoot: causalChainLinks.some(l => l.line === i + 1 && l.role === 'root_cause'),
                causalContrib: causalChainLinks.some(l => l.line === i + 1 && l.role === 'contributor'),
              }]"
            >
              <span class="line-num">{{ i + 1 }}</span>
              <span class="line-code">{{ line }}</span>
            </div>
          </div>
        </div>

        <!-- Column 2: Variable state diff -->
        <div class="vars-column">
          <div class="column-header">
            <span class="column-title">State Diff</span>
            <span class="change-count">
              {{ varChanges.filter(v => v.type !== 'unchanged').length }} changed
            </span>
          </div>
          <div class="vars-list">
            <div
              v-for="v in varChanges"
              :key="v.name"
              :class="['var-row', `type-${v.type}`, { flash: v.flash }]"
            >
              <div class="var-header">
                <span class="var-name">{{ v.name }}</span>
                <span :class="['var-badge', v.type]">
                  {{ v.type === 'new' ? 'NEW' : v.type === 'changed' ? 'CHG' : v.type === 'removed' ? 'DEL' : '' }}
                </span>
                <span class="var-type">{{ v.currType || v.prevType }}</span>
              </div>
              <div class="var-values">
                <div v-if="v.type === 'changed' || v.type === 'removed'" class="val-prev">
                  <span class="val-label">prev:</span>
                  <span class="val-text">{{ v.prevValue?.slice(0, 40) || '—' }}</span>
                </div>
                <div v-if="v.type !== 'removed'" class="val-curr">
                  <span class="val-label">curr:</span>
                  <span class="val-text">{{ v.currValue?.slice(0, 40) || '—' }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Column 3: Event narration + execution context -->
        <div class="context-column">
          <div class="column-header">
            <span class="column-title">Execution Context</span>
          </div>

          <!-- Event type badge -->
          <div v-if="eventNarration" class="event-section">
            <div class="event-type-row">
              <span
                class="event-type-badge"
                :style="{ background: EVENT_COLORS[eventNarration.type] || '#6b7280' }"
              >
                {{ EVENT_LABELS[eventNarration.type] || eventNarration.type }}
              </span>
              <span v-if="eventNarration.priority" class="priority-dot" :class="{ high: eventNarration.priority >= 2 }">
                P{{ eventNarration.priority }}
              </span>
            </div>

            <!-- Narration -->
            <div v-if="eventNarration.narration" class="narration-text">
              {{ eventNarration.narration }}
            </div>

            <!-- Semantic tags -->
            <div v-if="eventNarration.tags.length" class="tags-row">
              <span v-for="tag in eventNarration.tags" :key="tag" class="tag-chip">
                {{ tag }}
              </span>
            </div>

            <!-- Pointer move -->
            <div v-if="eventNarration.pointerMove" class="pointer-move">
              <span class="pointer-icon">→</span>
              <span class="pointer-text">
                {{ eventNarration.pointerMove.pointer }}
                {{ eventNarration.pointerMove.via }}
                {{ eventNarration.pointerMove.to_object }}
              </span>
            </div>
          </div>

          <!-- Call stack depth -->
          <div class="depth-section">
            <div class="depth-label">Call Depth</div>
            <div class="depth-bar">
              <div
                class="depth-fill"
                :style="{ width: `${((currentStep?.depth || 0) / Math.max(1, execStats.maxDepth)) * 100}%` }"
              />
            </div>
            <span class="depth-value">{{ currentStep?.depth || 0 }}</span>
          </div>

          <!-- Changed variables summary -->
          <div v-if="currentStep?.changed?.length || currentStep?.new_vars?.length" class="changes-section">
            <div class="changes-title">This step mutates:</div>
            <div class="changes-list">
              <span v-for="v in (currentStep?.changed || [])" :key="'c-' + v" class="change-chip changed">
                {{ v }}
              </span>
              <span v-for="v in (currentStep?.new_vars || [])" :key="'n-' + v" class="change-chip new">
                {{ v }}
              </span>
            </div>
          </div>

          <!-- Mini timeline: current position indicator -->
          <div class="mini-timeline">
            <div class="mini-label">Position</div>
            <div class="mini-bar">
              <div
                class="mini-progress"
                :style="{ width: `${((replayStep + 1) / Math.max(1, totalSteps)) * 100}%` }"
              />
              <div
                class="mini-thumb"
                :style="{ left: `${(replayStep / Math.max(1, totalSteps - 1)) * 100}%` }"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- Causal Chain Visualization -->
      <div v-if="causalChainLinks.length > 0" class="causal-bar">
        <div class="causal-header">
          <span class="causal-icon">🔗</span>
          <span class="causal-title">Causal Chain</span>
          <span class="causal-distance">distance: {{ causalDistance }}</span>
        </div>

        <!-- Chain links -->
        <div class="causal-chain">
          <div
            v-for="(link, i) in causalChainLinks"
            :key="i"
            :class="['causal-link', `role-${link.role}`]"
            @click="replayStep = link.step"
          >
            <span class="link-role">{{ link.role === 'root_cause' ? 'ROOT' : link.role === 'failure_point' ? 'FAIL' : '→' }}</span>
            <span class="link-var">`{{ link.version || link.var }}`</span>
            <span class="link-eq">=</span>
            <span class="link-value">{{ link.value?.slice(0, 20) }}</span>
            <span class="link-step">step {{ link.step }}</span>
            <span class="link-line">L{{ link.line }}</span>
          </div>
        </div>

        <!-- Causal sentences -->
        <div v-if="causalSentences.length" class="causal-sentences">
          <div v-for="(s, i) in causalSentences" :key="i" class="causal-sentence">
            {{ s }}
          </div>
        </div>

        <!-- Divergence point -->
        <div v-if="divergencePoint" class="divergence-point">
          <span class="divergence-icon">⚠</span>
          <span class="divergence-text">
            Divergence at step {{ divergencePoint.step }}: `{{ divergencePoint.var }}` = {{ divergencePoint.value }}
          </span>
        </div>
      </div>

      <!-- Failure Attribution Diagnostics -->
      <div v-if="attribution && findings.length > 0" class="diagnostics-bar">
        <div class="diag-header">
          <span class="diag-icon" :style="{ color: SEVERITY_COLORS[severity] }">
            {{ severity === 'critical' ? '🚨' : severity === 'error' ? '⚠️' : '💡' }}
          </span>
          <span class="diag-title">Failure Attribution</span>
          <span class="diag-severity" :style="{ color: SEVERITY_COLORS[severity] }">
            {{ SEVERITY_LABELS[severity] }}
          </span>
          <span class="diag-summary">{{ attribution.summary }}</span>
        </div>

        <div class="findings-list">
          <div
            v-for="(finding, i) in findings"
            :key="i"
            :class="['finding-card', `sev-${finding.severity}`, { active: findingStepsInRange(finding) }]"
            @click="finding.steps?.length && (replayStep = finding.steps[0])"
          >
            <div class="finding-header">
              <span class="finding-icon">{{ FINDING_ICONS[finding.type] || '?' }}</span>
              <span class="finding-title">{{ finding.title }}</span>
              <span class="finding-severity" :style="{ color: SEVERITY_COLORS[finding.severity] }">
                {{ SEVERITY_LABELS[finding.severity] }}
              </span>
            </div>
            <div class="finding-desc">{{ finding.description }}</div>
            <div v-if="finding.suggestion" class="finding-suggestion">
              💡 {{ finding.suggestion }}
            </div>
            <div v-if="finding.steps?.length" class="finding-steps">
              Steps: {{ finding.steps.slice(0, 5).join(', ') }}{{ finding.steps.length > 5 ? '...' : '' }}
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.replay-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  overflow: hidden;
}

.replay-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px;
  color: var(--text-muted);
}

.empty-icon {
  font-size: 48px;
  opacity: 0.5;
}

/* ─── Header ──────────────────────────────────────────── */
.replay-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 12px;
  background: rgba(59, 130, 246, 0.04);
  border: 1px solid rgba(59, 130, 246, 0.12);
  border-radius: 6px;
}

.stat-row {
  display: flex;
  gap: 16px;
}

.stat {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.stat-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--primary);
}

.stat-label {
  font-size: 14px;
  color: var(--text-muted);
}

/* ─── Playback bar ────────────────────────────────────── */
.playback-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.transport-controls {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.transport-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  color: var(--text);
  transition: all 0.15s;
}

.transport-btn:hover {
  background: rgba(59, 130, 246, 0.08);
  border-color: var(--primary);
}

.transport-btn.play-btn {
  width: 40px;
  font-size: 16px;
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}

.transport-btn.play-btn.playing {
  background: #f59e0b;
  border-color: #f59e0b;
}

.scrubber-row {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
}

.step-counter {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  min-width: 60px;
  text-align: center;
  font-family: monospace;
}

.scrubber {
  flex: 1;
  height: 6px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--border);
  border-radius: 3px;
  outline: none;
  cursor: pointer;
}

.scrubber::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--primary);
  cursor: pointer;
}

.scrubber-markers {
  position: absolute;
  top: 50%;
  left: 68px;
  right: 0;
  height: 6px;
  pointer-events: none;
}

.marker {
  position: absolute;
  width: 2px;
  height: 4px;
  background: var(--border);
  transform: translate(-50%, -50%);
}

.marker.changed {
  background: #f59e0b;
  height: 6px;
}

.speed-control {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}

.speed-btn {
  padding: 2px 6px;
  font-size: 14px;
  font-weight: 600;
  background: none;
  border: 1px solid var(--border);
  border-radius: 3px;
  cursor: pointer;
  color: var(--text-muted);
  transition: all 0.15s;
}

.speed-btn:hover {
  color: var(--text);
  border-color: var(--primary);
}

.speed-btn.active {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}

/* ─── Main content: 3-column ──────────────────────────── */
.replay-content {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
  flex: 1;
  overflow: hidden;
}

.column-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  background: rgba(148, 163, 184, 0.06);
  border-bottom: 1px solid var(--border);
}

.column-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.jump-badge {
  font-size: 14px;
  font-weight: 700;
  color: #f59e0b;
  padding: 1px 6px;
  background: rgba(245, 158, 11, 0.1);
  border-radius: 3px;
  animation: pulse 0.6s ease-in-out;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* ─── Code column ─────────────────────────────────────── */
.code-column {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.code-view {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  font-size: 14px;
  line-height: 1.6;
}

.code-line {
  display: flex;
  padding: 0 8px;
  transition: background 0.2s;
}

.code-line.active {
  background: rgba(59, 130, 246, 0.12);
  border-left: 3px solid var(--primary);
  padding-left: 5px;
}

.code-line.prev {
  background: rgba(148, 163, 184, 0.06);
  border-left: 3px solid var(--border);
  padding-left: 5px;
}

.code-line.jumpTarget {
  background: rgba(245, 158, 11, 0.12);
  border-left: 3px solid #f59e0b;
  padding-left: 5px;
}

.code-line.jumpSource {
  background: rgba(239, 68, 68, 0.08);
  border-left: 3px solid #ef4444;
  padding-left: 5px;
}

.line-num {
  width: 28px;
  text-align: right;
  padding-right: 8px;
  color: var(--text-muted);
  user-select: none;
  flex-shrink: 0;
}

.line-code {
  flex: 1;
  white-space: pre;
}

/* ─── Variables column ────────────────────────────────── */
.vars-column {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.vars-column .column-header {
  background: rgba(16, 185, 129, 0.06);
}

.var-row {
  padding: 6px 8px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  transition: background 0.3s;
}

.var-row.type-new {
  background: rgba(16, 185, 129, 0.06);
  border-left: 3px solid #10b981;
}

.var-row.type-changed {
  background: rgba(245, 158, 11, 0.06);
  border-left: 3px solid #f59e0b;
}

.var-row.type-removed {
  background: rgba(239, 68, 68, 0.06);
  border-left: 3px solid #ef4444;
}

.var-row.type-unchanged {
  opacity: 0.6;
}

.var-row.flash {
  animation: varFlash 0.5s ease-out;
}

@keyframes varFlash {
  0% { background: rgba(59, 130, 246, 0.2); }
  100% { background: transparent; }
}

.var-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}

.var-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  font-family: monospace;
}

.var-badge {
  font-size: 14px;
  font-weight: 700;
  padding: 0 4px;
  border-radius: 2px;
}

.var-badge.new { background: #10b981; color: white; }
.var-badge.changed { background: #f59e0b; color: white; }
.var-badge.removed { background: #ef4444; color: white; }

.var-type {
  font-size: 14px;
  color: var(--text-muted);
  margin-left: auto;
}

.var-values {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.val-prev, .val-curr {
  display: flex;
  gap: 4px;
  font-size: 14px;
}

.val-label {
  color: var(--text-muted);
  min-width: 30px;
}

.val-text {
  font-family: monospace;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.val-prev .val-text {
  color: #ef4444;
  text-decoration: line-through;
}

.val-curr .val-text {
  color: #10b981;
}

/* ─── Context column ──────────────────────────────────── */
.context-column {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  gap: 8px;
  padding: 8px;
}

.event-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.event-type-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.event-type-badge {
  font-size: 14px;
  font-weight: 700;
  color: white;
  padding: 2px 8px;
  border-radius: 4px;
}

.priority-dot {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-muted);
}

.priority-dot.high {
  color: #ef4444;
}

.narration-text {
  font-size: 14px;
  color: var(--text);
  line-height: 1.5;
  padding: 6px 8px;
  background: rgba(59, 130, 246, 0.04);
  border-radius: 4px;
  border-left: 3px solid var(--primary);
}

.tags-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.tag-chip {
  font-size: 14px;
  padding: 1px 6px;
  background: rgba(139, 92, 246, 0.08);
  color: #8b5cf6;
  border-radius: 3px;
  font-weight: 600;
}

.pointer-move {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: rgba(236, 72, 153, 0.06);
  border-radius: 4px;
}

.pointer-icon {
  color: #ec4899;
  font-weight: 700;
}

.pointer-text {
  font-size: 14px;
  color: #ec4899;
  font-family: monospace;
}

/* Depth section */
.depth-section {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}

.depth-label {
  font-size: 14px;
  color: var(--text-muted);
  min-width: 60px;
}

.depth-bar {
  flex: 1;
  height: 6px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
}

.depth-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
  border-radius: 3px;
  transition: width 0.3s;
}

.depth-value {
  font-size: 14px;
  font-weight: 700;
  color: var(--primary);
  min-width: 20px;
  text-align: right;
}

/* Changes section */
.changes-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.changes-title {
  font-size: 14px;
  color: var(--text-muted);
}

.changes-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.change-chip {
  font-size: 14px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: monospace;
}

.change-chip.changed {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.change-chip.new {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

/* Mini timeline */
.mini-timeline {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: auto;
}

.mini-label {
  font-size: 14px;
  color: var(--text-muted);
}

.mini-bar {
  position: relative;
  height: 4px;
  background: var(--border);
  border-radius: 2px;
}

.mini-progress {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: var(--primary);
  border-radius: 2px;
  transition: width 0.1s;
}

.mini-thumb {
  position: absolute;
  top: 50%;
  width: 8px;
  height: 8px;
  background: var(--primary);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  transition: left 0.1s;
}

/* ─── Scrollbar ───────────────────────────────────────── */
.code-view::-webkit-scrollbar,
.var-row::-webkit-scrollbar {
  width: 4px;
}

.code-view::-webkit-scrollbar-thumb,
.var-row::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 2px;
}

/* ─── Diagnostics bar ─────────────────────────────────── */
.diagnostics-bar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  background: rgba(239, 68, 68, 0.03);
  border: 1px solid rgba(239, 68, 68, 0.15);
  border-radius: 6px;
}

.diag-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.diag-icon {
  font-size: 16px;
}

.diag-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}

.diag-severity {
  font-size: 14px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(239, 68, 68, 0.08);
}

.diag-summary {
  font-size: 14px;
  color: var(--text-muted);
  margin-left: auto;
}

.findings-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.finding-card {
  padding: 8px 10px;
  background: rgba(148, 163, 184, 0.04);
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.2s;
}

.finding-card:hover {
  background: rgba(148, 163, 184, 0.08);
}

.finding-card.active {
  border-color: var(--primary);
  background: rgba(59, 130, 246, 0.06);
}

.finding-card.sev-critical {
  border-left: 3px solid #dc2626;
}

.finding-card.sev-error {
  border-left: 3px solid #ef4444;
}

.finding-card.sev-warning {
  border-left: 3px solid #f59e0b;
}

.finding-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.finding-icon {
  font-size: 14px;
}

.finding-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}

.finding-severity {
  font-size: 14px;
  font-weight: 700;
  margin-left: auto;
}

.finding-desc {
  font-size: 14px;
  color: var(--text);
  line-height: 1.4;
  margin-bottom: 4px;
}

.finding-suggestion {
  font-size: 14px;
  color: var(--primary);
  line-height: 1.4;
  padding: 4px 8px;
  background: rgba(59, 130, 246, 0.04);
  border-radius: 3px;
}

.finding-steps {
  font-size: 14px;
  color: var(--text-muted);
  font-family: monospace;
  margin-top: 4px;
}

/* ─── Code line causal highlights ─────────────────────── */
.code-line.causalRoot {
  background: rgba(239, 68, 68, 0.1);
  border-left: 3px solid #ef4444;
  padding-left: 5px;
}

.code-line.causalContrib {
  background: rgba(245, 158, 11, 0.08);
  border-left: 3px solid #f59e0b;
  padding-left: 5px;
}

/* ─── Causal chain bar ────────────────────────────────── */
.causal-bar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  background: rgba(59, 130, 246, 0.03);
  border: 1px solid rgba(59, 130, 246, 0.15);
  border-radius: 6px;
}

.causal-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.causal-icon {
  font-size: 16px;
}

.causal-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--primary);
}

.causal-distance {
  font-size: 14px;
  color: var(--text-muted);
  margin-left: auto;
  font-family: monospace;
}

.causal-chain {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.causal-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  font-size: 14px;
  font-family: monospace;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
}

.causal-link:hover {
  background: rgba(59, 130, 246, 0.06);
}

.causal-link.role-root_cause {
  border-left: 3px solid #ef4444;
  background: rgba(239, 68, 68, 0.04);
}

.causal-link.role-contributor {
  border-left: 3px solid #f59e0b;
  background: rgba(245, 158, 11, 0.03);
}

.causal-link.role-failure_point {
  border-left: 3px solid var(--primary);
  background: rgba(59, 130, 246, 0.04);
}

.link-role {
  font-size: 14px;
  font-weight: 700;
  min-width: 30px;
  color: var(--text-muted);
}

.role-root_cause .link-role { color: #ef4444; }
.role-failure_point .link-role { color: var(--primary); }

.link-var {
  color: #8b5cf6;
  font-weight: 600;
}

.link-eq {
  color: var(--text-muted);
}

.link-value {
  color: #10b981;
}

.link-step {
  color: var(--text-muted);
  margin-left: auto;
}

.link-line {
  color: var(--text-muted);
  min-width: 24px;
  text-align: right;
}

.causal-sentences {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 6px 8px;
  background: rgba(148, 163, 184, 0.04);
  border-radius: 4px;
}

.causal-sentence {
  font-size: 14px;
  color: var(--text);
  line-height: 1.4;
}

.divergence-point {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: rgba(239, 68, 68, 0.06);
  border-radius: 4px;
}

.divergence-icon {
  color: #ef4444;
}

.divergence-text {
  font-size: 14px;
  color: #ef4444;
  font-family: monospace;
}
</style>
