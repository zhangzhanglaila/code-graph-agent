<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()

const result = computed(() => store.githubResult)
const summary = computed(() => result.value?.summary)
const files = computed(() => result.value?.files || [])
const successfulFiles = computed(() => files.value.filter(f => !f.error))
const failedFiles = computed(() => files.value.filter(f => f.error))

// Import graph
const importGraph = computed(() => store.importGraph)
const importStats = computed(() => importGraph.value?.stats)
const importEdges = computed(() => importGraph.value?.edges || [])
const externalDeps = computed(() => importGraph.value?.external_deps || [])

function loadFileCode(file: any) {
  // For now, just show the insight
  // In a real implementation, we'd fetch the actual code
  store.setCode(`# ${file.file}\n# ${file.insight?.one_liner || 'No insight available'}`)
}
</script>

<template>
  <div class="github-panel" v-if="result">
    <!-- Header -->
    <div class="gh-header">
      <span class="gh-icon">&#x1F4C1;</span>
      <span class="gh-title">GitHub 仓库分析</span>
      <span class="gh-url">{{ result.repo_url }}</span>
    </div>

    <!-- Summary -->
    <div v-if="summary" class="gh-summary">
      <div class="summary-grid">
        <div class="summary-card">
          <span class="summary-value">{{ summary.total_files }}</span>
          <span class="summary-label">文件数</span>
        </div>
        <div class="summary-card">
          <span class="summary-value">{{ summary.analyzed_files }}</span>
          <span class="summary-label">已分析</span>
        </div>
        <div class="summary-card">
          <span class="summary-value">{{ summary.total_lines }}</span>
          <span class="summary-label">代码行</span>
        </div>
        <div class="summary-card">
          <span class="summary-value">{{ summary.total_execution_steps }}</span>
          <span class="summary-label">执行步骤</span>
        </div>
      </div>

      <!-- Top Patterns -->
      <div v-if="summary.top_patterns?.length" class="patterns-section">
        <span class="patterns-title">检测到的模式:</span>
        <div class="patterns-list">
          <span v-for="p in summary.top_patterns" :key="p.name" class="pattern-chip">
            {{ p.name }} ({{ p.count }})
          </span>
        </div>
      </div>
    </div>

    <!-- File List -->
    <div class="gh-files">
      <div class="files-title">
        <span>文件分析结果</span>
        <span class="files-count">{{ successfulFiles.length }} / {{ files.length }} 成功</span>
      </div>

      <div v-for="(file, i) in files" :key="i"
        :class="['file-card', { error: file.error }]"
        @click="!file.error && loadFileCode(file)">
        <div class="file-header">
          <span class="file-name">{{ file.file }}</span>
          <span v-if="file.code_lines" class="file-lines">{{ file.code_lines }} 行</span>
          <span v-if="file.total_steps" class="file-steps">{{ file.total_steps }} 步</span>
        </div>

        <div v-if="file.error" class="file-error">
          {{ file.error }}
        </div>

        <div v-else-if="file.insight" class="file-insight">
          <div class="insight-one-liner">{{ file.insight.one_liner }}</div>
          <div v-if="file.insight.algorithm_type" class="insight-type">
            {{ file.insight.algorithm_type }}
          </div>
          <div v-if="file.insight.patterns?.length" class="insight-patterns">
            <span v-for="p in file.insight.patterns" :key="p.name" class="insight-pattern">
              {{ p.name }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Import Graph Section -->
    <div v-if="importGraph?.success" class="import-section">
      <div class="import-header">
        <span class="import-title">Import Dependency Graph</span>
        <span class="import-stats">
          {{ importStats?.total_files }} files, {{ importStats?.total_edges }} imports, {{ importStats?.external_deps }} external deps
        </span>
      </div>

      <!-- Most imported files -->
      <div v-if="importStats?.most_imported?.length" class="import-ranking">
        <span class="ranking-title">Most imported:</span>
        <div class="ranking-list">
          <span v-for="f in importStats.most_imported" :key="f.file" class="ranking-chip">
            {{ f.file }} ({{ f.count }})
          </span>
        </div>
      </div>

      <!-- External dependencies -->
      <div v-if="externalDeps.length" class="external-deps">
        <span class="deps-title">External dependencies:</span>
        <div class="deps-list">
          <span v-for="dep in externalDeps.slice(0, 15)" :key="dep" class="dep-chip">
            {{ dep }}
          </span>
          <span v-if="externalDeps.length > 15" class="dep-more">+{{ externalDeps.length - 15 }} more</span>
        </div>
      </div>

      <!-- Import edges (top 10) -->
      <div v-if="importEdges.length" class="import-edges">
        <span class="edges-title">Dependencies:</span>
        <div class="edges-list">
          <div v-for="(edge, i) in importEdges.slice(0, 10)" :key="i" class="edge-row">
            <span class="edge-from">{{ edge.from }}</span>
            <span class="edge-arrow">→</span>
            <span class="edge-to">{{ edge.to }}</span>
            <span v-if="edge.name" class="edge-name">{{ edge.name }}</span>
          </div>
          <div v-if="importEdges.length > 10" class="edge-more">
            +{{ importEdges.length - 10 }} more dependencies
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Empty state -->
  <div v-else class="github-empty">
    <span class="empty-icon">&#x1F4C1;</span>
    <span class="empty-text">输入 GitHub 仓库 URL 开始分析</span>
  </div>
</template>

<style scoped>
.github-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.gh-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: linear-gradient(135deg, rgba(59,130,246,0.06), rgba(99,102,241,0.06));
  border: 1px solid rgba(59,130,246,0.15);
  border-radius: 8px;
}

