<script setup lang="ts">
import { ref, computed, onUnmounted, watch } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { getExplainStepFocus } from '../api/analysis'

const store = useAnalysisStore()
const playTimer = ref<number | null>(null)
const explainPlaying = ref(false)

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
          :style="{
            background: scoreToHeatColor(store.stepExplanations.find(e => e.step === step.index)?.importance_percentile ?? store.stepExplanations.find(e => e.step === step.index)?.importance_score ?? 0),
            opacity: (store.stepExplanations.find(e => e.step === step.index)?.importance_percentile ?? store.stepExplanations.find(e => e.step === step.index)?.importance_score ?? 0) * 0.7 + 0.3,
          }"
          :title="`Step ${step.index}: ${((store.stepExplanations.find(e => e.step === step.index)?.importance_percentile ?? 0) * 100).toFixed(0)}%ile`"
          @click="goToStepWithFocus(step.index)"
        />
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
            }"
            :title="store.stepExplanations.find(e => e.step === step.index)?.importance_explanation || ''"
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
</style>
