<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getAllMetrics, resetMetrics } from '../api/analysis'
import type { AllMetrics } from '../api/analysis'

const metrics = ref<AllMetrics | null>(null)
const loading = ref(false)

async function fetchMetrics() {
  loading.value = true
  try {
    metrics.value = await getAllMetrics()
  } catch (e: any) {
    console.error('Failed to fetch metrics', e)
  } finally {
    loading.value = false
  }
}

async function handleReset() {
  await resetMetrics()
  await fetchMetrics()
}

onMounted(fetchMetrics)
</script>

<template>
  <div class="metrics-panel">
    <div class="metrics-header">
      <h3>System Metrics</h3>
      <div class="metrics-actions">
        <button class="refresh-btn" @click="fetchMetrics" :disabled="loading">
          {{ loading ? 'Loading...' : 'Refresh' }}
        </button>
        <button class="reset-btn" @click="handleReset">Reset</button>
      </div>
    </div>

    <div v-if="loading && !metrics" class="loading">Loading metrics...</div>

    <div v-else-if="metrics" class="metrics-content">
      <!-- Query Metrics -->
      <section class="section">
        <h4>Query Performance</h4>
        <div class="stat-grid">
          <div class="stat-card">
            <div class="stat-value">{{ metrics.query.total_queries }}</div>
            <div class="stat-label">Total Queries</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ metrics.query.latency.p50?.toFixed(1) || 0 }}ms</div>
            <div class="stat-label">P50 Latency</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ metrics.query.latency.p95?.toFixed(1) || 0 }}ms</div>
            <div class="stat-label">P95 Latency</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ metrics.query.latency.p99?.toFixed(1) || 0 }}ms</div>
            <div class="stat-label">P99 Latency</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ (metrics.query.cache.hit_rate * 100).toFixed(0) }}%</div>
            <div class="stat-label">Cache Hit Rate</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ metrics.query.errors }}</div>
            <div class="stat-label">Errors</div>
          </div>
        </div>

        <div v-if="Object.keys(metrics.query.by_type).length" class="type-breakdown">
          <h5>By Query Type</h5>
          <div class="type-row" v-for="(stats, type) in metrics.query.by_type" :key="type">
            <span class="type-name">{{ type }}</span>
            <span class="type-count">{{ stats.count }} queries</span>
            <span class="type-latency">{{ stats.avg_ms.toFixed(1) }}ms avg</span>
          </div>
        </div>
      </section>

      <!-- Execution Metrics -->
      <section class="section">
        <h4>Pipeline Stages</h4>
        <div class="stage-list">
          <div v-for="(stats, name) in metrics.execution.stages" :key="name" class="stage-row">
            <span class="stage-name">{{ name }}</span>
            <div class="stage-bar">
              <div class="stage-fill" :style="{ width: Math.min(stats.avg_ms * 5, 100) + '%' }"></div>
            </div>
            <span class="stage-time">{{ stats.avg_ms.toFixed(1) }}ms</span>
            <span class="stage-count">x{{ stats.count }}</span>
          </div>
        </div>
      </section>

      <!-- Endpoint Metrics -->
      <section class="section" v-if="Object.keys(metrics.execution.endpoints).length">
        <h4>Endpoint Latency</h4>
        <div class="endpoint-list">
          <div v-for="(stats, path) in metrics.execution.endpoints" :key="path" class="endpoint-row">
            <span class="endpoint-path">{{ path }}</span>
            <span class="endpoint-time">{{ stats.avg_ms.toFixed(1) }}ms</span>
            <span class="endpoint-count">{{ stats.count }} req</span>
            <span v-if="stats.errors" class="endpoint-errors">{{ stats.errors }} err</span>
          </div>
        </div>
      </section>

      <!-- Agent Metrics -->
      <section class="section">
        <h4>Agent Performance</h4>
        <div class="stat-grid">
          <div class="stat-card">
            <div class="stat-value">{{ metrics.agent.total_runs }}</div>
            <div class="stat-label">Total Runs</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ metrics.agent.reasoning.avg_hypotheses.toFixed(1) }}</div>
            <div class="stat-label">Avg Hypotheses</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ metrics.agent.reasoning.avg_depth.toFixed(1) }}</div>
            <div class="stat-label">Avg Depth</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ (metrics.agent.actions.success_rate * 100).toFixed(0) }}%</div>
            <div class="stat-label">Action Success</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ metrics.agent.performance.avg_duration_ms.toFixed(0) }}ms</div>
            <div class="stat-label">Avg Duration</div>
          </div>
        </div>
      </section>

      <div class="uptime">Uptime: {{ metrics.query.uptime_seconds.toFixed(0) }}s</div>
    </div>
  </div>
</template>

<style scoped>
.metrics-panel { padding: 16px; overflow-y: auto; height: 100%; }
.metrics-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.metrics-header h3 { margin: 0; font-size: 18px; }
.metrics-actions { display: flex; gap: 8px; }
.refresh-btn, .reset-btn {
  padding: 6px 12px; border: 1px solid var(--border, #333); border-radius: 6px;
  background: var(--bg-secondary, #1a1a2e); color: inherit; cursor: pointer; font-size: 13px;
}
.refresh-btn:disabled { opacity: 0.5; }
.reset-btn { border-color: #f44336; color: #f44336; }
.loading { padding: 20px; text-align: center; color: var(--text-secondary, #888); }
.section { margin-bottom: 20px; }
.section h4 { margin: 0 0 10px; font-size: 14px; color: var(--text-secondary, #888); }
.section h5 { margin: 10px 0 6px; font-size: 12px; color: var(--text-secondary, #666); }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 8px; }
.stat-card { padding: 12px; background: var(--bg-secondary, #1a1a2e); border-radius: 8px; text-align: center; }
.stat-value { font-size: 20px; font-weight: 700; }
.stat-label { font-size: 11px; color: var(--text-secondary, #888); margin-top: 4px; }
.type-breakdown { margin-top: 10px; }
.type-row { display: flex; gap: 12px; padding: 4px 8px; font-size: 13px; }
.type-name { font-weight: 500; min-width: 80px; }
.type-count { color: var(--text-secondary, #888); }
.type-latency { color: var(--accent, #4fc3f7); }
.stage-list { display: flex; flex-direction: column; gap: 6px; }
.stage-row { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.stage-name { min-width: 120px; font-weight: 500; }
.stage-bar { flex: 1; height: 8px; background: var(--bg-secondary, #1a1a2e); border-radius: 4px; overflow: hidden; }
.stage-fill { height: 100%; background: var(--accent, #4fc3f7); border-radius: 4px; transition: width 0.3s; }
.stage-time { min-width: 60px; text-align: right; }
.stage-count { min-width: 40px; color: var(--text-secondary, #888); font-size: 12px; }
.endpoint-list { display: flex; flex-direction: column; gap: 4px; }
.endpoint-row { display: flex; gap: 12px; padding: 4px 8px; font-size: 13px; background: var(--bg-secondary, #1a1a2e); border-radius: 4px; }
.endpoint-path { flex: 1; font-family: monospace; font-size: 12px; }
.endpoint-time { min-width: 60px; text-align: right; }
.endpoint-count { min-width: 50px; color: var(--text-secondary, #888); }
.endpoint-errors { color: #f44336; }
.uptime { font-size: 12px; color: var(--text-secondary, #666); margin-top: 12px; }
</style>
