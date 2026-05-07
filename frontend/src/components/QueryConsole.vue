<script setup lang="ts">
import { ref, nextTick, computed } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { textQuery } from '../api/analysis'

const store = useAnalysisStore()

interface QueryEntry {
  id: number
  input: string
  result: any | null
  error: string
  loading: boolean
  showTrace: boolean
}

const entries = ref<QueryEntry[]>([])
const input = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const historyIdx = ref(-1)
const commandHistory = ref<string[]>([])
let nextId = 0

const suggestions = ['WHY ', 'TRACE ', 'IMPACT ', 'SHOW ', 'ROOTS ', 'COMPARE ', 'STATS', 'HELP']
const filteredSuggestions = computed(() => {
  const q = input.value.toUpperCase().trim()
  if (!q) return []
  return suggestions.filter(s => s.startsWith(q) || s.startsWith(q.split(' ')[0]))
})

function focusInput() {
  inputRef.value?.focus()
}

async function execute() {
  const text = input.value.trim()
  if (!text || !store.code.trim()) return

  commandHistory.value.push(text)
  historyIdx.value = commandHistory.value.length

  const entry: QueryEntry = {
    id: nextId++,
    input: text,
    result: null,
    error: '',
    loading: true,
    showTrace: false,
  }
  entries.value.push(entry)
  input.value = ''

  await nextTick()
  scrollToBottom()

  try {
    const res = await textQuery(store.code, store.funcName, store.language, text)
    if (res.success) {
      entry.result = res
    } else {
      entry.error = res.error || 'Query failed'
    }
  } catch (e: any) {
    entry.error = e.message
  } finally {
    entry.loading = false
    await nextTick()
    scrollToBottom()
  }
}

function scrollToBottom() {
  const el = document.querySelector('.qc-entries')
  if (el) el.scrollTop = el.scrollHeight
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    execute()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (historyIdx.value > 0) {
      historyIdx.value--
      input.value = commandHistory.value[historyIdx.value]
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (historyIdx.value < commandHistory.value.length - 1) {
      historyIdx.value++
      input.value = commandHistory.value[historyIdx.value]
    } else {
      historyIdx.value = commandHistory.value.length
      input.value = ''
    }
  } else if (e.key === 'Tab' && filteredSuggestions.value.length) {
    e.preventDefault()
    input.value = filteredSuggestions.value[0]
  }
}

function clearHistory() {
  entries.value = []
}

function toggleTrace(entry: QueryEntry) {
  entry.showTrace = !entry.showTrace
}

function traceSteps(result: any): any[] {
  return result?._trace?.steps || result?.trace?.steps || []
}

function phaseColor(phase: string): string {
  const map: Record<string, string> = {
    parse: '#8b5cf6',
    plan: '#3b82f6',
    traverse: '#f59e0b',
    select: '#10b981',
    narrate: '#ec4899',
    filter: '#6366f1',
  }
  return map[phase] || '#6b7280'
}

function phaseIcon(phase: string): string {
  const map: Record<string, string> = {
    parse: 'P',
    plan: '?',
    traverse: 'T',
    select: 'S',
    narrate: 'N',
    filter: 'F',
  }
  return map[phase] || '?'
}

function resultSummary(result: any): string {
  if (!result) return ''
  if (result.narrative?.title) return result.narrative.title
  if (result.text) return result.text.slice(0, 120) + (result.text.length > 120 ? '...' : '')
  if (result.facts?.length) return `${result.facts.length} facts found`
  if (result.history?.length) return `${result.history.length} versions`
  if (result.steps?.length) return `${result.steps.length} steps`
  if (result.pdg) return `PDG: ${result.pdg.nodes || 0} nodes, ${result.pdg.edges || 0} edges | ${result.facts_count || 0} facts`
  if (result.stats) return JSON.stringify(result.stats).slice(0, 100)
  return JSON.stringify(result).slice(0, 100)
}
</script>

