<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { query, type Narrative, type SemanticFact } from '../api/analysis'

const store = useAnalysisStore()

const narrative = ref<Narrative | null>(null)
const facts = ref<SemanticFact[]>([])
const loading = ref(false)
const error = ref('')
const expandedSegments = ref<Set<number>>(new Set())
const showAllFacts = ref(false)
const activeStory = ref<string | null>(null)

async function loadSemanticData() {
  if (!store.hasResults || !store.analysisCode.trim()) return
  loading.value = true
  error.value = ''
  try {
    // Load narrative and facts in parallel
    const [narrativeRes, factsRes] = await Promise.allSettled([
      query(store.analysisCode, store.analysisFuncName, store.analysisLanguage, { type: 'explain_slice' }),
      query(store.analysisCode, store.analysisFuncName, store.analysisLanguage, { type: 'facts' }),
    ])

    if (narrativeRes.status === 'fulfilled' && narrativeRes.value.success) {
      narrative.value = (narrativeRes.value as any).narrative || null
    }
    if (factsRes.status === 'fulfilled' && factsRes.value.success) {
      facts.value = (factsRes.value as any).facts || []
    }
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function toggleSegment(idx: number) {
  if (expandedSegments.value.has(idx)) {
    expandedSegments.value.delete(idx)
  } else {
    expandedSegments.value.add(idx)
  }
}

function factKindIcon(kind: string): string {
  if (kind.startsWith('variable.')) return 'V'
  if (kind.startsWith('data_flow.')) return 'D'
  if (kind.startsWith('loop.')) return 'L'
  if (kind.startsWith('control.')) return 'C'
  if (kind.startsWith('causal.')) return '!'
  return '?'
}

function factKindColor(kind: string): string {
  if (kind.startsWith('variable.')) return '#8b5cf6'
  if (kind.startsWith('data_flow.')) return '#3b82f6'
  if (kind.startsWith('loop.')) return '#f59e0b'
  if (kind.startsWith('control.')) return '#10b981'
  if (kind.startsWith('causal.')) return '#ef4444'
  return '#6b7280'
}

function roleIcon(role: string): string {
  if (role === 'setup') return '1'
  if (role === 'root_cause') return '!'
  if (role === 'flow') return '~'
  if (role === 'loop') return 'L'
  if (role === 'branch') return '?'
  if (role === 'result') return '='
  return '-'
}

const displayedFacts = ref<SemanticFact[]>([])
watch(facts, (f) => {
  displayedFacts.value = showAllFacts.value ? f : f.slice(0, 12)
}, { immediate: true })

watch(showAllFacts, (show) => {
  displayedFacts.value = show ? facts.value : facts.value.slice(0, 12)
})

onMounted(() => { if (store.hasResults) loadSemanticData() })
watch(() => store.sessionId, () => { if (store.hasResults) loadSemanticData() })
</script>

<template>
  <div class="semantic-explorer">
    <!-- Loading -->
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <span>Analyzing semantic structure...</span>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="error-box">{{ error }}</div>

    <!-- Empty -->
    <div v-else-if="!narrative" class="empty">
      <p>No semantic analysis available.</p>
      <p class="hint">Run analysis first, then explore the causal structure here.</p>
    </div>

    <!-- Content -->
    <div v-else class="content">
      <!-- Narrative Title & Summary -->
      <div class="narrative-header">
        <h2>{{ narrative.title }}</h2>
        <p class="summary">{{ narrative.summary }}</p>
      </div>

      <!-- Narrative Segments -->
      <div class="segments">
        <div
          v-for="(seg, i) in narrative.segments"
          :key="i"
          :class="['segment', `role-${seg.role}`, { expanded: expandedSegments.has(i) }]"
        >
          <div class="segment-header" @click="toggleSegment(i)">
            <span class="role-badge" :style="{ background: seg.role === 'root_cause' ? '#ef4444' : seg.role === 'loop' ? '#f59e0b' : seg.role === 'flow' ? '#3b82f6' : '#6b7280' }">
              {{ roleIcon(seg.role) }}
            </span>
            <span class="segment-heading">{{ seg.heading }}</span>
            <span class="segment-toggle">{{ expandedSegments.has(i) ? '−' : '+' }}</span>
          </div>
          <div class="segment-body" v-if="expandedSegments.has(i)">
            <pre class="segment-content">{{ seg.content }}</pre>
          </div>
        </div>
      </div>

      <!-- Variable Evolution Stories -->
      <div v-if="narrative.variable_stories?.length" class="variable-stories">
        <h3>Variable Evolution</h3>
        <div
          v-for="story in narrative.variable_stories"
          :key="story.name"
          :class="['story-card', { active: activeStory === story.name }]"
          @click="activeStory = activeStory === story.name ? null : story.name"
        >
          <div class="story-header">
            <span class="var-name">{{ story.name }}</span>
            <span class="version-count">{{ story.versions }} versions</span>
          </div>
          <div class="story-flow">
            <span class="value first">{{ story.first_value }}</span>
            <span class="arrow">→</span>
            <span class="dots">...</span>
            <span class="arrow">→</span>
            <span class="value last">{{ story.last_value }}</span>
          </div>
          <div class="story-detail" v-if="activeStory === story.name">
            <pre>{{ story.story }}</pre>
          </div>
        </div>
      </div>

      <!-- Semantic Facts -->
      <div class="facts-section">
        <div class="facts-header">
          <h3>Semantic Facts ({{ facts.length }})</h3>
          <button v-if="facts.length > 12" class="toggle-btn" @click="showAllFacts = !showAllFacts">
            {{ showAllFacts ? 'Show Less' : `Show All ${facts.length}` }}
          </button>
        </div>
        <div class="facts-grid">
          <div
            v-for="(fact, i) in displayedFacts"
            :key="i"
            class="fact-card"
            :style="{ borderLeftColor: factKindColor(fact.kind) }"
          >
            <div class="fact-kind">
              <span class="kind-icon" :style="{ background: factKindColor(fact.kind) }">
                {{ factKindIcon(fact.kind) }}
              </span>
              <span class="kind-label">{{ fact.kind }}</span>
            </div>
            <div class="fact-desc">{{ fact.description }}</div>
            <div class="fact-subject" v-if="fact.subject">re: {{ fact.subject }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.semantic-explorer {
  display: flex;
  flex-direction: column;
  gap: 16px;
  font-size: 14px;
}

.loading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 24px;
  color: var(--text-dim, #888);
}

.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--border, #ddd);
  border-top-color: var(--primary, #4f46e5);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.error-box {
  padding: 12px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 6px;
  color: #dc2626;
  font-size: 14px;
}

.empty {
  padding: 32px;
  text-align: center;
  color: var(--text-dim, #888);
}

.empty .hint {
  font-size: 14px;
  margin-top: 8px;
  opacity: 0.7;
}

.narrative-header h2 {
  font-size: 16px;
  font-weight: 700;
  margin: 0 0 6px;
}

.summary {
  color: var(--text-dim, #888);
  font-size: 14px;
  margin: 0;
  line-height: 1.5;
}

/* Segments */
.segments {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.segment {
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  overflow: hidden;
  transition: all 0.15s;
}

.segment:hover {
  border-color: var(--primary, #4f46e5);
}

.segment.role-root_cause {
  border-left: 3px solid #ef4444;
}

.segment.role-loop {
  border-left: 3px solid #f59e0b;
}

.segment.role-flow {
  border-left: 3px solid #3b82f6;
}

.segment-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  background: rgba(0, 0, 0, 0.01);
}

.segment-header:hover {
  background: rgba(0, 0, 0, 0.03);
}

.role-badge {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: white;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.segment-heading {
  flex: 1;
  font-weight: 600;
  font-size: 14px;
}

.segment-toggle {
  font-size: 16px;
  color: var(--text-dim, #888);
  width: 20px;
  text-align: center;
}

.segment-body {
  padding: 0 12px 12px;
  border-top: 1px solid var(--border, #e5e7eb);
}

.segment-content {
  margin: 8px 0 0;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  color: var(--text, #333);
}

/* Variable Stories */
.variable-stories {
  margin-top: 8px;
}

.variable-stories h3 {
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 8px;
}

.story-card {
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.story-card:hover {
  border-color: var(--primary, #4f46e5);
}

.story-card.active {
  border-color: var(--primary, #4f46e5);
  background: rgba(79, 70, 229, 0.03);
}

.story-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.var-name {
  font-weight: 700;
  font-family: monospace;
  color: #8b5cf6;
  font-size: 14px;
}

.version-count {
  font-size: 14px;
  color: var(--text-dim, #888);
  background: rgba(139, 92, 246, 0.08);
  padding: 1px 6px;
  border-radius: 3px;
}

.story-flow {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: monospace;
  font-size: 14px;
}

.value {
  background: rgba(59, 130, 246, 0.08);
  padding: 2px 6px;
  border-radius: 3px;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.value.first { color: #059669; }
.value.last { color: #dc2626; }

.arrow { color: var(--text-dim, #888); }
.dots { color: var(--text-dim, #888); font-size: 14px; }

.story-detail {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border, #e5e7eb);
}

.story-detail pre {
  font-family: inherit;
  font-size: 14px;
  line-height: 1.5;
  white-space: pre-wrap;
  margin: 0;
  color: var(--text, #333);
}

/* Facts */
.facts-section {
  margin-top: 8px;
}

.facts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.facts-header h3 {
  font-size: 14px;
  font-weight: 700;
  margin: 0;
}

.toggle-btn {
  font-size: 14px;
  padding: 3px 8px;
  border: 1px solid var(--border, #ddd);
  border-radius: 4px;
  background: white;
  cursor: pointer;
  color: var(--primary, #4f46e5);
}

.toggle-btn:hover {
  background: rgba(79, 70, 229, 0.05);
}

.facts-grid {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.fact-card {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 8px 10px;
  border: 1px solid var(--border, #e5e7eb);
  border-left: 3px solid #6b7280;
  border-radius: 4px;
  font-size: 14px;
}

.fact-kind {
  display: flex;
  align-items: center;
  gap: 6px;
}

.kind-icon {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  color: white;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.kind-label {
  font-family: monospace;
  font-size: 14px;
  color: var(--text-dim, #888);
}

.fact-desc {
  font-size: 14px;
  line-height: 1.4;
}

.fact-subject {
  font-size: 14px;
  color: var(--text-dim, #888);
}
</style>
