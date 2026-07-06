<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { useSemanticModel } from '../composables/useSemanticModel'

const store = useAnalysisStore()
const model = useSemanticModel()

function timeAgo(ts: number): string {
  const diff = Date.now() - ts
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return `${Math.floor(diff / 86400000)} 天前`
}

const resultPreview = computed(() => {
  const value = store.insightResult?.result
  if (value == null) return '无返回值'
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 120 ? `${text.slice(0, 120)}...` : text
})
</script>

<template>
  <div class="insight-panel">
    <section v-if="!store.hasResults" class="welcome">
      <div class="welcome-main">
        <span class="eyebrow">Why-Code-Agent</span>
        <h2>把代码变成可理解的执行故事</h2>
        <p>粘贴代码或选择示例，点击“分析代码”。系统会按真实执行轨迹解释阶段、变量变化、返回值和关键步骤。</p>
      </div>

      <div class="start-grid">
        <div class="start-card">
          <strong>1. 看结论</strong>
          <span>先读“理解代码”，知道这段代码整体在做什么。</span>
        </div>
        <div class="start-card">
          <strong>2. 看语义</strong>
          <span>再进“语义视图”，看阶段、变量角色和数据依赖。</span>
        </div>
        <div class="start-card">
          <strong>3. 看执行</strong>
          <span>最后用“执行回放”逐步跟踪代码行和值变化。</span>
        </div>
      </div>

      <section v-if="store.history.length" class="history-section">
        <div class="section-head">
          <h3>最近分析</h3>
          <button @click="store.clearHistory()">清空</button>
        </div>
        <div class="history-list">
          <button
            v-for="entry in store.history.slice(0, 5)"
            :key="entry.id"
            class="history-item"
            @click="store.loadFromHistory(entry)"
          >
            <span class="history-func">{{ entry.funcName || 'main' }}()</span>
            <span class="history-insight">{{ entry.oneLiner || entry.algorithmType }}</span>
            <span class="history-meta">{{ entry.algorithmType || '代码分析' }} · {{ timeAgo(entry.timestamp) }}</span>
          </button>
        </div>
      </section>
    </section>

    <section v-else class="result">
      <div class="summary">
        <span class="eyebrow">洞察摘要</span>
        <h2>{{ model.algorithmLabel.value }}</h2>
        <p>{{ model.summary.value }}</p>
      </div>

      <div class="result-value">
        <span>返回结果</span>
        <code>{{ resultPreview }}</code>
      </div>

      <div class="metric-grid">
        <div v-for="metric in model.metrics.value" :key="metric.label" class="metric">
          <strong>{{ metric.value }}</strong>
          <span>{{ metric.label }}</span>
        </div>
      </div>

      <div class="phase-list">
        <article v-for="phase in model.phases.value" :key="phase.id" class="phase" :style="{ '--phase': phase.color }">
          <strong>{{ phase.title }}</strong>
          <span>{{ phase.steps.length }} 步 · {{ phase.summary }}</span>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.insight-panel {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
  background: #f8fafc;
}

.welcome,
.result {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 980px;
  margin: 0 auto;
}

.welcome-main,
.summary,
.result-value,
.history-section {
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
  padding: 18px;
}

.eyebrow {
  display: block;
  margin-bottom: 6px;
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

h2, h3, p {
  margin: 0;
}

h2 {
  color: #0f172a;
  font-size: 24px;
}

.welcome-main p,
.summary p {
  margin-top: 8px;
  color: #64748b;
  font-size: 14px;
  line-height: 1.6;
}

.start-grid,
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}

.start-card,
.metric,
.phase {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  padding: 12px;
}

.start-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.start-card strong,
.phase strong {
  color: #0f172a;
}

.start-card span,
.phase span {
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

h3 {
  color: #0f172a;
  font-size: 15px;
}

.section-head button {
  border: none;
  background: none;
  color: #64748b;
  cursor: pointer;
}

.history-list,
.phase-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-item {
  display: grid;
  grid-template-columns: minmax(100px, 160px) minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
}

.history-func {
  color: #2563eb;
  font-weight: 800;
}

.history-insight {
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-meta {
  color: #64748b;
  font-size: 12px;
}

.result-value {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.result-value span {
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

code {
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  overflow-wrap: anywhere;
}

.metric {
  display: flex;
  align-items: baseline;
  gap: 7px;
}

.metric strong {
  color: #0f172a;
  font-size: 20px;
}

.metric span {
  color: #64748b;
  font-size: 12px;
}

.phase {
  border-left: 4px solid var(--phase);
  display: flex;
  flex-direction: column;
  gap: 5px;
}

@media (max-width: 720px) {
  .history-item {
    grid-template-columns: 1fr;
  }
}
</style>
