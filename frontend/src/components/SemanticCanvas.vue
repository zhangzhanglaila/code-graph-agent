<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { useSemanticModel } from '../composables/useSemanticModel'

const store = useAnalysisStore()
const model = useSemanticModel()

const selectedStep = ref<number | null>(null)
const selectedPhase = ref<string | null>(null)

const activeStep = computed(() => {
  if (selectedStep.value != null) {
    return model.semanticSteps.value.find(step => step.index === selectedStep.value) || null
  }
  return model.semanticSteps.value[store.safeStep] || model.semanticSteps.value[0] || null
})

const activePhase = computed(() => {
  if (selectedPhase.value) {
    return model.phases.value.find(phase => phase.id === selectedPhase.value) || null
  }
  const kind = activeStep.value?.kind
  return model.phases.value.find(phase => phase.id === kind) || model.phases.value[0] || null
})

const visibleSteps = computed(() => {
  const phase = activePhase.value
  if (!phase) return model.semanticSteps.value.slice(0, 12)
  const phaseSteps = new Set(phase.steps)
  const related = model.semanticSteps.value.filter(step => phaseSteps.has(step.index))
  return related.length > 14 ? related.slice(0, 14) : related
})

const topVariables = computed(() => model.variableRoles.value.slice(0, 8))
const topLinks = computed(() => model.semanticLinks.value.slice(0, 10))

function selectStep(index: number) {
  selectedStep.value = index
  const step = model.semanticSteps.value.find(item => item.index === index)
  if (step) selectedPhase.value = step.kind
  store.currentStep = Math.max(0, model.steps.value.findIndex(item => item.index === index))
  const raw = model.steps.value.find(item => item.index === index)
  store.highlightedLine = raw?.line || 0
}

function selectPhase(id: string) {
  selectedPhase.value = selectedPhase.value === id ? null : id
  const phase = model.phases.value.find(item => item.id === id)
  if (phase?.steps.length) selectStep(phase.steps[0])
}

function phaseWidth(count: number) {
  const max = Math.max(...model.phases.value.map(phase => phase.steps.length), 1)
  return `${Math.max(18, Math.round((count / max) * 100))}%`
}

function confidenceWidth(value: number) {
  return `${Math.round(value * 100)}%`
}

function shortValue(value: string) {
  if (!value) return '无快照'
  return value.length > 72 ? `${value.slice(0, 72)}...` : value
}

watch(() => store.safeStep, (idx) => {
  const step = model.semanticSteps.value[idx]
  if (!step || selectedStep.value != null) return
  selectedPhase.value = step.kind
})
</script>

