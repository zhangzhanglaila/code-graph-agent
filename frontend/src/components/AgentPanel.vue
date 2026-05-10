<script setup lang="ts">
import { ref } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { agentAnalyze } from '../api/analysis'

const store = useAnalysisStore()
const question = ref('')

async function runAgent() {
  store.agentLoading = true
  try {
    const result = await agentAnalyze(store.code, store.funcName, store.language, question.value)
    store.agentResult = result
  } catch (e: any) {
    store.agentResult = { success: false, error: e.message }
  } finally {
    store.agentLoading = false
  }
}

const agent = () => store.agentResult?.agent
</script>

<template>
  <div class="agent-panel">
    <div class="agent-header">
      <h3>Agent Analysis</h3>
      <div class="agent-controls">
        <input
          v-model="question"
          class="question-input"
          placeholder="Ask a question (e.g., Why does result change?)"
          @keyup.enter="runAgent"
        />
        <button class="run-btn" @click="runAgent" :disabled="store.agentLoading">
          {{ store.agentLoading ? 'Running...' : 'Run Agent' }}
        </button>
      </div>
    </div>

    <div v-if="store.agentLoading" class="loading">Analyzing execution...</div>

    <div v-else-if="store.agentResult?.success === false" class="error">
      {{ store.agentResult.error }}
    </div>

    <div v-else-if="agent()" class="agent-content">
      <!-- Observations -->
      <section class="section">
        <h4>Observations</h4>
        <div class="stat-row">
          <span class="stat">{{ agent()!.observation_count }} observations</span>
          <span class="stat">{{ Object.keys(agent()!.state.variables).length }} variables</span>
          <span class="stat">{{ agent()!.state.functions.join(', ') }}</span>
        </div>
      </section>

      <!-- Variables -->
      <section class="section" v-if="Object.keys(agent()!.state.variables).length">
        <h4>Variable Tracking</h4>
        <div class="var-grid">
          <div v-for="(rec, name) in agent()!.state.variables" :key="name" class="var-card">
            <div class="var-name">{{ name }}</div>
            <div class="var-values">{{ rec.values.length }} values</div>
            <div v-if="rec.mutations" class="var-mutations">{{ rec.mutations }} mutations</div>
          </div>
        </div>
      </section>

      <!-- Reasoning Chain -->
      <section class="section" v-if="agent()!.reasoning.steps.length">
        <h4>Reasoning Chain (confidence: {{ (agent()!.reasoning.overall_confidence * 100).toFixed(0) }}%)</h4>
        <div class="reasoning-steps">
          <div v-for="(step, i) in agent()!.reasoning.steps" :key="i" class="reason-step">
            <div class="step-header">
              <span class="step-num">{{ i + 1 }}</span>
              <span class="hypothesis">{{ step.hypothesis.description }}</span>
              <span class="confidence" :class="{ high: step.hypothesis.confidence > 0.7 }">
                {{ (step.hypothesis.confidence * 100).toFixed(0) }}%
              </span>
            </div>
            <div v-if="step.evidence.length" class="evidence-list">
              <div v-for="(e, j) in step.evidence" :key="j" class="evidence" :class="e.kind">
                {{ e.description || e.var }}
              </div>
            </div>
            <div class="conclusion">{{ step.conclusion }}</div>
          </div>
        </div>
      </section>

      <!-- Actions -->
      <section class="section" v-if="agent()!.action_results.length">
        <h4>Actions ({{ agent()!.action_results.length }})</h4>
        <div class="action-list">
          <div v-for="(ar, i) in agent()!.action_results" :key="i" class="action-item" :class="{ success: ar.success }">
            <span class="action-kind">{{ ar.action.kind }}</span>
            <span class="action-status">{{ ar.success ? 'OK' : 'FAIL' }}</span>
          </div>
        </div>
      </section>

      <div class="timing">Completed in {{ agent()!.duration_ms.toFixed(1) }}ms</div>
    </div>

    <div v-else class="empty">
      <p>Run the agent to analyze code execution.</p>
      <p>The agent observes execution, builds hypotheses, and generates explainable reasoning chains.</p>
    </div>
  </div>
</template>

<style scoped>
.agent-panel { padding: 16px; overflow-y: auto; height: 100%; }
.agent-header { margin-bottom: 16px; }
.agent-header h3 { margin: 0 0 12px; font-size: 18px; }
.agent-controls { display: flex; gap: 8px; }
.question-input {
  flex: 1; padding: 8px 12px; border: 1px solid var(--border, #333);
  border-radius: 6px; background: var(--bg-secondary, #1a1a2e); color: inherit; font-size: 14px;
}
.run-btn {
  padding: 8px 16px; border: none; border-radius: 6px;
  background: var(--accent, #4fc3f7); color: #000; font-weight: 600; cursor: pointer;
}
.run-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.loading { padding: 20px; text-align: center; color: var(--text-secondary, #888); }
.error { padding: 12px; background: #3a1c1c; border-radius: 6px; color: #ff6b6b; }
.section { margin-bottom: 16px; }
.section h4 { margin: 0 0 8px; font-size: 14px; color: var(--text-secondary, #888); }
.stat-row { display: flex; gap: 12px; flex-wrap: wrap; }
.stat { padding: 4px 8px; background: var(--bg-secondary, #1a1a2e); border-radius: 4px; font-size: 14px; }
.var-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }
.var-card { padding: 8px; background: var(--bg-secondary, #1a1a2e); border-radius: 6px; }
.var-name { font-weight: 600; font-size: 14px; }
.var-values { font-size: 14px; color: var(--text-secondary, #888); }
.var-mutations { font-size: 14px; color: #ff9800; }
.reasoning-steps { display: flex; flex-direction: column; gap: 8px; }
.reason-step { padding: 10px; background: var(--bg-secondary, #1a1a2e); border-radius: 6px; border-left: 3px solid var(--accent, #4fc3f7); }
.step-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.step-num { width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; background: var(--accent, #4fc3f7); color: #000; border-radius: 50%; font-size: 14px; font-weight: 700; }
.hypothesis { flex: 1; font-size: 14px; font-weight: 500; }
.confidence { font-size: 14px; padding: 2px 6px; border-radius: 10px; background: #333; }
.confidence.high { background: #1b5e20; color: #81c784; }
.evidence-list { margin: 4px 0; }
.evidence { font-size: 14px; padding: 2px 6px; margin: 2px 0; color: var(--text-secondary, #888); }
.evidence.support { border-left: 2px solid #4caf50; }
.evidence.contradict { border-left: 2px solid #f44336; }
.conclusion { font-size: 14px; margin-top: 6px; font-style: italic; color: var(--text-primary, #eee); }
.action-list { display: flex; gap: 8px; flex-wrap: wrap; }
.action-item { padding: 6px 10px; background: var(--bg-secondary, #1a1a2e); border-radius: 4px; display: flex; gap: 6px; align-items: center; }
.action-kind { font-weight: 500; font-size: 14px; }
.action-status { font-size: 14px; padding: 1px 4px; border-radius: 3px; background: #333; }
.action-item.success .action-status { background: #1b5e20; color: #81c784; }
.timing { font-size: 14px; color: var(--text-secondary, #888); margin-top: 8px; }
.empty { padding: 40px 20px; text-align: center; color: var(--text-secondary, #888); }
</style>
