<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'

const store = useAnalysisStore()

const frames = computed(() => store.callStack)
const narration = computed(() => store.currentNarration)
const currentStep = computed(() => store.safeStep)
const timeline = computed(() => store.timeline)
const currentData = computed(() => timeline.value[currentStep.value] || null)
const detectedPatterns = computed(() => store.detectedPatterns)
const currentPattern = computed(() => store.currentPattern)

// Counterfactual labels
const CF_SEVERITY_LABELS: Record<string, string> = {
  critical: '致命',
  major: '严重',
  minor: '轻微',
}
const CF_CAT_LABELS: Record<string, string> = {
  progress_loss: '进展丧失',
  termination_loss: '终止性丧失',
  correctness_loss: '正确性丧失',
  efficiency_loss: '效率退化',
}

// Motif labels
const MOTIF_LABELS: Record<string, string> = {
  uncertainty_reduction: '不确定性缩减',
  state_compression: '状态压缩',
  frontier_expansion: '前沿扩展',
  constraint_propagation: '约束传播',
  fixed_point_convergence: '不动点收敛',
}

// Goal type labels
const GOAL_TYPE_LABELS: Record<string, string> = {
  minimize: '最小化',
  maximize: '最大化',
  preserve: '保持不变',
  converge: '收敛到',
  compress: '压缩状态',
}

// Invariant category labels
const INVARIANT_CAT_LABELS: Record<string, string> = {
  precondition: '前置条件',
  loop_invariant: '循环不变量',
  progress: '进展保证',
  termination: '终止性',
  postcondition: '后置条件',
}

// Causal edge type labels and colors
const CAUSAL_TYPE_LABELS: Record<string, string> = {
  data_dependency: '数据依赖',
  control_dependency: '控制依赖',
  state_change: '状态变更',
  recursive_invocation: '递归调用',
}
const CAUSAL_TYPE_COLORS: Record<string, string> = {
  data_dependency: '#3b82f6',
  control_dependency: '#7c3aed',
  state_change: '#d97706',
  recursive_invocation: '#ec4899',
}

// Causal edges: filter to edges involving current step
const currentCausalEdges = computed(() => {
  const edges = currentPattern.value?.causal_edges
  if (!edges?.length) return []
  const step = currentStep.value
  return edges.filter(e => e.cause === step || e.effect === step).slice(0, 6)
})

// Current frame lifecycle event
const currentFrameEvent = computed(() => {
  const events = store.frameLifecycle
  return events.find(e => e.step === currentStep.value) || null
})

const FRAME_EVENT_LABELS: Record<string, { icon: string; text: string; color: string }> = {
  CALL_ENTER: { icon: '📥', text: '进入调用', color: '#7c3aed' },
  CALL_SUSPEND: { icon: '⏸', text: '挂起等待子调用', color: '#d97706' },
  CALL_RESUME: { icon: '▶', text: '恢复执行', color: '#0284c7' },
  CALL_RETURN: { icon: '📤', text: '返回调用', color: '#16a34a' },
}

function stepRange(frame: { start_step: number; end_step: number | null }) {
  const end = frame.end_step ?? store.totalSteps - 1
  return `${frame.start_step + 1}–${end + 1}`
}
</script>

