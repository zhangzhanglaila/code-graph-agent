<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()
const playTimer = ref<number | null>(null)

const steps = computed(() => store.timeline)

function togglePlay() {
  store.isPlaying = !store.isPlaying
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

onUnmounted(() => {
  if (playTimer.value) clearTimeout(playTimer.value)
})
</script>

<template>
  <div class="timeline-panel animate-slide-up">
    <!-- Controls -->
    <div class="controls">
      <button class="btn btn-secondary btn-sm" @click="store.prevStep()">&#9664;</button>
      <button class="btn btn-sm" :class="store.isPlaying ? 'btn-primary' : 'btn-secondary'" @click="togglePlay">
        {{ store.isPlaying ? '&#9632;' : '&#9654;' }}
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
          :class="{ active: step.index === store.currentStep }"
          @click="store.goToStep(step.index)"
        >
          <span class="step-idx">{{ step.index }}</span>
          <span class="step-code-text">{{ step.code }}</span>
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
}

.btn-sm { padding: 4px 12px; font-size: 12px; }

.slider { flex: 1; accent-color: var(--primary); }

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

.step-idx { color: var(--text-muted); min-width: 30px; text-align: right; }
.step-code-text { font-family: monospace; color: var(--text-dim); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step-changes-dot { font-size: 8px; }
</style>
