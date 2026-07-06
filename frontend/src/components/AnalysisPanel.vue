<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { useSemanticModel } from '../composables/useSemanticModel'
import type { SemanticStep } from '../composables/useSemanticModel'

const store = useAnalysisStore()
const model = useSemanticModel()

const resultPreview = computed(() => {
  const value = store.insightResult?.result
  if (value == null) return '无返回值'
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 140 ? `${text.slice(0, 140)}...` : text
})

const importantSteps = computed(() => {
  const seen = new Set<number>()
  const picked: SemanticStep[] = []
  for (const kind of ['input', 'setup', 'loop', 'branch', 'mutation', 'output']) {
    const step = model.semanticSteps.value.find(item => item.kind === kind)
    if (step && !seen.has(step.index)) {
      seen.add(step.index)
      picked.push(step)
    }
  }
  return picked.slice(0, 8)
})

const plainExplanation = computed(() => {
  const roles = model.variableRoles.value.slice(0, 4)
  const roleText = roles.map(role => `${role.name} 是${role.role}`).join('，')
  return `${model.algorithmLabel.value}。代码先准备运行状态，然后沿着执行轨迹逐步更新变量，最后把结果返回。${roleText ? `其中 ${roleText}。` : ''}`
})

function jumpToStep(index: number) {
  const rawIndex = model.steps.value.findIndex(step => step.index === index)
  if (rawIndex >= 0) store.currentStep = rawIndex
  const step = model.steps.value[rawIndex]
  store.highlightedLine = step?.line || 0
  store.activeTab = 'replay'
}
</script>

<template>
  <div class="understanding-panel">
    <section class="summary">
      <div>
        <span class="eyebrow">从零理解</span>
        <h2>{{ model.algorithmLabel.value }}</h2>
        <p>{{ plainExplanation }}</p>
      </div>
      <div class="result-box">
        <span>返回结果</span>
        <code>{{ resultPreview }}</code>
      </div>
    </section>

    <section class="metrics-row">
      <div v-for="metric in model.metrics.value" :key="metric.label" class="metric">
        <strong>{{ metric.value }}</strong>
        <span>{{ metric.label }}</span>
      </div>
    </section>

    <div class="main-grid">
      <section class="section">
        <div class="section-head">
          <h3>代码做了什么</h3>
          <p>按真实执行顺序，把代码拆成可理解的阶段。</p>
        </div>
        <div class="phase-list">
          <article
            v-for="phase in model.phases.value"
            :key="phase.id"
            class="phase-item"
            :style="{ '--phase': phase.color }"
          >
            <div class="phase-title">
              <span></span>
              <strong>{{ phase.title }}</strong>
              <em>{{ phase.steps.length }} 步</em>
            </div>
            <p>{{ phase.summary }}</p>
            <div class="phase-meta">
              <span v-if="phase.lines.length">代码行 {{ phase.lines.join(', ') }}</span>
              <span v-if="phase.variables.length">变量 {{ phase.variables.slice(0, 5).join(', ') }}</span>
            </div>
          </article>
        </div>
      </section>

      <section class="section">
        <div class="section-head">
          <h3>变量怎么变</h3>
          <p>先看角色，再看值从哪里变到哪里。</p>
        </div>
        <div class="var-list">
          <article
            v-for="variable in model.variableRoles.value.slice(0, 7)"
            :key="variable.name"
            class="var-item"
            :style="{ '--role': variable.color }"
          >
            <div class="var-title">
              <strong>{{ variable.name }}</strong>
              <span>{{ variable.role }}</span>
            </div>
            <div class="var-flow">
              <code>{{ variable.firstValue || '初始未记录' }}</code>
              <b>-></b>
              <code>{{ variable.lastValue || '最终未记录' }}</code>
            </div>
            <p>{{ variable.evidence.join('；') }}</p>
          </article>
        </div>
      </section>
    </div>

    <section class="section">
      <div class="section-head">
        <h3>关键步骤</h3>
        <p>点一步会跳到执行回放，并高亮对应代码行。</p>
      </div>
      <div class="step-grid">
        <button
          v-for="step in importantSteps"
          :key="step.index"
          class="step-card"
          @click="jumpToStep(step.index)"
        >
          <span>#{{ step.index }}</span>
          <strong>{{ step.title }}</strong>
          <code>{{ step.code }}</code>
          <em>{{ step.evidence }}</em>
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.understanding-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 100%;
  padding: 14px;
  background: #f8fafc;
  color: var(--text);
}

.summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 380px);
  gap: 16px;
  padding: 18px;
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
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

.summary p,
.section-head p,
.phase-item p,
.var-item p,
.step-card em {
  color: #64748b;
  font-size: 13px;
  line-height: 1.55;
}

.result-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #f8fafc;
}

.result-box span {
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.result-box code {
  color: #0f172a;
}

.metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
}

.metric {
  display: flex;
  align-items: baseline;
  gap: 7px;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #ffffff;
}

.metric strong {
  color: #0f172a;
  font-size: 20px;
}

.metric span {
  color: #64748b;
  font-size: 12px;
}

.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}

.section {
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
}

.section-head {
  padding: 12px;
  border-bottom: 1px solid #e2e8f0;
}

h3 {
  color: #0f172a;
  font-size: 15px;
}

.phase-list,
.var-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
}

.phase-item,
.var-item {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-left: 4px solid var(--phase, var(--role));
  border-radius: 7px;
  background: #ffffff;
}

.phase-title,
.var-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.phase-title span {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--phase);
}

.phase-title strong,
.var-title strong {
  flex: 1;
  color: #0f172a;
}

.phase-title em,
.var-title span {
  flex: 0 0 auto;
  padding: 3px 7px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--phase, var(--role)), white 86%);
  color: var(--phase, var(--role));
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}

.phase-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.phase-meta span {
  padding: 3px 6px;
  border-radius: 5px;
  background: #f1f5f9;
  color: #475569;
  font-size: 11px;
}

.var-flow {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 7px;
  align-items: center;
}

.var-flow code {
  min-width: 0;
  padding: 6px;
  border-radius: 5px;
  background: #f8fafc;
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.var-flow b {
  color: #94a3b8;
}

.step-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 9px;
  padding: 12px;
}

.step-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 5px 8px;
  min-height: 112px;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
}

.step-card:hover {
  border-color: #2563eb;
}

.step-card span {
  grid-row: span 3;
  color: #2563eb;
  font-weight: 900;
}

.step-card strong {
  color: #0f172a;
}

.step-card code {
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.step-card em {
  font-style: normal;
}

@media (max-width: 1100px) {
  .summary,
  .main-grid {
    grid-template-columns: 1fr;
  }
}
</style>