<template>
  <div class="semantic-canvas">
    <div v-if="!store.hasResults" class="empty-state">
      <div class="empty-title">还没有执行轨迹</div>
      <div class="empty-copy">先运行分析，语义画布会从真实 timeline、变量变化和依赖边生成。</div>
    </div>

    <template v-else>
      <section class="overview-band">
        <div class="overview-main">
          <span class="eyebrow">执行语义</span>
          <h2>{{ model.algorithmLabel.value }}</h2>
          <p>{{ model.summary.value }}</p>
        </div>
        <div class="metric-grid">
          <div v-for="metric in model.metrics.value" :key="metric.label" class="metric-cell">
            <span class="metric-value">{{ metric.value }}</span>
            <span class="metric-label">{{ metric.label }}</span>
          </div>
        </div>
      </section>

      <section class="phase-board">
        <button
          v-for="phase in model.phases.value"
          :key="phase.id"
          class="phase-lane"
          :class="{ active: activePhase?.id === phase.id }"
          :style="{ '--phase': phase.color }"
          @click="selectPhase(phase.id)"
        >
          <span class="phase-head">
            <span class="phase-dot"></span>
            <span class="phase-title">{{ phase.title }}</span>
            <span class="phase-count">{{ phase.steps.length }}</span>
          </span>
          <span class="phase-summary">{{ phase.summary }}</span>
          <span class="phase-bar">
            <span class="phase-fill" :style="{ width: phaseWidth(phase.steps.length) }"></span>
          </span>
          <span class="phase-signals">
            <span v-for="signal in phase.signals" :key="signal">{{ signal }}</span>
          </span>
        </button>
      </section>

      <div class="workspace-grid">
        <section class="rail-panel">
          <div class="panel-header">
            <div>
              <h3>执行语义轨道</h3>
              <p>{{ activePhase?.title || '全部阶段' }}中的关键步骤</p>
            </div>
            <button class="clear-btn" @click="selectedStep = null">跟随回放</button>
          </div>

          <div class="execution-rail">
            <button
              v-for="step in visibleSteps"
              :key="step.index"
              class="step-node"
              :class="{ active: activeStep?.index === step.index }"
              :style="{ '--phase': model.phases.value.find(p => p.id === step.kind)?.color || '#475569' }"
              @click="selectStep(step.index)"
            >
              <span class="step-index">#{{ step.index }}</span>
              <span class="step-title">{{ step.title }}</span>
              <span class="step-code">{{ step.code }}</span>
              <span class="step-vars" v-if="step.variables.length">
                {{ step.variables.slice(0, 4).join(', ') }}
              </span>
            </button>
          </div>
        </section>

        <aside class="detail-panel">
          <div class="panel-header compact">
            <div>
              <h3>当前语义证据</h3>
              <p v-if="activeStep">第 {{ activeStep.index }} 步，代码行 {{ activeStep.line || '-' }}</p>
            </div>
          </div>

          <div v-if="activeStep" class="detail-card">
            <span class="detail-kind">{{ activeStep.title }}</span>
            <code>{{ activeStep.code }}</code>
            <p>{{ activeStep.evidence }}</p>
            <div class="io-grid">
              <div>
                <span class="io-label">读取</span>
                <strong>{{ activeStep.reads.join(', ') || '无' }}</strong>
              </div>
              <div>
                <span class="io-label">写入</span>
                <strong>{{ activeStep.writes.join(', ') || '无' }}</strong>
              </div>
            </div>
          </div>

          <div class="hot-lines">
            <h4>热代码行</h4>
            <button
              v-for="item in model.hotLines.value"
              :key="item.line"
              class="hot-line"
              @click="store.highlightedLine = item.line"
            >
              <span>Line {{ item.line }}</span>
              <strong>{{ item.count }} 次</strong>
            </button>
          </div>
        </aside>
      </div>

      <div class="lower-grid">
        <section class="role-panel">
          <div class="panel-header">
            <div>
              <h3>变量角色板</h3>
              <p>角色由写入频次、循环位置、返回语句和值形态推导</p>
            </div>
          </div>
          <div class="role-grid">
            <article
              v-for="variable in topVariables"
              :key="variable.name"
              class="role-card"
              :style="{ '--role': variable.color }"
            >
              <div class="role-head">
                <span class="role-name">{{ variable.name }}</span>
                <span class="role-kind">{{ variable.role }}</span>
              </div>
              <div class="confidence">
                <span :style="{ width: confidenceWidth(variable.confidence) }"></span>
              </div>
              <div class="role-stats">
                <span>写 {{ variable.changes }}</span>
                <span>读 {{ variable.reads }}</span>
                <span>#{{ variable.firstStep }}-#{{ variable.lastStep }}</span>
              </div>
              <p class="role-value">{{ shortValue(variable.lastValue) }}</p>
              <p class="role-evidence">{{ variable.evidence.join('；') }}</p>
            </article>
          </div>
        </section>

        <section class="dependency-panel">
          <div class="panel-header">
            <div>
              <h3>因果流</h3>
              <p>谁写入变量，后续哪一步读取它</p>
            </div>
          </div>
          <div v-if="topLinks.length" class="link-list">
            <button
              v-for="link in topLinks"
              :key="`${link.from}-${link.to}-${link.variable}`"
              class="link-row"
              @click="selectStep(link.to)"
            >
              <span class="from">#{{ link.from }}</span>
              <span class="line"></span>
              <span class="var">{{ link.variable }}</span>
              <span class="line"></span>
              <span class="to">#{{ link.to }}</span>
            </button>
          </div>
          <div v-else class="no-links">当前执行没有形成可见的数据依赖边。</div>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.semantic-canvas {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 100%;
  padding: 14px;
  color: var(--text);
  background: #f8fafc;
}

.empty-state {
  display: grid;
  place-content: center;
  min-height: 320px;
  gap: 8px;
  color: #475569;
  text-align: center;
}

.empty-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.empty-copy {
  font-size: 13px;
}

.overview-band {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(320px, 540px);
  gap: 16px;
  padding: 18px;
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
}

.overview-main {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.eyebrow {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
}

h2, h3, h4, p {
  margin: 0;
}

h2 {
  font-size: 24px;
  color: #0f172a;
}

.overview-main p,
.panel-header p {
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.metric-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
}

.metric-value {
  font-size: 20px;
  font-weight: 800;
  color: #0f172a;
}

.metric-label {
  font-size: 12px;
  color: #64748b;
}

.phase-board {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px;
}

.phase-lane {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 156px;
  padding: 12px;
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
  color: #334155;
  text-align: left;
  cursor: pointer;
}

.phase-lane.active {
  border-color: var(--phase);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--phase), transparent 82%);
}