<template>
  <div class="stack-panel animate-slide-up">
    <!-- Semantic narration -->
    <div v-if="narration" class="narration-bar">
      <span class="narration-icon">💡</span>
      <span class="narration-text">{{ narration }}</span>
    </div>

    <!-- Detected algorithmic pattern -->
    <div v-if="currentPattern" class="pattern-bar">
      <span class="pattern-icon">🔍</span>
      <div class="pattern-info">
        <span class="pattern-name">{{ currentPattern.narrative?.headline || currentPattern.display_name }}</span>
        <span class="pattern-desc">{{ currentPattern.description }}</span>
        <div v-if="currentPattern.semantic" class="pattern-semantic">
          <span class="sem-op">{{ currentPattern.semantic.op }}</span>
          <span class="sem-structure">{{ currentPattern.semantic.structure }}</span>
          <span v-if="currentPattern.semantic.direction" class="sem-dir">{{ currentPattern.semantic.direction }}</span>
          <span v-for="actor in currentPattern.semantic.actors" :key="actor" class="sem-actor">{{ actor }}</span>
        </div>
        <div v-if="currentPattern.sub_patterns?.length" class="pattern-composition">
          由 {{ currentPattern.sub_patterns.join(' + ') }} 组合而成
        </div>
      </div>
      <span class="pattern-range">步骤 {{ currentPattern.start_step + 1 }}–{{ currentPattern.end_step + 1 }}</span>
      <span class="pattern-conf">{{ Math.round(currentPattern.confidence * 100) }}%</span>
    </div>

    <!-- Cognitive Narrative (the "why") -->
    <div v-if="currentPattern?.narrative" class="narrative-panel">
      <div class="narrative-section">
        <span class="narrative-label">机制</span>
        <span class="narrative-text">{{ currentPattern.narrative.mechanism }}</span>
      </div>
      <div class="narrative-section">
        <span class="narrative-label">策略</span>
        <span class="narrative-text">{{ currentPattern.narrative.strategy }}</span>
      </div>
      <div v-if="currentPattern.narrative.temporal_facts?.length" class="narrative-section">
        <span class="narrative-label">时序逻辑</span>
        <div class="temporal-facts">
          <span v-for="(fact, i) in currentPattern.narrative.temporal_facts" :key="i" class="temporal-fact">{{ fact }}</span>
        </div>
      </div>
      <div v-if="currentPattern.narrative.analogies?.length" class="narrative-section">
        <span class="narrative-label">计算类比</span>
        <div class="analogies">
          <span v-for="(a, i) in currentPattern.narrative.analogies" :key="i" class="analogy-chip">{{ a }}</span>
        </div>
      </div>
      <div v-if="currentPattern.narrative.lattice_path?.length" class="narrative-section lattice-path">
        <span class="narrative-label">语义层级</span>
        <span class="lattice-chain">{{ currentPattern.narrative.lattice_path.join(' → ') }}</span>
      </div>
    </div>

    <!-- Goals (optimization objectives) -->
    <div v-if="currentPattern?.goals?.length" class="goals-panel">
      <div class="goals-title">
        <span class="goal-icon">🎯</span>
        <span>优化目标</span>
        <span class="goal-count">{{ currentPattern.goals.length }}</span>
      </div>
      <div class="goal-list">
        <div v-for="(goal, i) in currentPattern.goals" :key="i"
          class="goal-card" :class="goal.type">
          <div class="goal-header">
            <span class="goal-type-badge">{{ GOAL_TYPE_LABELS[goal.type] || goal.type }}</span>
            <span class="goal-target">{{ goal.target }}</span>
            <span class="goal-conf">{{ Math.round(goal.confidence * 100) }}%</span>
          </div>
          <span class="goal-desc">{{ goal.description }}</span>
          <div v-if="goal.evidence?.length" class="goal-evidence">
            <span v-for="(ev, j) in goal.evidence" :key="j" class="goal-ev">{{ ev }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Invariants (correctness reasoning) -->
    <div v-if="currentPattern?.invariants?.length" class="invariants-panel">
      <div class="invariants-title">
        <span class="inv-icon">🛡</span>
        <span>正确性不变量</span>
        <span class="inv-count">{{ currentPattern.invariants.length }}</span>
      </div>
      <div class="invariant-list">
        <div v-for="inv in currentPattern.invariants" :key="inv.name"
          :class="['invariant-card', inv.category, { violated: inv.violations > 0 }]">
          <div class="inv-header">
            <span class="inv-cat">{{ INVARIANT_CAT_LABELS[inv.category] || inv.category }}</span>
            <span class="inv-conf">{{ Math.round(inv.confidence * 100) }}%</span>
            <span v-if="inv.violations > 0" class="inv-violations">⚠ {{ inv.violations }} 次违反</span>
            <span v-else class="inv-ok">✓ 成立</span>
          </div>
          <code class="inv-predicate">{{ inv.predicate }}</code>
          <span class="inv-desc">{{ inv.description }}</span>
        </div>
      </div>
    </div>

    <!-- Causal Edges (execution causality) -->
    <div v-if="currentCausalEdges.length" class="causal-panel">
      <div class="causal-title">
        <span class="causal-icon">🔗</span>
        <span>因果依赖</span>
        <span class="causal-count">{{ currentCausalEdges.length }}</span>
      </div>
      <div class="causal-list">
        <div v-for="(edge, i) in currentCausalEdges" :key="i"
          class="causal-edge"
          :style="{ borderColor: CAUSAL_TYPE_COLORS[edge.type] || '#94a3b8' }">
          <span class="ce-type" :style="{ color: CAUSAL_TYPE_COLORS[edge.type] }">{{ CAUSAL_TYPE_LABELS[edge.type] || edge.type }}</span>
          <span class="ce-flow">步骤 {{ edge.cause + 1 }} → {{ edge.effect + 1 }}</span>
          <span v-if="edge.variable" class="ce-var">{{ edge.variable }}</span>
          <span class="ce-desc">{{ edge.description }}</span>
        </div>
      </div>
    </div>

    <!-- Counterfactuals (what would break) -->
    <div v-if="currentPattern?.counterfactuals?.length" class="counterfactuals-panel">
      <div class="cf-title">
        <span class="cf-icon">⚡</span>
        <span>反事实推理</span>
        <span class="cf-count">{{ currentPattern.counterfactuals.length }}</span>
      </div>
      <div class="cf-list">
        <div v-for="(cf, i) in currentPattern.counterfactuals" :key="i"
          :class="['cf-card', cf.severity]">
          <div class="cf-header">
            <span class="cf-severity">{{ CF_SEVERITY_LABELS[cf.severity] || cf.severity }}</span>
            <span class="cf-cat">{{ CF_CAT_LABELS[cf.category] || cf.category }}</span>
            <span class="cf-conf">{{ Math.round(cf.confidence * 100) }}%</span>
          </div>
          <div class="cf-logic">
            <span class="cf-condition">{{ cf.condition }}</span>
            <span class="cf-arrow">→</span>
            <span class="cf-consequence">{{ cf.consequence }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Computational Motifs (deep patterns) -->
    <div v-if="currentPattern?.motifs?.length" class="motifs-panel">
      <div class="motif-title">
        <span class="motif-icon">🧬</span>
        <span>计算原语</span>
        <span class="motif-count">{{ currentPattern.motifs.length }}</span>
      </div>
      <div class="motif-list">
        <div v-for="(m, i) in currentPattern.motifs" :key="i"
          class="motif-card" :class="`depth-${m.depth}`">
          <div class="motif-header">
            <span class="motif-name">{{ MOTIF_LABELS[m.motif] || m.motif }}</span>
            <span class="motif-depth">{{ ['表层', '结构层', '深层'][m.depth] }}</span>
            <span class="motif-conf">{{ Math.round(m.confidence * 100) }}%</span>
          </div>
          <span class="motif-desc">{{ m.description }}</span>
          <div v-if="m.evidence?.length" class="motif-evidence">
            <span v-for="(ev, j) in m.evidence" :key="j" class="motif-ev">{{ ev }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- All detected patterns (collapsed) -->
    <div v-if="detectedPatterns.length > 1" class="patterns-list">
      <span class="patterns-label">检测到 {{ detectedPatterns.length }} 个算法模式:</span>
      <span v-for="p in detectedPatterns" :key="p.pattern_name" class="pattern-chip"
        :class="{ active: currentPattern?.pattern_name === p.pattern_name, composed: p.sub_patterns?.length }"
        @click="store.goToStep(p.start_step)">
        {{ p.narrative?.headline || p.display_name }}
      </span>
    </div>

    <!-- Current step info -->
    <div v-if="currentData" class="step-info">
      <span class="step-line">L{{ currentData.line }}</span>
      <code class="step-code">{{ currentData.code }}</code>
      <span v-if="currentData.depth != null" class="step-depth">depth {{ currentData.depth }}</span>
    </div>

    <!-- Call stack -->
    <div v-if="frames.length" class="stack-frames">
      <div class="stack-title">调用栈</div>
      <div class="stack-visual">
        <div
          v-for="(frame, i) in frames" :key="frame.call_id"
          :class="['frame-card', { active: frame.is_current }]"
          :style="{ marginLeft: frame.depth * 16 + 'px' }"
        >
          <div class="frame-header">
            <span class="frame-indicator">{{ frame.is_current ? '▶' : '│' }}</span>
            <span class="frame-func">{{ frame.func_name }}()</span>
            <span class="frame-range">步骤 {{ stepRange(frame) }}</span>
          </div>
          <div class="frame-args">
            <span v-for="(val, name) in frame.args" :key="name" class="arg-tag">
              {{ name }}={{ val }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Frame lifecycle event -->
    <div v-if="currentFrameEvent" class="frame-lifecycle" :style="{ borderColor: FRAME_EVENT_LABELS[currentFrameEvent.type]?.color }">
      <span class="fl-icon">{{ FRAME_EVENT_LABELS[currentFrameEvent.type]?.icon }}</span>
      <span class="fl-text" :style="{ color: FRAME_EVENT_LABELS[currentFrameEvent.type]?.color }">
        {{ FRAME_EVENT_LABELS[currentFrameEvent.type]?.text }}
      </span>
      <span class="fl-func">{{ currentFrameEvent.func_name }}()</span>
      <span class="fl-depth">depth {{ currentFrameEvent.depth }}</span>
    </div>

    <!-- Variable state at current step -->
    <div v-if="currentData?.vars" class="var-state">
      <div class="var-title">当前变量</div>
      <div class="var-grid">
        <div
          v-for="(v, name) in currentData.vars" :key="name"
          :class="['var-card', { changed: v.changed, 'is-new': v.is_new }]"
        >
          <span class="var-name">{{ name }}</span>
          <span class="var-type">{{ v.type }}</span>
          <span class="var-val">{{ String(v.value).slice(0, 40) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stack-panel { display: flex; flex-direction: column; gap: 10px; height: 100%; }

.narration-bar {
  display: flex; align-items: center; gap: 8px;
  background: linear-gradient(135deg, rgba(59,130,246,0.06), rgba(124,58,237,0.06));
  border: 1px solid rgba(59,130,246,0.2);
  border-left: 3px solid #3b82f6;
  border-radius: 8px; padding: 10px 14px;
}
.narration-icon { font-size: 16px; flex-shrink: 0; }
.narration-text { font-size: 13px; color: var(--text); line-height: 1.4; }

.pattern-bar {
  display: flex; align-items: center; gap: 8px;
  background: linear-gradient(135deg, rgba(34,197,94,0.06), rgba(59,130,246,0.06));
  border: 1px solid rgba(34,197,94,0.2);
  border-left: 3px solid #22c55e;
  border-radius: 8px; padding: 10px 14px;
  animation: flSlide 0.3s ease;
}
.pattern-icon { font-size: 16px; flex-shrink: 0; }
.pattern-info { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.pattern-name { font-size: 13px; font-weight: 700; color: #22c55e; }
.pattern-desc { font-size: 11px; color: var(--text-muted); line-height: 1.3; }
.pattern-range { font-size: 10px; color: var(--text-muted); white-space: nowrap; }
.pattern-conf {
  font-size: 10px; font-weight: 700; color: #22c55e;
  background: rgba(34,197,94,0.1); padding: 1px 6px; border-radius: 3px;
}

.pattern-semantic {
  display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-top: 3px;
}
.sem-op {
  font-size: 10px; font-weight: 700; color: #7c3aed;
  background: rgba(124,58,237,0.08); padding: 1px 6px; border-radius: 3px;
}
.sem-structure {
  font-size: 10px; font-weight: 600; color: #0284c7;
  background: rgba(2,132,199,0.08); padding: 1px 6px; border-radius: 3px;
}
.sem-dir {
  font-size: 10px; color: var(--text-muted);
  background: rgba(148,163,184,0.08); padding: 1px 6px; border-radius: 3px;
}
.sem-actor {
  font-size: 10px; color: #d97706;
  background: rgba(217,119,6,0.08); padding: 1px 6px; border-radius: 3px;
}
.pattern-composition {
  font-size: 10px; color: var(--text-muted); margin-top: 2px;
  font-style: italic;
}

/* Cognitive Narrative Panel */
.narrative-panel {
  display: flex; flex-direction: column; gap: 8px;
  background: linear-gradient(135deg, rgba(124,58,237,0.04), rgba(59,130,246,0.04));
  border: 1px solid rgba(124,58,237,0.15);
  border-left: 3px solid #7c3aed;
  border-radius: 8px; padding: 10px 14px;
  animation: flSlide 0.3s ease;
}
.narrative-section {
  display: flex; flex-direction: column; gap: 2px;
}
.narrative-label {
  font-size: 10px; font-weight: 700; color: #7c3aed;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.narrative-text {
  font-size: 12px; color: var(--text); line-height: 1.5;
}

.temporal-facts {
  display: flex; flex-direction: column; gap: 3px;
}
.temporal-fact {
  font-size: 11px; color: var(--text-dim);
  padding: 2px 8px; background: rgba(148,163,184,0.06);
  border-radius: 4px; border-left: 2px solid #94a3b8;
}

.analogies {
  display: flex; flex-wrap: wrap; gap: 4px;
}
.analogy-chip {
  font-size: 10px; color: #0284c7;
  background: rgba(2,132,199,0.08);
  padding: 2px 8px; border-radius: 4px;
  border: 1px solid rgba(2,132,199,0.15);
}

.lattice-path .lattice-chain {
  font-size: 11px; color: var(--text-muted); font-family: monospace;
}

.patterns-list {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-size: 11px; color: var(--text-muted);
}
.patterns-label { font-size: 10px; }
.pattern-chip {
  font-size: 10px; padding: 2px 8px; border-radius: 4px;
  background: rgba(148,163,184,0.08); border: 1px solid rgba(148,163,184,0.15);
  color: var(--text-dim); cursor: pointer; transition: all 0.15s;
}
.pattern-chip:hover { border-color: #22c55e; color: #22c55e; }
.pattern-chip.active {
  background: rgba(34,197,94,0.1); border-color: #22c55e; color: #22c55e; font-weight: 600;
}
.pattern-chip.composed {
  border-color: #7c3aed; color: #7c3aed;
  background: rgba(124,58,237,0.06);
}
.pattern-chip.composed::before { content: '◆ '; font-size: 8px; }

.step-info {
  display: flex; align-items: center; gap: 8px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 14px;
  font-size: 12px;
}
.step-line {
  background: var(--primary); color: #fff;
  padding: 1px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 700; font-family: monospace;
}
.step-code {
  flex: 1; color: var(--text); font-size: 12px;
  font-family: monospace; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.step-depth {
  font-size: 10px; color: var(--text-muted);
  background: rgba(148,163,184,0.1); padding: 1px 6px; border-radius: 3px;
}

.stack-frames {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px 14px; flex: 1;
  overflow-y: auto; min-height: 0;
}
.stack-title {
  font-size: 11px; font-weight: 700; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.5px;
  margin-bottom: 8px;
}
.stack-visual {
  display: flex; flex-direction: column; gap: 4px;
}

.frame-card {
  background: rgba(148,163,184,0.04);
  border: 1px solid rgba(148,163,184,0.15);
  border-radius: 6px; padding: 6px 10px;
  transition: all 0.2s;
}
.frame-card.active {
  background: rgba(251,114,153,0.08);
  border-color: var(--primary);
  box-shadow: 0 2px 8px rgba(251,114,153,0.15);
}
.frame-header {
  display: flex; align-items: center; gap: 6px; font-size: 12px;
}
.frame-indicator { color: var(--primary); font-size: 10px; width: 12px; }
.frame-card.active .frame-indicator { color: var(--primary); }
.frame-card:not(.active) .frame-indicator { color: var(--text-muted); }
.frame-func { font-weight: 700; color: var(--text); font-family: monospace; font-size: 12px; }
.frame-range { font-size: 10px; color: var(--text-muted); margin-left: auto; }

.frame-args {
  display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;
  padding-left: 18px;
}
.arg-tag {
  font-size: 10px; font-family: monospace;
  background: rgba(0,161,214,0.08); color: var(--highlight);
  padding: 1px 6px; border-radius: 3px;
}

.var-state {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px 14px;
}
.var-title {
  font-size: 11px; font-weight: 700; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.5px;
  margin-bottom: 8px;
}
.var-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.var-card {
  display: flex; flex-direction: column; gap: 2px;
  background: rgba(148,163,184,0.04);
  border: 1px solid rgba(148,163,184,0.15);
  border-radius: 6px; padding: 6px 10px; min-width: 80px;
}
.var-card.changed {
  border-color: var(--primary);
  background: rgba(251,114,153,0.06);
}
.var-card.is-new {
  border-color: #22c55e;
  background: rgba(34,197,94,0.06);
}
.var-name { font-size: 11px; font-weight: 700; color: var(--highlight); font-family: monospace; }
.var-type { font-size: 9px; color: var(--text-muted); }
.var-val { font-size: 11px; color: var(--text); font-family: monospace; word-break: break-all; }

.frame-lifecycle {
  display: flex; align-items: center; gap: 8px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-left: 3px solid; border-radius: 8px; padding: 8px 14px;
  animation: flSlide 0.3s ease;
}
.fl-icon { font-size: 16px; }
.fl-text { font-size: 13px; font-weight: 600; }
.fl-func { font-family: monospace; font-size: 12px; color: var(--text); }
.fl-depth { font-size: 10px; color: var(--text-muted); margin-left: auto; }
@keyframes flSlide {
  from { opacity: 0; transform: translateX(-8px); }
  to { opacity: 1; transform: translateX(0); }
}

/* Counterfactuals Panel */
.counterfactuals-panel {
  display: flex; flex-direction: column; gap: 6px;
  background: linear-gradient(135deg, rgba(239,68,68,0.04), rgba(245,158,11,0.04));
  border: 1px solid rgba(239,68,68,0.12);
  border-left: 3px solid #ef4444;
  border-radius: 8px; padding: 10px 14px;
  animation: flSlide 0.3s ease;
}
.cf-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 700; color: #ef4444;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.cf-icon { font-size: 14px; }
.cf-count {
  font-size: 9px; background: rgba(239,68,68,0.12);
  padding: 1px 6px; border-radius: 3px; margin-left: auto;
}
.cf-list { display: flex; flex-direction: column; gap: 4px; }
.cf-card {
  background: rgba(148,163,184,0.04);
  border: 1px solid rgba(148,163,184,0.12);
  border-radius: 6px; padding: 6px 10px;
}
.cf-card.critical { border-left: 2px solid #ef4444; }
.cf-card.major { border-left: 2px solid #f59e0b; }
.cf-card.minor { border-left: 2px solid #94a3b8; }
.cf-header {
  display: flex; align-items: center; gap: 6px;
  font-size: 10px; margin-bottom: 3px;
}
.cf-severity {
  font-weight: 700; padding: 1px 6px; border-radius: 3px;
}
.cf-card.critical .cf-severity { color: #ef4444; background: rgba(239,68,68,0.08); }
.cf-card.major .cf-severity { color: #f59e0b; background: rgba(245,158,11,0.08); }
.cf-card.minor .cf-severity { color: #94a3b8; background: rgba(148,163,184,0.08); }
.cf-cat { font-size: 9px; color: var(--text-muted); }
.cf-conf { font-size: 9px; color: var(--text-muted); margin-left: auto; }
.cf-logic {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-size: 11px; line-height: 1.4;
}
.cf-condition { color: var(--text); }
.cf-arrow { color: #ef4444; font-weight: 700; }
.cf-consequence { color: #ef4444; font-weight: 600; }

/* Motifs Panel */
.motifs-panel {
  display: flex; flex-direction: column; gap: 6px;
  background: linear-gradient(135deg, rgba(99,102,241,0.04), rgba(168,85,247,0.04));
  border: 1px solid rgba(99,102,241,0.15);
  border-left: 3px solid #6366f1;
  border-radius: 8px; padding: 10px 14px;
  animation: flSlide 0.3s ease;
}
.motif-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 700; color: #6366f1;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.motif-icon { font-size: 14px; }
.motif-count {
  font-size: 9px; background: rgba(99,102,241,0.12);
  padding: 1px 6px; border-radius: 3px; margin-left: auto;
}
.motif-list { display: flex; flex-direction: column; gap: 4px; }
.motif-card {
  background: rgba(148,163,184,0.04);
  border: 1px solid rgba(148,163,184,0.12);
  border-radius: 6px; padding: 6px 10px;
}
.motif-card.depth-0 { border-left: 2px solid #94a3b8; }
.motif-card.depth-1 { border-left: 2px solid #6366f1; }
.motif-card.depth-2 { border-left: 2px solid #a855f7; background: rgba(99,102,241,0.04); }
.motif-header {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px; margin-bottom: 3px;
}
.motif-name { font-weight: 700; color: #6366f1; }
.motif-depth {
  font-size: 9px; color: var(--text-muted);
  background: rgba(148,163,184,0.08); padding: 1px 6px; border-radius: 3px;
}
.motif-conf { font-size: 9px; color: var(--text-muted); margin-left: auto; }
.motif-desc { font-size: 11px; color: var(--text); line-height: 1.3; }
.motif-evidence {
  display: flex; flex-direction: column; gap: 2px; margin-top: 3px;
}
.motif-ev {
  font-size: 10px; color: var(--text-dim);
  padding: 2px 6px; background: rgba(148,163,184,0.06);
  border-radius: 3px; border-left: 2px solid #6366f1;
}

/* Goals Panel */
.goals-panel {
  display: flex; flex-direction: column; gap: 6px;
  background: linear-gradient(135deg, rgba(245,158,11,0.04), rgba(234,88,12,0.04));
  border: 1px solid rgba(245,158,11,0.15);
  border-left: 3px solid #f59e0b;
  border-radius: 8px; padding: 10px 14px;
  animation: flSlide 0.3s ease;
}
.goals-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 700; color: #f59e0b;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.goal-icon { font-size: 14px; }
.goal-count {
  font-size: 9px; background: rgba(245,158,11,0.12);
  padding: 1px 6px; border-radius: 3px; margin-left: auto;
}
.goal-list {
  display: flex; flex-direction: column; gap: 4px;
}
.goal-card {
  background: rgba(148,163,184,0.04);
  border: 1px solid rgba(148,163,184,0.12);
  border-radius: 6px; padding: 6px 10px;
}
.goal-card.minimize { border-left: 2px solid #3b82f6; }
.goal-card.maximize { border-left: 2px solid #22c55e; }
.goal-card.preserve { border-left: 2px solid #8b5cf6; }
.goal-card.converge { border-left: 2px solid #f59e0b; }
.goal-card.compress { border-left: 2px solid #ec4899; }
.goal-header {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px; margin-bottom: 3px;
}
.goal-type-badge {
  font-size: 10px; font-weight: 700; color: #f59e0b;
  background: rgba(245,158,11,0.08); padding: 1px 6px; border-radius: 3px;
}
.goal-target { font-size: 10px; color: var(--highlight); font-family: monospace; }
.goal-conf { font-size: 9px; color: var(--text-muted); margin-left: auto; }
.goal-desc { font-size: 11px; color: var(--text); line-height: 1.3; }
.goal-evidence {
  display: flex; flex-direction: column; gap: 2px; margin-top: 3px;
}
.goal-ev {
  font-size: 10px; color: var(--text-dim);
  padding: 2px 6px; background: rgba(148,163,184,0.06);
  border-radius: 3px; border-left: 2px solid #f59e0b;
}

/* Invariants Panel */
.invariants-panel {
  display: flex; flex-direction: column; gap: 6px;
  background: linear-gradient(135deg, rgba(16,185,129,0.04), rgba(59,130,246,0.04));
  border: 1px solid rgba(16,185,129,0.15);
  border-left: 3px solid #10b981;
  border-radius: 8px; padding: 10px 14px;
  animation: flSlide 0.3s ease;
}
.invariants-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 700; color: #10b981;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.inv-icon { font-size: 14px; }
.inv-count {
  font-size: 9px; background: rgba(16,185,129,0.12);
  padding: 1px 6px; border-radius: 3px; margin-left: auto;
}
.invariant-list {
  display: flex; flex-direction: column; gap: 4px;
}
.invariant-card {
  background: rgba(148,163,184,0.04);
  border: 1px solid rgba(148,163,184,0.12);
  border-radius: 6px; padding: 6px 10px;
}
.invariant-card.violated {
  border-color: #ef4444;
  background: rgba(239,68,68,0.06);
}
.inv-header {
  display: flex; align-items: center; gap: 6px;
  font-size: 10px; margin-bottom: 3px;
}
.inv-cat {
  font-weight: 700; color: #10b981;
  background: rgba(16,185,129,0.08); padding: 1px 6px; border-radius: 3px;
}
.invariant-card.violated .inv-cat { color: #ef4444; background: rgba(239,68,68,0.08); }
.inv-conf { font-size: 9px; color: var(--text-muted); }
.inv-violations { font-size: 9px; color: #ef4444; font-weight: 600; }
.inv-ok { font-size: 9px; color: #10b981; }
.inv-predicate {
  font-size: 11px; font-family: monospace; color: var(--highlight);
  background: rgba(0,161,214,0.06); padding: 2px 6px; border-radius: 3px;
  display: inline-block; margin: 2px 0;
}
.inv-desc { font-size: 10px; color: var(--text-dim); line-height: 1.3; }

/* Causal Panel */
.causal-panel {
  display: flex; flex-direction: column; gap: 6px;
  background: linear-gradient(135deg, rgba(236,72,153,0.04), rgba(124,58,237,0.04));
  border: 1px solid rgba(236,72,153,0.15);
  border-left: 3px solid #ec4899;
  border-radius: 8px; padding: 10px 14px;
  animation: flSlide 0.3s ease;
}
.causal-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 700; color: #ec4899;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.causal-icon { font-size: 14px; }
.causal-count {
  font-size: 9px; background: rgba(236,72,153,0.12);
  padding: 1px 6px; border-radius: 3px; margin-left: auto;
}
.causal-list {
  display: flex; flex-direction: column; gap: 4px;
}
.causal-edge {
  background: rgba(148,163,184,0.04);
  border: 1px solid rgba(148,163,184,0.12);
  border-left: 2px solid;
  border-radius: 6px; padding: 6px 10px;
}
.ce-type {
  font-size: 10px; font-weight: 700;
  padding: 1px 6px; border-radius: 3px;
  background: rgba(148,163,184,0.06);
}
.ce-flow { font-size: 10px; color: var(--text-muted); font-family: monospace; }
.ce-var {
  font-size: 10px; color: var(--highlight);
  background: rgba(0,161,214,0.08); padding: 1px 6px; border-radius: 3px;
}
.ce-desc { font-size: 10px; color: var(--text-dim); line-height: 1.3; }
</style>
