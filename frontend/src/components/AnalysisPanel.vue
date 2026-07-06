<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { useSemanticModel } from '../composables/useSemanticModel'

const store = useAnalysisStore()
const model = useSemanticModel()

const resultPreview = computed(() => {
  const value = store.insightResult?.result
  if (value == null) return '无返回值'
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 180 ? `${text.slice(0, 180)}...` : text
})

const inputVars = computed(() => {
  return model.variableRoles.value
    .filter(v => v.role.includes('输入') || v.changes === 0 || v.firstStep <= 1)
    .slice(0, 5)
})

const outputVars = computed(() => {
  return model.variableRoles.value
    .filter(v => v.role.includes('结果'))
    .slice(0, 4)
})

const processText = computed(() => {
  const phases = model.phases.value.map(p => p.title).join(' -> ')
  return phases || '顺序执行'
})

const coverage = computed(() => {
  const executedLines = new Set(model.steps.value.map(step => step.line).filter(Boolean))
  const codeLines = store.analysisCode
    .split(/\r?\n/)
    .map((text, i) => ({ line: i + 1, text: text.trim() }))
    .filter(item => item.text && !item.text.startsWith('#'))
  const total = Math.max(codeLines.length, executedLines.size, 1)
  const covered = codeLines.filter(item => executedLines.has(item.line)).length
  return {
    covered,
    total,
    percent: Math.round((covered / total) * 100),
    executedLines: [...executedLines].sort((a, b) => a - b),
  }
})

const lineExplanations = computed(() => {
  const byLine = new Map<number, typeof model.semanticSteps.value>()
  for (const step of model.semanticSteps.value) {
    if (!byLine.has(step.line)) byLine.set(step.line, [])
    byLine.get(step.line)!.push(step)
  }

  const source = store.analysisCode || store.code
  return source.split(/\r?\n/).map((raw, i) => {
    const line = i + 1
    const text = raw.trim()
    const steps = byLine.get(line) || []
    const writes = [...new Set(steps.flatMap(step => step.writes))]
    const reads = [...new Set(steps.flatMap(step => step.reads))]
    return {
      line,
      code: raw,
      trimmed: text,
      executed: steps.length > 0,
      count: steps.length,
      title: steps[0]?.title || (text ? '未在本次执行中经过' : '空行'),
      explanation: steps[0]?.evidence || (text ? '这行代码没有被当前输入走到，可能是未进入的分支、定义语句或辅助代码。' : '空行不会产生执行步骤。'),
      reads,
      writes,
      firstStep: steps[0]?.index,
    }
  }).filter(item => item.trimmed)
})

const plainConclusion = computed(() => {
  const vars = model.variableRoles.value.slice(0, 3).map(v => `${v.name} 负责${v.role}`).join('，')
  return `${model.algorithmLabel.value}：这段代码把输入状态送入执行流程，经过 ${processText.value}，最后得到返回结果。${vars ? `关键变量是 ${vars}。` : ''}`
})

function jumpToStep(index?: number) {
  if (index == null) return
  const rawIndex = model.steps.value.findIndex(step => step.index === index)
  if (rawIndex >= 0) store.currentStep = rawIndex
  const step = model.steps.value[rawIndex]
  store.highlightedLine = step?.line || 0
  store.activeTab = 'replay'
}

function jumpToSemantic() {
  store.activeTab = 'semantic'
}
</script>

<template>
  <div class="understanding-panel">
    <section class="hero">
      <div class="hero-main">
        <span class="eyebrow">一眼看懂</span>
        <h2>{{ model.algorithmLabel.value }}</h2>
        <p>{{ plainConclusion }}</p>
        <button class="primary-link" @click="jumpToSemantic">看语义图</button>
      </div>

      <div class="coverage-card">
        <span>本次解析覆盖率</span>
        <strong>{{ coverage.percent }}%</strong>
        <div class="coverage-bar">
          <i :style="{ width: `${coverage.percent}%` }"></i>
        </div>
        <p>{{ coverage.covered }} / {{ coverage.total }} 行代码在这次运行中被执行并解释。</p>
      </div>
    </section>

    <section class="flow-board">
      <article class="flow-card input">
        <span>输入</span>
        <strong>{{ inputVars.map(v => v.name).join(', ') || '函数默认参数 / 初始状态' }}</strong>
        <p>这些值进入函数或在最开始建立运行上下文。</p>
      </article>
      <article class="flow-card process">
        <span>处理过程</span>
        <strong>{{ processText }}</strong>
        <p>代码实际执行时经过的主要阶段。</p>
      </article>
      <article class="flow-card output">
        <span>输出</span>
        <strong>{{ outputVars.map(v => v.name).join(', ') || 'return 表达式' }}</strong>
        <code>{{ resultPreview }}</code>
      </article>
    </section>

    <section class="limits">
      <strong>不是所有代码都能完整解析。</strong>
      <span>当前解释基于“这一次真实执行轨迹”。未执行分支、外部 IO、网络/文件/数据库依赖、随机数、线程、反射/动态执行、无限循环或运行超时，都只能部分解释。</span>
    </section>

    <div class="main-grid">
      <section class="section">
        <div class="section-head">
          <h3>变量现在是什么角色</h3>
          <p>先看变量职责，再看值怎么变。</p>
        </div>
        <div class="var-list">
          <article
            v-for="variable in model.variableRoles.value.slice(0, 8)"
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

      <section class="section">
        <div class="section-head">
          <h3>执行阶段</h3>
          <p>这不是静态猜测，是按实际运行步骤归类。</p>
        </div>
        <div class="phase-list">
          <article
            v-for="phase in model.phases.value"
            :key="phase.id"
            class="phase-item"
            :style="{ '--phase': phase.color }"
          >
            <div>
              <strong>{{ phase.title }}</strong>
              <span>{{ phase.steps.length }} 步</span>
            </div>
            <p>{{ phase.summary }}</p>
            <em>代码行 {{ phase.lines.join(', ') || '-' }}</em>
          </article>
        </div>
      </section>
    </div>

    <section class="section line-section">
      <div class="section-head">
        <h3>逐行解释</h3>
        <p>绿色代表本次运行走到了；灰色代表这次输入没有执行到。</p>
      </div>
      <div class="line-list">
        <button
          v-for="item in lineExplanations"
          :key="item.line"
          class="line-row"
          :class="{ executed: item.executed }"
          @click="jumpToStep(item.firstStep)"
        >
          <span class="line-no">L{{ item.line }}</span>
          <code>{{ item.code }}</code>
          <span class="line-state">{{ item.executed ? `${item.count} 次` : '未执行' }}</span>
          <strong>{{ item.title }}</strong>
          <p>{{ item.explanation }}</p>
          <em v-if="item.reads.length || item.writes.length">
            读 {{ item.reads.join(', ') || '无' }}；写 {{ item.writes.join(', ') || '无' }}
          </em>
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