<template>
  <div class="query-console" @click="focusInput">
    <!-- Header -->
    <div class="qc-header">
      <span class="qc-title">Semantic Console</span>
      <span class="qc-hint">Type a query: WHY, TRACE, IMPACT, SHOW, ROOTS, STATS, HELP</span>
      <button v-if="entries.length" class="qc-clear" @click.stop="clearHistory">Clear</button>
    </div>

    <!-- Entries -->
    <div class="qc-entries">
      <div v-for="entry in entries" :key="entry.id" class="qc-entry">
        <!-- Input line -->
        <div class="qc-input-line">
          <span class="qc-prompt">&gt;</span>
          <span class="qc-cmd">{{ entry.input }}</span>
        </div>

        <!-- Loading -->
        <div v-if="entry.loading" class="qc-loading">
          <div class="qc-spinner"></div>
          <span>Executing query...</span>
        </div>

        <!-- Error -->
        <div v-else-if="entry.error" class="qc-error">{{ entry.error }}</div>

        <!-- Result -->
        <div v-else-if="entry.result" class="qc-result">
          <!-- Summary -->
          <div class="qc-summary">{{ resultSummary(entry.result) }}</div>

          <!-- Narrative (if present) -->
          <div v-if="entry.result.narrative" class="qc-narrative">
            <div class="qc-narr-title">{{ entry.result.narrative.title }}</div>
            <div class="qc-narr-summary">{{ entry.result.narrative.summary }}</div>
            <div v-if="entry.result.narrative.segments?.length" class="qc-segments">
              <div
                v-for="(seg, i) in entry.result.narrative.segments"
                :key="i"
                class="qc-seg"
                :class="`role-${seg.role}`"
              >
                <span class="qc-seg-role">{{ seg.role }}</span>
                <span class="qc-seg-heading">{{ seg.heading }}</span>
              </div>
            </div>
          </div>

          <!-- Variable history (TRACE) -->
          <div v-if="entry.result.history?.length" class="qc-history">
            <div
              v-for="(h, i) in entry.result.history.slice(0, 20)"
              :key="i"
              class="qc-hist-row"
            >
              <span class="qc-hist-step">#{{ h.step }}</span>
              <span class="qc-hist-ver">v{{ h.version }}</span>
              <span class="qc-hist-val">{{ h.value }}</span>
              <span class="qc-hist-type">{{ h.type }}</span>
            </div>
            <div v-if="entry.result.history.length > 20" class="qc-more">
              ... {{ entry.result.history.length - 20 }} more
            </div>
          </div>

          <!-- Facts (SHOW) -->
          <div v-if="entry.result.facts?.length" class="qc-facts">
            <div
              v-for="(fact, i) in entry.result.facts.slice(0, 10)"
              :key="i"
              class="qc-fact"
            >
              <span class="qc-fact-kind" :style="{ color: phaseColor(fact.kind?.split('.')[0] || '') }">{{ fact.kind }}</span>
              <span class="qc-fact-desc">{{ fact.description }}</span>
            </div>
            <div v-if="entry.result.facts.length > 10" class="qc-more">
              ... {{ entry.result.facts.length - 10 }} more
            </div>
          </div>

          <!-- Stats -->
          <div v-if="entry.result.stats || entry.result.pdg" class="qc-stats">
            <span v-for="(v, k) in { ...entry.result.pdg, ...entry.result.stats }" :key="k" class="qc-stat">
              {{ k }}: {{ v }}
            </span>
          </div>

          <!-- Text output -->
          <div v-if="entry.result.text && !entry.result.narrative" class="qc-text">
            {{ entry.result.text }}
          </div>

          <!-- Query Trace toggle -->
          <button
            v-if="traceSteps(entry.result).length"
            class="qc-trace-toggle"
            @click.stop="toggleTrace(entry)"
          >
            {{ entry.showTrace ? 'Hide' : 'Show' }} Query Trace
            <span class="qc-trace-count">({{ traceSteps(entry.result).length }} phases)</span>
          </button>

          <!-- Query Trace visualization -->
          <div v-if="entry.showTrace" class="qc-trace">
            <div class="qc-trace-header">
              <span>Query Execution Trace</span>
              <span class="qc-trace-total">{{ entry.result._trace?.total_ms?.toFixed(1) || '?' }}ms</span>
            </div>
            <div class="qc-trace-pipeline">
              <div
                v-for="(step, i) in traceSteps(entry.result)"
                :key="i"
                class="qc-trace-step"
              >
                <div class="qc-trace-node" :style="{ borderColor: phaseColor(step.phase) }">
                  <span class="qc-trace-phase" :style="{ background: phaseColor(step.phase) }">{{ step.phase }}</span>
                  <span class="qc-trace-desc">{{ step.description }}</span>
                  <span v-if="step.duration_ms" class="qc-trace-ms">{{ step.duration_ms.toFixed(1) }}ms</span>
                </div>
                <div v-if="i < traceSteps(entry.result).length - 1" class="qc-trace-arrow">
                  <svg width="20" height="20" viewBox="0 0 20 20">
                    <path d="M10 4 L10 16 M6 12 L10 16 L14 12" stroke="#9ca3af" fill="none" stroke-width="1.5"/>
                  </svg>
                </div>
              </div>
            </div>
            <!-- Phase summary -->
            <div v-if="entry.result._trace?.phase_summary" class="qc-trace-summary">
              <span
                v-for="(ms, phase) in entry.result._trace.phase_summary"
                :key="phase"
                class="qc-trace-ph"
              >
                <span class="qc-trace-ph-dot" :style="{ background: phaseColor(String(phase)) }"></span>
                {{ phase }}: {{ Number(ms).toFixed(1) }}ms
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Empty state -->
      <div v-if="!entries.length" class="qc-empty">
        <div class="qc-empty-icon">?</div>
        <div>Ask a semantic question about your code</div>
        <div class="qc-examples">
          <span @click="input = 'WHY result'">WHY result</span>
          <span @click="input = 'TRACE memo'">TRACE memo</span>
          <span @click="input = 'SHOW loops'">SHOW loops</span>
          <span @click="input = 'ROOTS result'">ROOTS result</span>
          <span @click="input = 'STATS'">STATS</span>
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="qc-input-bar">
      <span class="qc-prompt-input">&gt;</span>
      <input
        ref="inputRef"
        v-model="input"
        placeholder="WHY result | TRACE a | SHOW loops | STATS"
        @keydown="onKeydown"
        :disabled="!store.code.trim()"
      />
      <!-- Suggestions dropdown -->
      <div v-if="filteredSuggestions.length && input" class="qc-suggestions">
        <div
          v-for="s in filteredSuggestions"
          :key="s"
          class="qc-suggestion"
          @click="input = s"
        >
          {{ s }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.query-console {
  display: flex;
  flex-direction: column;
  height: 100%;
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 13px;
  cursor: text;
}

.qc-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border, #e5e7eb);
  background: rgba(0,0,0,0.015);
  flex-shrink: 0;
}