.phase-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.phase-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--phase);
}

.phase-title {
  flex: 1;
  font-weight: 800;
  color: #0f172a;
}

.phase-count {
  min-width: 28px;
  padding: 2px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--phase), white 86%);
  color: var(--phase);
  font-size: 12px;
  font-weight: 800;
  text-align: center;
}

.phase-summary {
  min-height: 34px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.phase-bar {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.phase-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--phase);
}

.phase-signals {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.phase-signals span {
  max-width: 100%;
  padding: 3px 6px;
  border-radius: 5px;
  background: #f1f5f9;
  color: #475569;
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.workspace-grid,
.lower-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(300px, 0.8fr);
  gap: 12px;
  min-height: 0;
}

.rail-panel,
.detail-panel,
.role-panel,
.dependency-panel {
  min-width: 0;
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.panel-header.compact {
  padding-bottom: 10px;
}

h3 {
  font-size: 15px;
  color: #0f172a;
}

h4 {
  font-size: 13px;
  color: #0f172a;
}

.clear-btn {
  flex: 0 0 auto;
  height: 30px;
  padding: 0 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #ffffff;
  color: #334155;
  cursor: pointer;
}

.execution-rail {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 8px;
  padding: 12px;
}

.step-node {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 8px;
  min-height: 94px;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-left: 4px solid var(--phase);
  border-radius: 7px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
}

.step-node.active {
  background: color-mix(in srgb, var(--phase), white 92%);
  border-color: var(--phase);
}

.step-index {
  grid-row: span 3;
  color: var(--phase);
  font-weight: 900;
  font-size: 12px;
}

.step-title {
  color: #0f172a;
  font-weight: 800;
  font-size: 13px;
}

.step-code {
  min-width: 0;
  color: #334155;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.step-vars {
  color: #64748b;
  font-size: 11px;
}

.detail-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 12px;
  padding: 12px;
  border-radius: 7px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.detail-kind {
  font-size: 12px;
  font-weight: 800;
  color: #2563eb;
}

code {
  display: block;
  padding: 8px;
  border-radius: 6px;
  background: #0f172a;
  color: #e2e8f0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  overflow-x: auto;
}

.detail-card p {
  color: #475569;
  font-size: 13px;
  line-height: 1.5;
}

.io-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.io-grid > div {
  min-width: 0;
  padding: 8px;
  border-radius: 6px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
}

.io-label {
  display: block;
  margin-bottom: 4px;
  color: #64748b;
  font-size: 11px;
}

.io-grid strong {
  color: #0f172a;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.hot-lines {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 0 12px 12px;
}

.hot-line {
  display: flex;
  justify-content: space-between;
  padding: 7px 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
  color: #334155;
  cursor: pointer;
}

.role-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  padding: 12px;
}

.role-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 150px;
  padding: 11px;
  border: 1px solid #e2e8f0;
  border-top: 4px solid var(--role);
  border-radius: 7px;
  background: #ffffff;
}

.role-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: flex-start;
}

.role-name {
  min-width: 0;
  color: #0f172a;
  font-weight: 900;
  overflow-wrap: anywhere;
}

.role-kind {
  flex: 0 0 auto;
  max-width: 108px;
  padding: 3px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--role), white 86%);
  color: var(--role);
  font-size: 11px;
  font-weight: 800;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.confidence {
  height: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.confidence span {
  display: block;
  height: 100%;
  background: var(--role);
}

.role-stats {
  display: flex;
  gap: 8px;
  color: #64748b;
  font-size: 11px;
}

.role-value,
.role-evidence {
  color: #475569;
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.role-value {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: #334155;
}

.link-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 12px;
}

.link-row {
  display: grid;
  grid-template-columns: auto 1fr auto 1fr auto;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
  cursor: pointer;
}

.link-row:hover {
  border-color: #94a3b8;
}

.from,
.to {
  font-weight: 900;
  color: #0f172a;
}

.var {
  padding: 2px 7px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #0369a1;
  font-size: 12px;
  font-weight: 800;
}

.line {
  height: 1px;
  background: #cbd5e1;
}

.no-links {
  padding: 12px;
  color: #64748b;
  font-size: 13px;
}

@media (max-width: 1100px) {
  .overview-band,
  .workspace-grid,
  .lower-grid {
    grid-template-columns: 1fr;
  }
}
</style>