.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: 14px;
}

.hero-main,
.coverage-card,
.flow-card,
.limits,
.section {
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
}

.hero-main {
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
  font-size: 28px;
}

.hero-main p {
  margin-top: 8px;
  color: #334155;
  font-size: 15px;
  line-height: 1.65;
}

.primary-link {
  margin-top: 14px;
  padding: 8px 12px;
  border: 1px solid #2563eb;
  border-radius: 6px;
  background: #2563eb;
  color: #ffffff;
  font-weight: 800;
  cursor: pointer;
}

.coverage-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
}

.coverage-card span,
.flow-card span {
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

.coverage-card strong {
  color: #0f172a;
  font-size: 34px;
  line-height: 1;
}

.coverage-bar {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.coverage-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #059669;
}

.coverage-card p,
.flow-card p,
.limits span,
.section-head p,
.var-item p,
.phase-item p,
.line-row p,
.line-row em {
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.flow-board {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.flow-card {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-height: 118px;
  padding: 12px;
  border-top: 4px solid #2563eb;
}

.flow-card.process {
  border-top-color: #0891b2;
}

.flow-card.output {
  border-top-color: #dc2626;
}

.flow-card strong {
  color: #0f172a;
  font-size: 16px;
  overflow-wrap: anywhere;
}

code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.flow-card code {
  color: #334155;
}

.limits {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 12px;
  border-color: #fed7aa;
  background: #fff7ed;
}

.limits strong {
  flex: 0 0 auto;
  color: #9a3412;
}

.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}

.section-head {
  padding: 12px;
  border-bottom: 1px solid #e2e8f0;
}

h3 {
  color: #0f172a;
  font-size: 15px;
}

.var-list,
.phase-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
}

.var-item,
.phase-item {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-left: 4px solid var(--role, var(--phase));
  border-radius: 7px;
  background: #ffffff;
}

.var-title,
.phase-item > div {
  display: flex;
  align-items: center;
  gap: 8px;
}

.var-title strong,
.phase-item strong {
  flex: 1;
  color: #0f172a;
}

.var-title span,
.phase-item span {
  flex: 0 0 auto;
  padding: 3px 7px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--role, var(--phase)), white 86%);
  color: var(--role, var(--phase));
  font-size: 11px;
  font-weight: 800;
}

.phase-item em {
  color: #475569;
  font-size: 12px;
  font-style: normal;
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

.line-section {
  overflow: hidden;
}

.line-list {
  display: flex;
  flex-direction: column;
}

.line-row {
  display: grid;
  grid-template-columns: 54px minmax(180px, 1.2fr) 72px minmax(120px, 0.8fr);
  gap: 8px 10px;
  align-items: start;
  padding: 9px 12px;
  border: 0;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
}

.line-row.executed {
  background: #f0fdf4;
}

.line-row:hover {
  background: #eff6ff;
}

.line-no {
  color: #64748b;
  font-weight: 900;
}

.line-row code {
  color: #0f172a;
  white-space: pre-wrap;
}

.line-state {
  justify-self: start;
  padding: 2px 7px;
  border-radius: 999px;
  background: #e2e8f0;
  color: #475569;
  font-size: 11px;
  font-weight: 800;
}

.line-row.executed .line-state {
  background: #bbf7d0;
  color: #166534;
}

.line-row strong {
  color: #0f172a;
}

.line-row p,
.line-row em {
  grid-column: 2 / -1;
  font-style: normal;
}

@media (max-width: 1100px) {
  .hero,
  .flow-board,
  .main-grid,
  .line-row {
    grid-template-columns: 1fr;
  }

  .line-row p,
  .line-row em {
    grid-column: auto;
  }
}
</style>
