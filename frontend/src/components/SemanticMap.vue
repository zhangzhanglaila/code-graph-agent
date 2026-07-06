<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { useSemanticModel } from '../composables/useSemanticModel'

const store = useAnalysisStore()
const model = useSemanticModel()
const selectedVariable = ref<string | null>(null)

const focusedVariable = computed(() => {
  if (!selectedVariable.value) return model.variableRoles.value[0] || null
  return model.variableRoles.value.find(v => v.name === selectedVariable.value) || null
})

const variableSteps = computed(() => {
  const variable = focusedVariable.value?.name
  if (!variable) return []
  return model.semanticSteps.value.filter(step => step.variables.includes(variable)).slice(0, 18)
})

const phaseConnections = computed(() => {
  return model.phases.value.map(phase => ({
    ...phase,
    variables: phase.variables
      .map(name => model.variableRoles.value.find(role => role.name === name))
      .filter(Boolean)
      .slice(0, 6),
  }))
})

function pickVariable(name: string) {
  selectedVariable.value = selectedVariable.value === name ? null : name
}

function jumpToStep(index: number) {
  const rawIndex = model.steps.value.findIndex(step => step.index === index)
  if (rawIndex >= 0) store.currentStep = rawIndex
  const step = model.steps.value[rawIndex]
  store.highlightedLine = step?.line || 0
}

function short(value: string) {
  if (!value) return '无快照'
  return value.length > 96 ? `${value.slice(0, 96)}...` : value
}
</script>

<template>
  <div class="semantic-map">
    <div v-if="!store.hasResults" class="empty-state">
      <div class="empty-title">语义地图等待执行数据</div>
      <div class="empty-copy">运行分析后，这里会按真实代码轨迹生成概念、变量角色和依赖证据。</div>
    </div>

    <template v-else>
      <section class="map-header">
        <div>
          <span class="eyebrow">概念地图</span>
          <h2>{{ model.algorithmLabel.value }}</h2>
          <p>{{ model.summary.value }}</p>
        </div>
        <div class="compact-metrics">
          <span v-for="metric in model.metrics.value" :key="metric.label">
            <strong>{{ metric.value }}</strong>{{ metric.label }}
          </span>
        </div>
      </section>

      <section class="concept-grid">
        <article v-for="phase in phaseConnections" :key="phase.id" class="concept-card" :style="{ '--phase': phase.color }">
          <div class="concept-head">
            <span class="phase-marker"></span>
            <h3>{{ phase.title }}</h3>
            <strong>{{ phase.steps.length }}</strong>
          </div>
          <p>{{ phase.summary }}</p>
          <div class="concept-lines">
            <span v-for="line in phase.lines.slice(0, 8)" :key="line">Line {{ line }}</span>
          </div>
          <div class="concept-vars">
            <button
              v-for="variable in phase.variables"
              :key="variable!.name"
              @click="pickVariable(variable!.name)"
              :class="{ active: focusedVariable?.name === variable!.name }"
            >
              {{ variable!.name }} / {{ variable!.role }}
            </button>
          </div>
        </article>
      </section>

      <div class="map-body">
        <section class="inventory-panel">
          <div class="panel-title">
            <h3>变量语义清单</h3>
            <p>每个角色都由执行轨迹推导，不再依赖后端身份猜测。</p>
          </div>
          <div class="variable-list">
            <button
              v-for="variable in model.variableRoles.value"
              :key="variable.name"
              class="variable-row"
              :class="{ active: focusedVariable?.name === variable.name }"
              :style="{ '--role': variable.color }"
              @click="pickVariable(variable.name)"
            >
              <span class="var-dot"></span>
              <span class="var-main">
                <strong>{{ variable.name }}</strong>
                <small>{{ variable.role }}</small>
              </span>
              <span class="var-score">{{ Math.round(variable.confidence * 100) }}%</span>
            </button>
          </div>
        </section>

        <section class="focus-panel">
          <div class="panel-title">
            <h3>变量证据</h3>
            <p v-if="focusedVariable">{{ focusedVariable.name }} 在执行过程中的角色和流动。</p>
          </div>

          <div v-if="focusedVariable" class="focus-card" :style="{ '--role': focusedVariable.color }">
            <div class="focus-head">
              <span>{{ focusedVariable.name }}</span>
              <strong>{{ focusedVariable.role }}</strong>
            </div>
            <div class="focus-stats">
              <span>写入 {{ focusedVariable.changes }}</span>
              <span>读取 {{ focusedVariable.reads }}</span>
              <span>步骤 #{{ focusedVariable.firstStep }} 到 #{{ focusedVariable.lastStep }}</span>
            </div>
            <div class="value-block">
              <span>初始</span>
              <code>{{ short(focusedVariable.firstValue) }}</code>
              <span>最终</span>
              <code>{{ short(focusedVariable.lastValue) }}</code>
            </div>
            <div class="evidence-list">
              <span v-for="item in focusedVariable.evidence" :key="item">{{ item }}</span>
            </div>
          </div>

          <div class="step-evidence">
            <h4>相关执行步骤</h4>
            <button
              v-for="step in variableSteps"
              :key="step.index"
              class="evidence-row"
              @click="jumpToStep(step.index)"
            >
              <span>#{{ step.index }}</span>
              <strong>{{ step.title }}</strong>
              <code>{{ step.code }}</code>
            </button>
          </div>
        </section>

        <section class="flow-panel">
          <div class="panel-title">
            <h3>数据依赖链</h3>
            <p>变量从写入点流向读取点。</p>
          </div>

          <div v-if="model.semanticLinks.value.length" class="flow-list">
            <button
              v-for="link in model.semanticLinks.value"
              :key="`${link.from}-${link.to}-${link.variable}`"
              class="flow-row"
              @click="jumpToStep(link.to)"
            >
              <span class="node">#{{ link.from }}</span>
              <span class="arrow">-></span>
              <strong>{{ link.variable }}</strong>
              <span class="arrow">-></span>
              <span class="node">#{{ link.to }}</span>
            </button>
          </div>
          <div v-else class="muted">没有可见依赖链，通常意味着样例很短或变量读取未形成跨步依赖。</div>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.semantic-map {
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
  font-weight: 800;
  color: #0f172a;
}

