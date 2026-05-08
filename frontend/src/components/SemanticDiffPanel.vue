<script setup lang="ts">
import { ref } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { semanticDiff, getSimilarity } from '../api/analysis'

const store = useAnalysisStore()

const codeA = ref(store.code)
const codeB = ref('')
const loading = ref(false)
const error = ref('')
const result = ref<any>(null)
const similarityResult = ref<any>(null)
const expandedCats = ref<Set<string>>(new Set(['regression']))

async function runDiff() {
  if (!codeA.value.trim() || !codeB.value.trim()) return
  loading.value = true
  error.value = ''
  result.value = null
  similarityResult.value = null
  try {
    const [diffRes, simRes] = await Promise.allSettled([
      semanticDiff(codeA.value, codeB.value, store.funcName, store.language),
      getSimilarity(codeA.value, codeB.value, store.funcName, store.language),
    ])

    if (diffRes.status === 'fulfilled' && diffRes.value.success) {
      result.value = diffRes.value
    } else {
      error.value = diffRes.status === 'rejected' ? diffRes.reason?.message : diffRes.value?.error || 'Diff failed'
    }

    if (simRes.status === 'fulfilled' && simRes.value.success) {
      similarityResult.value = simRes.value.similarity
    }
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function useCurrentAsA() {
  codeA.value = store.code
}

function toggleCat(cat: string) {
  if (expandedCats.value.has(cat)) {
    expandedCats.value.delete(cat)
  } else {
    expandedCats.value.add(cat)
  }
}

function severityColor(s: string): string {
  if (s === 'regression') return '#ef4444'
  if (s === 'improvement') return '#10b981'
  if (s === 'warning') return '#f59e0b'
  return '#6b7280'
}

function severityIcon(s: string): string {
  if (s === 'regression') return '!'
  if (s === 'improvement') return '+'
  if (s === 'warning') return '~'
  return '*'
}

function groupedItems(items: any[]): Record<string, any[]> {
  const groups: Record<string, any[]> = {}
  for (const item of items) {
    const key = item.severity
    if (!groups[key]) groups[key] = []
    groups[key].push(item)
  }
  return groups
}

function categoryLabel(cat: string): string {
  const map: Record<string, string> = {
    topology: 'Topology',
    dependency: 'Dependencies',
    variable: 'Variables',
    root_cause: 'Root Causes',
    fact: 'Semantic Facts',
    complexity: 'Complexity',
    narrative: 'Narrative',
  }
  return map[cat] || cat
}
</script>

<template>
  <div class="diff-panel">
    <!-- Input -->
    <div class="diff-input">
      <div class="diff-col">
        <div class="diff-col-header">
          <span class="diff-label">Run A (baseline)</span>
          <button class="diff-use-btn" @click="useCurrentAsA">Use current</button>
        </div>
        <textarea v-model="codeA" placeholder="Paste code version A..." rows="8"></textarea>
      </div>
      <div class="diff-col">
        <div class="diff-col-header">
          <span class="diff-label">Run B (comparison)</span>
        </div>
        <textarea v-model="codeB" placeholder="Paste code version B..." rows="8"></textarea>
      </div>
    </div>

    <button class="diff-run-btn" @click="runDiff" :disabled="loading || !codeA.trim() || !codeB.trim()">
      {{ loading ? 'Comparing...' : 'Semantic Diff' }}
    </button>

    <!-- Loading -->
    <div v-if="loading" class="diff-loading">
      <div class="diff-spinner"></div>
      <span>Running both versions and comparing semantics...</span>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="diff-error">{{ error }}</div>

    <!-- Result -->
    <div v-else-if="result" class="diff-result">
      <!-- Similarity Score -->
      <div v-if="similarityResult" class="similarity-header">
        <div class="sim-score-ring">
          <span class="sim-score-val">{{ (similarityResult.score * 100).toFixed(0) }}%</span>
          <span class="sim-score-label">Semantic Similarity</span>
        </div>
        <div class="sim-vectors">
          <div v-for="v in similarityResult.vectors" :key="v.name" class="sim-vector">
            <span class="sim-vec-name">{{ v.name }}</span>
            <div class="sim-vec-bar">
              <div class="sim-vec-fill" :style="{ width: (v.score * 100) + '%', background: v.score > 0.7 ? '#10b981' : v.score > 0.4 ? '#f59e0b' : '#ef4444' }"></div>
            </div>
            <span class="sim-vec-val">{{ (v.score * 100).toFixed(0) }}%</span>
          </div>
        </div>
        <div class="sim-summary">{{ similarityResult.summary }}</div>
      </div>

      <!-- Summary bar -->
      <div class="diff-summary-bar">
        <span class="diff-summary-text">{{ result.diff.summary }}</span>
        <div class="diff-counts">
          <span class="diff-count reg" v-if="result.diff.counts.regressions">
            {{ result.diff.counts.regressions }} regressions
          </span>
          <span class="diff-count imp" v-if="result.diff.counts.improvements">
            {{ result.diff.counts.improvements }} improvements
          </span>
          <span class="diff-count warn" v-if="result.diff.counts.warnings">
            {{ result.diff.counts.warnings }} warnings
          </span>
        </div>
      </div>

      <!-- Complexity comparison -->
      <div class="diff-section" v-if="result.diff.complexity_delta?.run_a">
        <div class="diff-section-header" @click="toggleCat('complexity')">
          <span>Complexity Comparison</span>
          <span class="diff-toggle">{{ expandedCats.has('complexity') ? '-' : '+' }}</span>
        </div>
        <div v-if="expandedCats.has('complexity')" class="diff-section-body">
          <table class="diff-table">
            <tr><th></th><th>Run A</th><th>Run B</th><th>Delta</th></tr>
            <tr v-for="metric in ['nodes', 'edges', 'max_fan_in', 'max_fan_out', 'data_density']" :key="metric">
              <td class="metric-name">{{ metric }}</td>
              <td>{{ result.diff.complexity_delta.run_a[metric] }}</td>
              <td>{{ result.diff.complexity_delta.run_b[metric] }}</td>
              <td :class="{ 'delta-pos': result.diff.complexity_delta.run_b[metric] > result.diff.complexity_delta.run_a[metric], 'delta-neg': result.diff.complexity_delta.run_b[metric] < result.diff.complexity_delta.run_a[metric] }">
                {{ (result.diff.complexity_delta.run_b[metric] - result.diff.complexity_delta.run_a[metric]).toFixed(2) }}
              </td>
            </tr>
          </table>
        </div>
      </div>

      <!-- Items grouped by severity -->
      <div v-for="severity in ['regression', 'warning', 'improvement', 'info']" :key="severity">
        <div
          v-if="groupedItems(result.diff.items)[severity]?.length"
          class="diff-section"
        >
          <div class="diff-section-header" @click="toggleCat(severity)">
            <span class="diff-sev-badge" :style="{ background: severityColor(severity) }">
              {{ severityIcon(severity) }}
            </span>
            <span>{{ severity.charAt(0).toUpperCase() + severity.slice(1) }}s ({{ groupedItems(result.diff.items)[severity].length }})</span>
            <span class="diff-toggle">{{ expandedCats.has(severity) ? '-' : '+' }}</span>
          </div>
          <div v-if="expandedCats.has(severity)" class="diff-section-body">
            <div
              v-for="(item, i) in groupedItems(result.diff.items)[severity]"
              :key="i"
              class="diff-item"
              :style="{ borderLeftColor: severityColor(severity) }"
            >
              <span class="diff-item-cat">{{ categoryLabel(item.category) }}</span>
              <span class="diff-item-desc">{{ item.description }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty -->
    <div v-else class="diff-empty">
      <p>Paste two versions of the same function to see semantic differences.</p>
      <p class="hint">Not line diffs — dependency shifts, root cause changes, value divergences.</p>
    </div>
  </div>
</template>

<style scoped>
.diff-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 13px;
}

.diff-input {
  display: flex;
  gap: 12px;
}

.diff-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.diff-col-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.diff-label {
  font-weight: 700;
  font-size: 12px;
  color: var(--text-dim, #888);
  text-transform: uppercase;
}

.diff-use-btn {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid var(--border, #ddd);
  border-radius: 4px;
  background: white;
  cursor: pointer;
  color: var(--primary, #4f46e5);
}

.diff-input textarea {
  width: 100%;
  font-family: 'SF Mono', 'Consolas', monospace;
  font-size: 12px;
  padding: 8px;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  resize: vertical;
  line-height: 1.5;
  background: #fafbfc;
}

.diff-run-btn {
  align-self: center;
  padding: 8px 24px;
  background: var(--primary, #4f46e5);
  color: white;
  border: none;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  font-size: 13px;
}

.diff-run-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.diff-loading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px;
  color: var(--text-dim, #888);
}

.diff-spinner {
  width: 20px; height: 20px;
  border: 2px solid var(--border, #ddd);
  border-top-color: var(--primary, #4f46e5);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.diff-error {
  padding: 10px;
  background: rgba(239,68,68,0.06);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: 6px;
  color: #dc2626;
}

.diff-empty {
  padding: 32px;
  text-align: center;
  color: var(--text-dim, #9ca3af);
}

.diff-empty .hint {
  font-size: 12px;
  margin-top: 4px;
  opacity: 0.7;
}

/* Similarity Header */
.similarity-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  background: linear-gradient(135deg, rgba(139,92,246,0.04), rgba(59,130,246,0.04));
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 8px;
  margin-bottom: 12px;
}

.sim-score-ring {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 70px;
}

.sim-score-val {
  font-size: 24px;
  font-weight: 800;
  color: #8b5cf6;
}

.sim-score-label {
  font-size: 10px;
  color: var(--text-dim, #888);
  text-align: center;
}

.sim-vectors {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sim-vector {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sim-vec-name {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-dim, #888);
  width: 80px;
  text-align: right;
}

.sim-vec-bar {
  flex: 1;
  height: 6px;
  background: rgba(0,0,0,0.06);
  border-radius: 3px;
  overflow: hidden;
}

.sim-vec-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}

.sim-vec-val {
  font-size: 10px;
  font-weight: 600;
  width: 32px;
  text-align: right;
}

.sim-summary {
  font-size: 11px;
  color: var(--text-dim, #888);
  max-width: 150px;
  text-align: right;
}

/* Summary */
.diff-summary-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: rgba(0,0,0,0.02);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
}

.diff-summary-text {
  flex: 1;
  font-weight: 600;
  font-size: 12px;
}

.diff-counts {
  display: flex;
  gap: 6px;
}

.diff-count {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
}

.diff-count.reg { background: rgba(239,68,68,0.1); color: #dc2626; }
.diff-count.imp { background: rgba(16,185,129,0.1); color: #059669; }
.diff-count.warn { background: rgba(245,158,11,0.1); color: #d97706; }

/* Sections */
.diff-section {
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  overflow: hidden;
}

.diff-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  font-weight: 600;
  font-size: 13px;
  background: rgba(0,0,0,0.01);
}

.diff-section-header:hover { background: rgba(0,0,0,0.03); }

.diff-toggle {
  margin-left: auto;
  font-size: 16px;
  color: var(--text-dim, #888);
}

.diff-sev-badge {
  width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 4px;
  color: white;
  font-size: 11px;
  font-weight: 700;
}

.diff-section-body {
  padding: 8px 12px;
  border-top: 1px solid var(--border, #e5e7eb);
}

/* Items */
.diff-item {
  display: flex;
  gap: 8px;
  padding: 4px 0 4px 8px;
  border-left: 3px solid #6b7280;
  margin-bottom: 4px;
  font-size: 12px;
}

.diff-item-cat {
  font-weight: 600;
  min-width: 80px;
  color: var(--text-dim, #888);
  font-size: 11px;
  text-transform: uppercase;
}

.diff-item-desc {
  flex: 1;
  line-height: 1.4;
}

/* Table */
.diff-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.diff-table th {
  text-align: left;
  font-weight: 600;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border, #e5e7eb);
  color: var(--text-dim, #888);
  font-size: 11px;
}

.diff-table td {
  padding: 4px 8px;
  border-bottom: 1px solid rgba(0,0,0,0.03);
}

.metric-name { font-family: monospace; font-weight: 600; }
.delta-pos { color: #dc2626; }
.delta-neg { color: #059669; }
</style>
