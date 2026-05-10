<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { getIdentity } from '../api/analysis'

const store = useAnalysisStore()

const loading = ref(false)
const error = ref('')
const identities = ref<any>(null)
const normalForm = ref<any>(null)
const fingerprint = ref<any>(null)
const ontology = ref<any>(null)
const selectedNode = ref<string | null>(null)
const expandedCats = ref<Set<string>>(new Set(['algorithm', 'variable']))

async function loadIdentityData() {
  if (!store.code.trim()) return
  loading.value = true
  error.value = ''
  try {
    const res = await getIdentity(store.code, store.funcName, store.language)
    if (res.success) {
      identities.value = (res as any).identities || null
      normalForm.value = (res as any).normal_form || null
      fingerprint.value = (res as any).fingerprint || null
      ontology.value = (res as any).ontology || null
    } else {
      error.value = res.error || 'Failed to load identity'
    }
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function toggleCat(cat: string) {
  if (expandedCats.value.has(cat)) expandedCats.value.delete(cat)
  else expandedCats.value.add(cat)
}

function categoryColor(cat: string): string {
  const map: Record<string, string> = {
    algorithm: '#8b5cf6',
    variable: '#3b82f6',
    structure: '#f59e0b',
    control: '#10b981',
  }
  return map[cat] || '#6b7280'
}

function categoryIcon(cat: string): string {
  const map: Record<string, string> = {
    algorithm: 'A',
    variable: 'V',
    structure: 'S',
    control: 'C',
  }
  return map[cat] || '?'
}

function confidenceWidth(conf: number): string {
  return `${Math.round(conf * 100)}%`
}

const canonicalByCategory = computed(() => {
  if (!normalForm.value?.canonical_identities) return {}
  const groups: Record<string, any[]> = {}
  for (const c of normalForm.value.canonical_identities) {
    if (!groups[c.category]) groups[c.category] = []
    groups[c.category].push(c)
  }
  return groups
})

const relationshipEdges = computed(() => {
  if (!identities.value?.relationships) return []
  return identities.value.relationships
})

onMounted(loadIdentityData)
watch(() => store.hasResults, (has) => { if (has) loadIdentityData() })
</script>

<template>
  <div class="semantic-map">
    <!-- Loading -->
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <span>Analyzing semantic identity...</span>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="error-box">{{ error }}</div>

    <!-- Empty -->
    <div v-else-if="!fingerprint" class="empty">
      <p>No semantic identity available.</p>
      <p class="hint">Run analysis first to see the semantic map.</p>
    </div>

    <!-- Content -->
    <div v-else class="content">
      <!-- Fingerprint Header -->
      <div class="fp-header">
        <div class="fp-hash">{{ fingerprint.hash }}</div>
        <div class="fp-signature">
          <span class="fp-algo">{{ fingerprint.algorithm }}</span>
          <span class="fp-conf">{{ (fingerprint.algorithm_confidence * 100).toFixed(0) }}%</span>
        </div>
        <div class="fp-details">
          <span class="fp-tag" v-if="fingerprint.structures.length">
            {{ fingerprint.structures.join(' + ') }}
          </span>
          <span class="fp-tag complexity">{{ fingerprint.complexity }}</span>
        </div>
      </div>

      <!-- Canonical Identity Graph -->
      <div class="graph-section">
        <h3>Semantic Identity Graph</h3>

        <!-- Node graph (vertical tree) -->
        <div class="identity-graph">
          <!-- Algorithm node (root) -->
          <div class="graph-node algo-node" v-if="fingerprint.algorithm !== 'unknown'">
            <span class="node-icon" :style="{ background: categoryColor('algorithm') }">A</span>
            <span class="node-label">{{ fingerprint.algorithm }}</span>
            <span class="node-conf">{{ (fingerprint.algorithm_confidence * 100).toFixed(0) }}%</span>
          </div>

          <!-- Relationship edges -->
          <div v-for="rel in relationshipEdges" :key="`${rel.from}-${rel.to}`" class="graph-edge">
            <div class="edge-line"></div>
            <div class="edge-label">{{ rel.type }}</div>
            <div class="edge-node from-node">{{ rel.from }}</div>
            <div class="edge-node to-node">{{ rel.to }}</div>
          </div>

          <!-- Canonical nodes by category -->
          <div v-for="(items, cat) in canonicalByCategory" :key="cat" class="graph-cluster">
            <div
              class="cluster-header"
              @click="toggleCat(cat)"
              :style="{ borderLeftColor: categoryColor(cat) }"
            >
              <span class="cluster-icon" :style="{ background: categoryColor(cat) }">{{ categoryIcon(cat) }}</span>
              <span class="cluster-label">{{ cat }} ({{ items.length }})</span>
              <span class="cluster-toggle">{{ expandedCats.has(cat) ? '-' : '+' }}</span>
            </div>
            <div v-if="expandedCats.has(cat)" class="cluster-body">
              <div
                v-for="item in items"
                :key="item.canonical_id"
                :class="['identity-card', { selected: selectedNode === item.canonical_id }]"
                @click="selectedNode = selectedNode === item.canonical_id ? null : item.canonical_id"
              >
                <div class="card-header">
                  <span class="card-id">{{ item.canonical_id }}</span>
                  <div class="card-conf-bar">
                    <div class="card-conf-fill" :style="{ width: confidenceWidth(item.confidence), background: categoryColor(cat) }"></div>
                  </div>
                </div>
                <div class="card-subjects">
                  <span v-for="s in item.subjects" :key="s" class="subject-tag">{{ s }}</span>
                </div>
                <div class="card-params" v-if="selectedNode === item.canonical_id">
                  <div v-for="(v, k) in item.parameters" :key="k" class="param-row">
                    <span class="param-key">{{ k }}:</span>
                    <span class="param-val">{{ typeof v === 'object' ? JSON.stringify(v) : v }}</span>
                  </div>
                </div>
                <div class="card-invariants" v-if="selectedNode === item.canonical_id">
                  <span v-for="inv in item.invariants" :key="inv" class="inv-tag">{{ inv }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Ontology Context -->
      <div v-if="ontology && Object.keys(ontology).length" class="ontology-section">
        <h3>Ontology Context</h3>
        <div class="ontology-grid">
          <div v-for="(info, conceptId) in ontology" :key="conceptId" class="ontology-card">
            <div class="ont-header">
              <span class="ont-id">{{ conceptId }}</span>
              <span class="ont-implication" v-if="info.complexity_implication">
                {{ info.complexity_implication }}
              </span>
            </div>
            <div class="ont-ancestors" v-if="info.ancestors?.length">
              <span class="ont-label">is_a:</span>
              <span v-for="a in info.ancestors" :key="a" class="ont-tag ancestor">{{ a }}</span>
            </div>
            <div class="ont-siblings" v-if="info.siblings?.length">
              <span class="ont-label">sibling:</span>
              <span v-for="s in info.siblings" :key="s" class="ont-tag sibling">{{ s }}</span>
            </div>
            <div class="ont-mistakes" v-if="info.common_mistakes?.length">
              <span class="ont-label">watch:</span>
              <span class="ont-mistake">{{ info.common_mistakes.join(', ') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Variable Archetype Map -->
      <div v-if="Object.keys(fingerprint.variable_archetypes || {}).length" class="var-map">
        <h3>Variable Archetypes</h3>
        <div class="var-grid">
          <div v-for="(archetype, varName) in fingerprint.variable_archetypes" :key="varName" class="var-card">
            <span class="var-name">{{ varName }}</span>
            <span class="var-arrow">→</span>
            <span class="var-archetype">{{ archetype }}</span>
          </div>
        </div>
      </div>

      <!-- Invariant Set -->
      <div v-if="fingerprint.invariant_set?.length" class="invariants">
        <h3>Invariant Set</h3>
        <div class="inv-list">
          <span v-for="inv in fingerprint.invariant_set" :key="inv" class="inv-badge">{{ inv }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.semantic-map {
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
  width: 20px; height: 20px;
  border: 2px solid var(--border, #ddd);
  border-top-color: var(--primary, #4f46e5);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.error-box {
  padding: 10px;
  background: rgba(239,68,68,0.06);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: 6px;
  color: #dc2626;
}

.empty {
  padding: 32px;
  text-align: center;
  color: var(--text-dim, #9ca3af);
}

.empty .hint {
  font-size: 14px;
  margin-top: 4px;
  opacity: 0.7;
}

/* Fingerprint Header */
.fp-header {
  padding: 12px 16px;
  background: linear-gradient(135deg, rgba(139,92,246,0.05), rgba(59,130,246,0.05));
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 8px;
}

.fp-hash {
  font-family: monospace;
  font-size: 20px;
  font-weight: 700;
  color: #8b5cf6;
  letter-spacing: 2px;
}

.fp-signature {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.fp-algo {
  font-weight: 700;
  font-size: 14px;
  color: var(--text, #333);
}

.fp-conf {
  font-size: 14px;
  padding: 1px 6px;
  background: rgba(139,92,246,0.1);
  color: #8b5cf6;
  border-radius: 4px;
  font-weight: 600;
}

.fp-details {
  display: flex;
  gap: 6px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.fp-tag {
  font-size: 14px;
  padding: 2px 8px;
  background: rgba(0,0,0,0.04);
  border-radius: 4px;
  color: var(--text-dim, #888);
}

.fp-tag.complexity {
  background: rgba(245,158,11,0.08);
  color: #d97706;
}

/* Graph Section */
.graph-section h3 {
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 8px;
}

.identity-graph {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* Algorithm root node */
.graph-node.algo-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: linear-gradient(135deg, rgba(139,92,246,0.08), rgba(139,92,246,0.03));
  border: 2px solid #8b5cf6;
  border-radius: 8px;
  font-weight: 700;
}

.node-icon {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 5px;
  color: white;
  font-size: 14px;
  font-weight: 700;
}

.node-label {
  flex: 1;
  font-size: 14px;
}

.node-conf {
  font-size: 14px;
  color: #8b5cf6;
  font-weight: 600;
}

/* Relationship edges */
.graph-edge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 12px;
  font-size: 14px;
}

.edge-line {
  flex: 1;
  height: 1px;
  background: var(--border, #e5e7eb);
}

.edge-label {
  font-size: 14px;
  color: var(--text-dim, #9ca3af);
  font-weight: 600;
  text-transform: uppercase;
}

.edge-node {
  font-family: monospace;
  font-size: 14px;
  color: var(--text-dim, #888);
}

/* Clusters */
.graph-cluster {
  margin-top: 4px;
}

.cluster-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-left: 3px solid #6b7280;
  cursor: pointer;
  user-select: none;
  background: rgba(0,0,0,0.01);
  border-radius: 0 4px 4px 0;
}

.cluster-header:hover { background: rgba(0,0,0,0.03); }

.cluster-icon {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: white;
  font-size: 14px;
  font-weight: 700;
}

.cluster-label {
  flex: 1;
  font-weight: 600;
  font-size: 14px;
  text-transform: capitalize;
}

.cluster-toggle {
  font-size: 14px;
  color: var(--text-dim, #888);
}

.cluster-body {
  padding: 6px 0 6px 28px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* Identity Cards */
.identity-card {
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  padding: 8px 10px;
  cursor: pointer;
  transition: all 0.15s;
}

.identity-card:hover {
  border-color: var(--primary, #4f46e5);
}

.identity-card.selected {
  border-color: var(--primary, #4f46e5);
  background: rgba(79,70,229,0.03);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-id {
  font-family: monospace;
  font-weight: 700;
  font-size: 14px;
  color: var(--text, #333);
}

.card-conf-bar {
  flex: 1;
  height: 4px;
  background: rgba(0,0,0,0.06);
  border-radius: 2px;
  overflow: hidden;
}

.card-conf-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}

.card-subjects {
  display: flex;
  gap: 4px;
  margin-top: 4px;
  flex-wrap: wrap;
}

.subject-tag {
  font-size: 14px;
  padding: 1px 5px;
  background: rgba(0,0,0,0.04);
  border-radius: 3px;
  font-family: monospace;
  color: var(--text-dim, #888);
}

.card-params {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--border, #e5e7eb);
}

.param-row {
  display: flex;
  gap: 6px;
  font-size: 14px;
  padding: 1px 0;
}

.param-key {
  font-weight: 600;
  color: var(--text-dim, #888);
}

.param-val {
  font-family: monospace;
  color: var(--text, #333);
}

.card-invariants {
  display: flex;
  gap: 4px;
  margin-top: 4px;
  flex-wrap: wrap;
}

.inv-tag {
  font-size: 14px;
  padding: 1px 5px;
  background: rgba(16,185,129,0.08);
  color: #059669;
  border-radius: 3px;
}

/* Variable Map */
.var-map h3 {
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 8px;
}

.var-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.var-card {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  font-size: 14px;
}

.var-name {
  font-family: monospace;
  font-weight: 700;
  color: #3b82f6;
}

.var-arrow {
  color: var(--text-dim, #9ca3af);
}

.var-archetype {
  font-family: monospace;
  color: #8b5cf6;
  font-size: 14px;
}

/* Ontology Section */
.ontology-section h3 {
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 8px;
}

.ontology-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ontology-card {
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  padding: 8px 10px;
  background: rgba(139,92,246,0.02);
}

.ont-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.ont-id {
  font-family: monospace;
  font-weight: 700;
  font-size: 14px;
  color: #8b5cf6;
}

.ont-implication {
  font-size: 14px;
  padding: 1px 6px;
  background: rgba(245,158,11,0.08);
  color: #d97706;
  border-radius: 3px;
}

.ont-ancestors, .ont-siblings, .ont-mistakes {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 2px;
  flex-wrap: wrap;
}

.ont-label {
  font-size: 14px;
  color: var(--text-dim, #9ca3af);
  font-weight: 600;
}

.ont-tag {
  font-size: 14px;
  padding: 1px 5px;
  border-radius: 3px;
  font-family: monospace;
}

.ont-tag.ancestor {
  background: rgba(59,130,246,0.08);
  color: #3b82f6;
}

.ont-tag.sibling {
  background: rgba(16,185,129,0.08);
  color: #059669;
}

.ont-mistake {
  font-size: 14px;
  color: #dc2626;
}

/* Invariants */
.invariants h3 {
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 8px;
}

.inv-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.inv-badge {
  font-size: 14px;
  padding: 2px 8px;
  background: rgba(16,185,129,0.08);
  color: #059669;
  border-radius: 4px;
  font-weight: 600;
}
</style>