.gh-icon { font-size: 20px; }
.gh-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--primary);
}
.gh-url {
  font-size: 12px;
  color: var(--text-muted);
  margin-left: auto;
  font-family: monospace;
}

.gh-summary {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px;
  background: rgba(148,163,184,0.04);
  border: 1px solid rgba(148,163,184,0.12);
  border-radius: 6px;
}

.summary-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--primary);
}

.summary-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.patterns-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.patterns-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.patterns-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.pattern-chip {
  font-size: 11px;
  padding: 3px 8px;
  background: rgba(139,92,246,0.08);
  color: #8b5cf6;
  border-radius: 4px;
  font-weight: 600;
}

.gh-files {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.files-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.files-count {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 400;
}

.file-card {
  padding: 10px 12px;
  background: rgba(148,163,184,0.04);
  border: 1px solid rgba(148,163,184,0.12);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.file-card:hover {
  background: rgba(148,163,184,0.08);
  border-color: rgba(148,163,184,0.2);
}

.file-card.error {
  border-color: rgba(239,68,68,0.2);
  background: rgba(239,68,68,0.04);
  cursor: default;
}

.file-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.file-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--highlight);
  font-family: monospace;
}

.file-lines, .file-steps {
  font-size: 10px;
  color: var(--text-muted);
  padding: 1px 4px;
  background: rgba(148,163,184,0.08);
  border-radius: 3px;
}

.file-error {
  font-size: 11px;
  color: var(--error);
}

.file-insight {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.insight-one-liner {
  font-size: 12px;
  color: var(--text);
  line-height: 1.4;
}

.insight-type {
  font-size: 10px;
  color: var(--primary);
  font-weight: 600;
  padding: 1px 6px;
  background: rgba(59,130,246,0.08);
  border-radius: 3px;
  align-self: flex-start;
}

.insight-patterns {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 2px;
}

.insight-pattern {
  font-size: 10px;
  color: #8b5cf6;
  padding: 1px 4px;
  background: rgba(139,92,246,0.06);
  border-radius: 2px;
}

.github-empty {
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

.empty-text {
  font-size: 14px;
}

/* ─── Import Graph Section ────────────────────────────── */
.import-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  background: rgba(139, 92, 246, 0.04);
  border: 1px solid rgba(139, 92, 246, 0.15);
  border-radius: 8px;
}

.import-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.import-title {
  font-size: 14px;
  font-weight: 700;
  color: #8b5cf6;
}

.import-stats {
  font-size: 11px;
  color: var(--text-muted);
  font-family: monospace;
}

.import-ranking, .external-deps, .import-edges {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ranking-title, .deps-title, .edges-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text);
}

.ranking-list, .deps-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.ranking-chip {
  font-size: 10px;
  padding: 2px 6px;
  background: rgba(59, 130, 246, 0.08);
  color: var(--primary);
  border-radius: 3px;
  font-family: monospace;
}

.dep-chip {
  font-size: 10px;
  padding: 2px 6px;
  background: rgba(245, 158, 11, 0.08);
  color: #f59e0b;
  border-radius: 3px;
  font-family: monospace;
}

.dep-more {
  font-size: 10px;
  color: var(--text-muted);
}

.edges-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.edge-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-family: monospace;
}

.edge-from {
  color: var(--primary);
}

.edge-arrow {
  color: var(--text-muted);
}

.edge-to {
  color: #10b981;
}

.edge-name {
  font-size: 10px;
  color: var(--text-muted);
  padding: 0 4px;
  background: rgba(148, 163, 184, 0.08);
  border-radius: 2px;
}

.edge-more {
  font-size: 10px;
  color: var(--text-muted);
}
</style>