.empty-copy {
  font-size: 13px;
}

.map-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 420px);
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

h2, h3, h4, p {
  margin: 0;
}

h2 {
  color: #0f172a;
  font-size: 24px;
}

.map-header p,
.panel-title p {
  margin-top: 6px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.compact-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.compact-metrics span {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  padding: 9px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
  color: #64748b;
  font-size: 12px;
}

.compact-metrics strong {
  color: #0f172a;
  font-size: 18px;
}

.concept-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 10px;
}

.concept-card {
  display: flex;
  flex-direction: column;
  gap: 9px;
  min-height: 168px;
  padding: 12px;
  border: 1px solid #dbe3ef;
  border-top: 4px solid var(--phase);
  border-radius: 8px;
  background: #ffffff;
}

.concept-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.phase-marker {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--phase);
}

.concept-head h3 {
  flex: 1;
  color: #0f172a;
  font-size: 15px;
}

.concept-head strong {
  color: var(--phase);
}

.concept-card p {
  min-height: 36px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.concept-lines,
.concept-vars,
.evidence-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.concept-lines span {
  padding: 3px 6px;
  border-radius: 5px;
  background: #f1f5f9;
  color: #475569;
  font-size: 11px;
}

.concept-vars button {
  max-width: 100%;
  padding: 4px 7px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #ffffff;
  color: #334155;
  font-size: 11px;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.concept-vars button.active {
  border-color: var(--phase);
  background: color-mix(in srgb, var(--phase), white 90%);
}

.map-body {
  display: grid;
  grid-template-columns: minmax(260px, 0.8fr) minmax(360px, 1.3fr) minmax(260px, 0.8fr);
  gap: 12px;
  align-items: start;
}

.inventory-panel,
.focus-panel,
.flow-panel {
  min-width: 0;
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
}

.panel-title {
  padding: 12px;
  border-bottom: 1px solid #e2e8f0;
}

h3 {
  color: #0f172a;
  font-size: 15px;
}

h4 {
  color: #0f172a;
  font-size: 13px;
}

.variable-list,
.flow-list,
.step-evidence {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 12px;
}

.variable-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 46px;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
}

.variable-row.active {
  border-color: var(--role);
  background: color-mix(in srgb, var(--role), white 92%);
}

.var-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--role);
}

.var-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.var-main strong {
  color: #0f172a;
  overflow-wrap: anywhere;
}

.var-main small {
  color: #64748b;
}

.var-score {
  color: var(--role);
  font-weight: 900;
  font-size: 12px;
}

.focus-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 12px;
  padding: 12px;
  border: 1px solid color-mix(in srgb, var(--role), white 72%);
  border-radius: 8px;
  background: color-mix(in srgb, var(--role), white 94%);
}

.focus-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.focus-head span {
  color: #0f172a;
  font-size: 18px;
  font-weight: 900;
  overflow-wrap: anywhere;
}

.focus-head strong {
  flex: 0 0 auto;
  padding: 4px 8px;
  border-radius: 999px;
  background: #ffffff;
  color: var(--role);
  font-size: 12px;
}

.focus-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.focus-stats span,
.evidence-list span {
  padding: 4px 7px;
  border-radius: 5px;
  background: #ffffff;
  color: #475569;
  font-size: 12px;
}

.value-block {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 7px;
  align-items: start;
}

.value-block span {
  color: #64748b;
  font-size: 12px;
}

code {
  padding: 6px;
  border-radius: 5px;
  background: #0f172a;
  color: #e2e8f0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.evidence-row {
  display: grid;
  grid-template-columns: 48px minmax(90px, 120px) minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #ffffff;
  color: #334155;
  text-align: left;
  cursor: pointer;
}

.evidence-row span {
  color: #2563eb;
  font-weight: 900;
}

.evidence-row strong {
  color: #0f172a;
  font-size: 12px;
}

.evidence-row code {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.flow-row {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 7px;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #ffffff;
  color: #334155;
  cursor: pointer;
}

.flow-row strong {
  padding: 3px 7px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #0369a1;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node {
  color: #0f172a;
  font-weight: 900;
}

.arrow {
  color: #94a3b8;
}

.muted {
  padding: 12px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

@media (max-width: 1180px) {
  .map-header,
  .map-body {
    grid-template-columns: 1fr;
  }
}
</style>