.qc-title {
  font-weight: 700;
  font-size: 13px;
  color: var(--primary, #4f46e5);
}

.qc-hint {
  font-size: 11px;
  color: var(--text-dim, #9ca3af);
  flex: 1;
}

.qc-clear {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid var(--border, #ddd);
  border-radius: 4px;
  background: white;
  cursor: pointer;
  color: var(--text-dim, #888);
}

.qc-entries {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
}

.qc-entry {
  margin-bottom: 12px;
}

.qc-input-line {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
}

.qc-prompt {
  color: var(--primary, #4f46e5);
  font-weight: 700;
  user-select: none;
}

.qc-cmd {
  color: var(--text, #333);
  font-weight: 600;
}

.qc-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  color: var(--text-dim, #888);
  font-size: 12px;
}

.qc-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border, #ddd);
  border-top-color: var(--primary, #4f46e5);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.qc-error {
  padding: 6px 8px;
  background: rgba(239, 68, 68, 0.06);
  border-left: 3px solid #ef4444;
  color: #dc2626;
  font-size: 12px;
  border-radius: 0 4px 4px 0;
}

.qc-result {
  padding-left: 8px;
}

.qc-summary {
  color: var(--text, #333);
  font-size: 12px;
  margin-bottom: 6px;
  line-height: 1.4;
}

/* Narrative */
.qc-narrative {
  margin-bottom: 8px;
}

.qc-narr-title {
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 2px;
}

.qc-narr-summary {
  font-size: 12px;
  color: var(--text-dim, #888);
  margin-bottom: 6px;
  line-height: 1.4;
}

.qc-segments {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.qc-seg {
  display: flex;
  gap: 6px;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(0,0,0,0.02);
}

.qc-seg-role {
  font-weight: 700;
  min-width: 60px;
  color: var(--text-dim, #888);
  text-transform: uppercase;
  font-size: 10px;
}

.qc-seg-heading {
  color: var(--text, #333);
}

/* Variable history */
.qc-history {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin-bottom: 8px;
}

.qc-hist-row {
  display: flex;
  gap: 8px;
  font-size: 11px;
  padding: 2px 0;
}

.qc-hist-step { color: var(--text-dim, #888); min-width: 32px; }
.qc-hist-ver { color: #8b5cf6; font-weight: 600; min-width: 24px; }
.qc-hist-val { color: #059669; font-weight: 600; }
.qc-hist-type { color: var(--text-dim, #9ca3af); font-size: 10px; }

/* Facts */
.qc-facts {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 8px;
}

.qc-fact {
  display: flex;
  gap: 8px;
  font-size: 11px;
  padding: 2px 0;
}

.qc-fact-kind {
  font-weight: 700;
  min-width: 120px;
  font-size: 10px;
}

.qc-fact-desc {
  color: var(--text, #333);
}

/* Stats */
.qc-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.qc-stat {
  font-size: 11px;
  padding: 2px 6px;
  background: rgba(59, 130, 246, 0.06);
  border-radius: 3px;
  color: #3b82f6;
  font-weight: 600;
}

/* Text */
.qc-text {
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  color: var(--text, #333);
  margin-bottom: 8px;
}

.qc-more {
  font-size: 11px;
  color: var(--text-dim, #9ca3af);
  font-style: italic;
}

/* Trace toggle */
.qc-trace-toggle {
  font-size: 11px;
  padding: 3px 8px;
  border: 1px solid var(--border, #ddd);
  border-radius: 4px;
  background: white;
  cursor: pointer;
  color: var(--primary, #4f46e5);
  margin-top: 4px;
}

.qc-trace-toggle:hover {
  background: rgba(79, 70, 229, 0.05);
}

.qc-trace-count {
  color: var(--text-dim, #9ca3af);
  font-weight: 400;
}

/* Trace visualization */
.qc-trace {
  margin-top: 8px;
  padding: 10px;
  background: rgba(0,0,0,0.02);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
}

.qc-trace-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-weight: 700;
  font-size: 12px;
}

.qc-trace-total {
  color: var(--text-dim, #888);
  font-weight: 400;
}

.qc-trace-pipeline {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
}

.qc-trace-step {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.qc-trace-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  background: white;
  min-width: 240px;
}

.qc-trace-phase {
  font-size: 10px;
  font-weight: 700;
  color: white;
  padding: 2px 6px;
  border-radius: 3px;
  text-transform: uppercase;
  min-width: 50px;
  text-align: center;
}

.qc-trace-desc {
  flex: 1;
  font-size: 11px;
  color: var(--text, #333);
}

.qc-trace-ms {
  font-size: 10px;
  color: var(--text-dim, #9ca3af);
}

.qc-trace-arrow {
  display: flex;
  justify-content: center;
  height: 20px;
}

/* Trace summary */
.qc-trace-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border, #e5e7eb);
}

.qc-trace-ph {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--text-dim, #888);
}

.qc-trace-ph-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

/* Empty state */
.qc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-dim, #9ca3af);
  font-size: 13px;
  gap: 8px;
}

.qc-empty-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: rgba(79, 70, 229, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: var(--primary, #4f46e5);
  font-weight: 700;
}

.qc-examples {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.qc-examples span {
  font-size: 11px;
  padding: 3px 8px;
  border: 1px solid var(--border, #ddd);
  border-radius: 4px;
  cursor: pointer;
  color: var(--primary, #4f46e5);
  font-family: monospace;
}

.qc-examples span:hover {
  background: rgba(79, 70, 229, 0.05);
}

/* Input bar */
.qc-input-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid var(--border, #e5e7eb);
  background: white;
  flex-shrink: 0;
  position: relative;
}

.qc-prompt-input {
  color: var(--primary, #4f46e5);
  font-weight: 700;
  user-select: none;
}

.qc-input-bar input {
  flex: 1;
  border: none;
  outline: none;
  font-family: inherit;
  font-size: 13px;
  background: transparent;
  color: var(--text, #333);
}

.qc-input-bar input::placeholder {
  color: var(--text-dim, #9ca3af);
}

.qc-input-bar input:disabled {
  opacity: 0.5;
}

/* Suggestions */
.qc-suggestions {
  position: absolute;
  bottom: 100%;
  left: 32px;
  background: white;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  overflow: hidden;
  z-index: 10;
}

.qc-suggestion {
  padding: 6px 12px;
  font-size: 12px;
  cursor: pointer;
  font-family: monospace;
  color: var(--text, #333);
}

.qc-suggestion:hover {
  background: rgba(79, 70, 229, 0.08);
  color: var(--primary, #4f46e5);
}
</style>
