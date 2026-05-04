<script setup lang="ts">
import { ref, computed, onUnmounted, watch } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()
const playTimer = ref<number | null>(null)
const explainPlaying = ref(false)

const steps = computed(() => store.timeline)
const hasStepExplanations = computed(() => store.stepExplanations.length > 0)

// Importance color
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

// Normal play
function togglePlay() {
  store.isPlaying = !store.isPlaying
  if (store.isPlaying) {
    explainPlaying.value = false
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

// Explain Mode — auto-play with AI narration
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
    // Slower speed for explain mode — give time to read
    const speed = Math.max(store.playSpeed * 2, 1500)
    playTimer.value = window.setTimeout(explainPlayNext, speed)
  } else {
    explainPlaying.value = false
    store.isPlaying = false
  }
}

onUnmounted(() => {
  if (playTimer.value) clearTimeout(playTimer.value)
})
</script>

<template>
  <div class="timeline-panel animate-slide-up">
    <!-- Controls -->
    <div class="controls">
      <button class="btn btn-secondary btn-sm" @click="store.prevStep()">&#9664;</button>
      <button class="btn btn-sm" :class="store.isPlaying && !explainPlaying ? 'btn-primary' : 'btn-secondary'" @click="togglePlay">
        {{ store.isPlaying && !explainPlaying ? '&#9632;' : '&#9654;' }}
      </button>
      <button class="btn btn-secondary btn-sm" @click="store.nextStep()">&#9654;</button>
      <input
        type="range"
        class="slider"
        :min="0"
        :max="store.totalSteps - 1"
        :value="store.currentStep"
        @input="store.goToStep(+($event.target as HTMLInputElement).value)"
      />
      <span class="step-display">{{ store.currentStep }} / {{ store.totalSteps - 1 }}</span>
      <input type="number" class="speed-input" v-model.number="store.playSpeed" min="100" max="3000" step="100" />
      <span class="speed-label">ms</span>

      <!-- Explain Mode button -->
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
    <div v-if="store.currentStepExplanation" class="step-explain card">
      <div class="explain-header">
        <span class="explain-badge">AI</span>
        <span class="explain-step-label">Step {{ store.currentStep }}</span>
        <span
          class="explain-importance"
          :style="{ color: importanceColor(store.currentStepExplanation.importance) }"
        >
          {{ importanceIcon(store.currentStepExplanation.importance) }}
          {{ store.currentStepExplanation.importance }}
        </span>
      </div>
      <div class="explain-text">{{ store.currentStepExplanation.explanation }}</div>
    </div>

    <!-- Current step highlight -->
    <div v-if="store.currentStepData" class="current-step card">
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

    <!-- Step list -->
    <div class="step-list">
      <div class="section-title">All Steps</div>
      <div class="steps-scroll">
        <div
          v-for="step in steps"
          :key="step.index"
          class="step-item"
          :class="{
            active: step.index === store.currentStep,
            'has-ai': hasStepExplanations
          }"
          @click="store.goToStep(step.index)"
        >
          <span class="step-idx">{{ step.index }}</span>
          <span class="step-code-text">{{ step.code }}</span>
          <span
            v-if="hasStepExplanations"
            class="step-ai-dot"
            :style="{ color: importanceColor(store.stepExplanations.find(e => e.step === step.index)?.importance || 'medium') }"
          >{{ importanceIcon(store.stepExplanations.find(e => e.step === step.index)?.importance || 'medium') }}</span>
          <span v-if="step.changed.length" class="step-changes-dot">&#x1F534;</span>
        </div>
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
  width: 50px;
  background: var(--bg-dark);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
  text-align: center;
}

.speed-label { font-size: 11px; color: var(--text-muted); }

.explain-btn {
  background: linear-gradient(135deg, rgba(34,211,238,0.15), rgba(167,139,250,0.15));
  border-color: rgba(34,211,238,0.3);
  color: var(--highlight);
  font-weight: 700;
  letter-spacing: 0.5px;
}

.explain-btn:hover {
  border-color: var(--highlight);
  background: linear-gradient(135deg, rgba(34,211,238,0.25), rgba(167,139,250,0.25));
}

.explain-active {
  background: linear-gradient(135deg, var(--highlight), #a78bfa) !important;
  color: #0f172a !important;
  border-color: transparent !important;
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
}

.explain-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.explain-badge {
  background: linear-gradient(135deg, #22d3ee, #a78bfa);
  color: #0f172a;
  font-size: 9px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 3px;
  letter-spacing: 1px;
}

.explain-step-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--highlight);
}

.explain-importance {
  font-size: 10px;
  margin-left: auto;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.explain-text {
  font-size: 14px;
  color: var(--text);
  line-height: 1.6;
}

/* Current step */
.current-step { border-color: var(--primary); }

.step-header { display: flex; justify-content: space-between; margin-bottom: 6px; }
.step-num { font-weight: 700; color: var(--primary); }
.step-loc { font-size: 12px; color: var(--text-muted); }
.step-code { font-family: monospace; font-size: 14px; color: var(--highlight); padding: 6px 0; }
.step-changes { font-size: 11px; color: var(--warning); margin-top: 4px; }
.step-new { font-size: 11px; color: var(--success); margin-top: 2px; }

.vars-section { }

.section-title { font-size: 13px; font-weight: 600; color: var(--text-dim); margin-bottom: 8px; }

.var-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 6px; }

.var-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  position: relative;
  transition: all 0.2s;
}

.var-card.changed { border-color: var(--warning); background: rgba(251,191,36,0.05); }
.var-card.is-new { border-color: var(--success); background: rgba(52,211,153,0.05); }

.var-name { font-size: 12px; font-weight: 600; color: var(--highlight); }
.var-value { font-size: 11px; font-family: monospace; color: var(--text); margin-top: 2px; word-break: break-all; max-height: 40px; overflow: hidden; }
.var-type { font-size: 10px; color: var(--text-muted); margin-top: 2px; }

.var-badge {
  position: absolute;
  top: -6px;
  right: 4px;
  font-size: 8px;
  padding: 1px 5px;
  border-radius: 6px;
  font-weight: 700;
}

.changed-badge { background: var(--warning); color: #000; }
.new-badge { background: var(--success); color: #000; }

.step-list { flex: 1; min-height: 0; }
.steps-scroll { max-height: 300px; overflow-y: auto; }

.step-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  cursor: pointer;
  border-radius: 4px;
  font-size: 11px;
  transition: background 0.15s;
}

.step-item:hover { background: var(--bg-card-hover); }
.step-item.active { background: rgba(251,114,153,0.15); border-left: 2px solid var(--primary); }
.step-item.has-ai .step-idx { min-width: 24px; }

.step-idx { color: var(--text-muted); min-width: 30px; text-align: right; }
.step-code-text { font-family: monospace; color: var(--text-dim); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step-changes-dot { font-size: 8px; }
.step-ai-dot { font-size: 10px; min-width: 14px; text-align: center; }
</style>
