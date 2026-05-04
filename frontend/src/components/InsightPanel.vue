<script setup lang="ts">
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()
</script>

<template>
  <div class="insight-panel">
    <!-- Welcome state -->
    <div v-if="!store.hasResults" class="welcome">
      <div class="welcome-icon">&#x1F9E0;</div>
      <h2>Paste code, understand everything</h2>
      <p>Why-Code-Agent analyzes your code and explains:</p>
      <div class="feature-grid">
        <div class="feature-card">
          <div class="feature-icon">&#x1F50D;</div>
          <div class="feature-title">WHY this result</div>
          <div class="feature-desc">Variable lineage and critical path</div>
        </div>
        <div class="feature-card">
          <div class="feature-icon">&#x1F4CA;</div>
          <div class="feature-title">Algorithm structure</div>
          <div class="feature-desc">Pattern detection and phase compression</div>
        </div>
        <div class="feature-card">
          <div class="feature-icon">&#x1F4A1;</div>
          <div class="feature-title">One-line insight</div>
          <div class="feature-desc">Cognitive-level explanation</div>
        </div>
        <div class="feature-card">
          <div class="feature-icon">&#x1F9EC;</div>
          <div class="feature-title">Data structures</div>
          <div class="feature-desc">Pointer animation and traversal</div>
        </div>
      </div>
      <p class="hint">Paste code above and click <strong>Analyze</strong>, or try a demo</p>
    </div>

    <!-- Results state -->
    <div v-else class="results animate-slide-up">
      <!-- One-liner insight -->
      <div class="insight-hero">
        <div class="insight-label">INSIGHT</div>
        <div class="insight-text">{{ store.insightResult!.insight.one_liner }}</div>
        <div class="insight-meta">
          <span class="tag tag-confidence">{{ store.insightResult!.insight.algorithm_type }}</span>
          <span class="tag tag-confidence">{{ Math.round(store.insightResult!.insight.confidence * 100) }}% confidence</span>
          <span class="tag tag-pattern">{{ store.insightResult!.total_steps }} steps</span>
        </div>
      </div>

      <!-- Result -->
      <div class="result-box">
        <div class="result-label">Result</div>
        <div class="result-value">{{ formatResult(store.insightResult!.result) }}</div>
      </div>

      <!-- Patterns -->
      <div class="section" v-if="store.insightResult!.insight.patterns.length">
        <div class="section-title">Patterns Detected</div>
        <div class="patterns">
          <div v-for="p in store.insightResult!.insight.patterns" :key="p.name" class="pattern-card">
            <div class="pattern-name">{{ p.name }}</div>
            <div class="pattern-desc">{{ p.description }}</div>
            <div class="pattern-conf">{{ Math.round(p.confidence * 100) }}%</div>
          </div>
        </div>
      </div>

      <!-- Phases -->
      <div class="section" v-if="store.insightResult!.insight.phases.length">
        <div class="section-title">Execution Phases</div>
        <div class="phases">
          <div v-for="(phase, i) in store.insightResult!.insight.phases" :key="i" class="phase-card">
            <div class="phase-num">{{ i + 1 }}</div>
            <div class="phase-info">
              <div class="phase-name">{{ phase.name }}</div>
              <div class="phase-desc">{{ phase.description }}</div>
              <div class="phase-meta">
                Steps {{ phase.start_step }}-{{ phase.end_step }} ({{ phase.step_count }} steps)
                <span v-if="phase.key_variables.length"> | {{ phase.key_variables.join(', ') }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Explanation levels -->
      <div class="section">
        <div class="section-title">Explanation Levels</div>
        <div class="levels">
          <div v-for="(val, key) in store.insightResult!.insight.explanation_levels" :key="key" class="level-block">
            <div class="level-label">{{ key }}</div>
            <pre class="level-content">{{ val }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
function formatResult(result: any): string {
  if (result === null || result === undefined) return 'null'
  if (typeof result === 'object') {
    const s = JSON.stringify(result)
    return s.length > 200 ? s.slice(0, 200) + '...' : s
  }
  return String(result)
}
</script>

<style scoped>
.insight-panel { height: 100%; }

.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: 40px;
}

.welcome-icon { font-size: 64px; margin-bottom: 16px; }

.welcome h2 {
  font-size: 22px;
  margin-bottom: 8px;
  background: linear-gradient(135deg, var(--primary), var(--highlight));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.welcome p { color: var(--text-dim); margin-bottom: 24px; font-size: 14px; }

.feature-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 24px;
  max-width: 500px;
}

.feature-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
  text-align: left;
  transition: all 0.3s;
}

.feature-card:hover {
  border-color: var(--primary);
  transform: translateY(-2px);
}

.feature-icon { font-size: 24px; margin-bottom: 8px; }
.feature-title { font-size: 13px; font-weight: 600; color: var(--text); }
.feature-desc { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

.hint { color: var(--text-muted); font-size: 12px; }
.hint strong { color: var(--primary); }

/* Results */
.results { padding: 0; }

.insight-hero {
  background: linear-gradient(135deg, rgba(251,114,153,0.1), rgba(34,211,238,0.1));
  border: 1px solid rgba(251,114,153,0.2);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
}

.insight-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  letter-spacing: 2px;
  margin-bottom: 8px;
}

.insight-text {
  font-size: 18px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--text);
}

.insight-meta {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.result-box {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 16px;
}

.result-label { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }
.result-value { font-family: monospace; font-size: 14px; color: var(--highlight); word-break: break-all; }

.section { margin-bottom: 16px; }
.section-title { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 8px; }

.patterns { display: flex; flex-wrap: wrap; gap: 8px; }

.pattern-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  flex: 1;
  min-width: 150px;
}

.pattern-name { font-size: 13px; font-weight: 600; color: var(--highlight); }
.pattern-desc { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
.pattern-conf { font-size: 11px; color: var(--success); margin-top: 4px; }

.phases { display: flex; flex-direction: column; gap: 8px; }

.phase-card {
  display: flex;
  gap: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}

.phase-num {
  width: 28px;
  height: 28px;
  background: var(--primary);
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.phase-name { font-size: 13px; font-weight: 600; }
.phase-desc { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
.phase-meta { font-size: 10px; color: var(--text-muted); margin-top: 4px; }

.levels { display: flex; flex-direction: column; gap: 8px; }

.level-block {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.level-label {
  padding: 6px 12px;
  background: rgba(251,114,153,0.1);
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
  border-bottom: 1px solid var(--border);
}

.level-content {
  padding: 10px 12px;
  font-size: 12px;
  font-family: monospace;
  color: var(--text-dim);
  white-space: pre-wrap;
  margin: 0;
  max-height: 200px;
  overflow-y: auto;
}
</style>
