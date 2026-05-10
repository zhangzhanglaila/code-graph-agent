<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAnalysisStore } from '../store/analysisStore'
import { analyzeFull, type AnalyzeFullResponse } from '../api/analysis'

const store = useAnalysisStore()
const fullResult = ref<AnalyzeFullResponse | null>(null)
const fullLoading = ref(false)
const fullError = ref('')

async function runFullAnalysis() {
  fullLoading.value = true
  fullError.value = ''
  try {
    fullResult.value = await analyzeFull(store.code, store.funcName, store.language)
  } catch (e: any) {
    fullError.value = e.message
  } finally {
    fullLoading.value = false
  }
}

function timeAgo(ts: number): string {
  const diff = Date.now() - ts
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return `${Math.floor(diff / 86400000)}天前`
}

const varList = computed(() => {
  if (!fullResult.value?.variables) return []
  return Object.values(fullResult.value.variables)
    .filter(v => v.changes > 0 || v.first_value !== v.last_value)
    .sort((a, b) => b.changes - a.changes)
})

const topPatterns = computed(() => {
  return fullResult.value?.key_patterns || []
})

const showTimeline = ref(false)
</script>

<template>
  <div class="insight-panel">
    <!-- Welcome state -->
    <div v-if="!store.hasResults && !fullResult" class="welcome">
      <div class="welcome-icon">&#x1F9E0;</div>
      <h2>粘贴代码，理解一切</h2>
      <p>一键分析代码的算法类型、变量演变、执行流程和因果关系</p>
      <div class="feature-grid">
        <div class="feature-card">
          <div class="feature-icon">&#x1F50D;</div>
          <div class="feature-title">智能分析</div>
          <div class="feature-desc">算法识别 · 模式检测 · 一句话总结</div>
        </div>
        <div class="feature-card">
          <div class="feature-icon">&#x1F4CA;</div>
          <div class="feature-title">变量演变</div>
          <div class="feature-desc">追踪每个变量从创建到最终值</div>
        </div>
        <div class="feature-card">
          <div class="feature-icon">&#x1F4A1;</div>
          <div class="feature-title">执行时间线</div>
          <div class="feature-desc">关键步骤高亮 · 变化标注</div>
        </div>
        <div class="feature-card">
          <div class="feature-icon">&#x1F9EC;</div>
          <div class="feature-title">因果链</div>
          <div class="feature-desc">根因追踪 · 数据依赖可视化</div>
        </div>
      </div>
      <p class="hint">在上方粘贴代码并点击 <strong>分析</strong>，或尝试示例</p>

      <!-- History -->
      <div v-if="store.history.length" class="history-section">
        <div class="history-header">
          <span class="history-title">最近分析</span>
          <button class="history-clear" @click="store.clearHistory()">清空</button>
        </div>
        <div class="history-list">
          <div
            v-for="entry in store.history.slice(0, 5)" :key="entry.id"
            class="history-item"
            @click="store.loadFromHistory(entry)"
          >
            <div class="history-func">{{ entry.funcName }}()</div>
            <div class="history-insight">{{ entry.oneLiner }}</div>
            <div class="history-meta">
              <span class="history-algo">{{ entry.algorithmType }}</span>
              <span class="history-time">{{ timeAgo(entry.timestamp) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Results state -->
    <div v-else class="results">
      <!-- Loading unified analysis -->
      <div v-if="fullLoading" class="loading-inline">
        <div class="spinner"></div>
        <span>正在生成统一分析报告...</span>
      </div>

      <!-- Error -->
      <div v-if="fullError" class="error-box">{{ fullError }}</div>

      <!-- Unified Result -->
      <div v-if="fullResult?.success" class="unified-result">

        <!-- 1. Summary Hero -->
        <div class="summary-hero">
          <div class="summary-label">分析结论</div>
          <div class="summary-text">{{ fullResult.summary }}</div>
          <div class="summary-tags">
            <span class="tag tag-algo">{{ fullResult.algorithm }}</span>
            <span class="tag tag-conf">{{ Math.round(fullResult.confidence * 100) }}% 置信度</span>
            <span class="tag tag-steps">{{ fullResult.total_steps }} 步</span>
          </div>
        </div>

        <!-- 2. Result -->
        <div class="result-box">
          <span class="result-label">返回值</span>
          <code class="result-value">{{ fullResult.result }}</code>
        </div>

        <!-- 3. Key Patterns -->
        <div v-if="topPatterns.length" class="section">
          <div class="section-title">检测到的模式</div>
          <div class="pattern-row">
            <div v-for="p in topPatterns" :key="p.name" class="pattern-chip">
              <span class="pattern-name">{{ p.name }}</span>
              <span class="pattern-conf">{{ Math.round(p.confidence * 100) }}%</span>
              <span v-if="p.complexity" class="pattern-cmplx">{{ p.complexity }}</span>
            </div>
          </div>
          <div class="pattern-descs">
            <div v-for="p in topPatterns" :key="p.name + '-desc'" class="pattern-desc-item">
              <strong>{{ p.name }}:</strong> {{ p.description }}
            </div>
          </div>
        </div>

        <!-- 4. Phases -->
        <div v-if="fullResult.phases.length" class="section">
          <div class="section-title">执行阶段</div>
          <div class="phase-bar">
            <div
              v-for="(phase, i) in fullResult.phases" :key="i"
              class="phase-segment"
              :style="{ flex: phase.step_count }"
              :title="`${phase.name}: ${phase.description} (${phase.step_count}步)`"
            >
              <div class="phase-name">{{ phase.name }}</div>
              <div class="phase-count">{{ phase.step_count }}步</div>
            </div>
          </div>
        </div>

        <!-- 5. Variable Evolution -->
        <div v-if="varList.length" class="section">
          <div class="section-title">变量演变</div>
          <div class="var-grid">
            <div v-for="v in varList" :key="v.name" class="var-card">
              <div class="var-header">
                <span class="var-name">{{ v.name }}</span>
                <span class="var-type">{{ v.type }}</span>
                <span class="var-changes">{{ v.changes }}次变化</span>
              </div>
              <div class="var-flow">
                <code class="var-val var-first">{{ v.first_value }}</code>
                <span class="var-arrow">→</span>
                <code class="var-val var-last">{{ v.last_value }}</code>
              </div>
            </div>
          </div>
        </div>

        <!-- 6. Key Timeline (collapsible) -->
        <div v-if="fullResult.key_timeline.length" class="section">
          <div class="section-title clickable" @click="showTimeline = !showTimeline">
            关键步骤时间线 ({{ fullResult.key_timeline.length }} 步)
            <span class="toggle-arrow">{{ showTimeline ? '▼' : '▶' }}</span>
          </div>
          <div v-show="showTimeline" class="timeline-list">
            <div
              v-for="step in fullResult.key_timeline" :key="step.step"
              class="timeline-step"
              :class="step.event"
            >
              <span class="step-num">#{{ step.step }}</span>
              <code class="step-code">{{ step.code }}</code>
              <span v-if="step.changed_vars.length" class="step-changed">
                {{ step.changed_vars.join(', ') }}
              </span>
              <span v-if="step.event" class="step-event">{{ step.event }}</span>
            </div>
          </div>
        </div>

        <!-- 7. Causal Chain (collapsible) -->
        <div v-if="fullResult.causal_chain.length" class="section">
          <div class="section-title">因果依赖链</div>
          <div class="causal-mini">
            <div v-for="(link, i) in fullResult.causal_chain.slice(0, 8)" :key="i" class="causal-link">
              <span class="causal-step">步骤{{ link.step }}</span>
              <span class="causal-kind" :class="link.kind">{{ link.kind }}</span>
              <span v-if="link.var" class="causal-var">{{ link.var }}</span>
              <span class="causal-arrow">→</span>
              <span class="causal-step">步骤{{ link.target }}</span>
            </div>
          </div>
        </div>

        <!-- 8. Fallback: raw insight if no unified result -->
      </div>

      <!-- Fallback: show old insight if unified failed -->
      <div v-else-if="store.insightResult" class="fallback-result">
        <div class="summary-hero">
          <div class="summary-label">分析洞察</div>
          <div class="summary-text">{{ store.insightResult.insight.one_liner }}</div>
          <div class="summary-tags">
            <span class="tag tag-algo">{{ store.insightResult.insight.algorithm_type }}</span>
            <span class="tag tag-conf">{{ Math.round(store.insightResult.insight.confidence * 100) }}% 置信度</span>
          </div>
        </div>

        <div v-if="store.insightResult.insight.patterns.length" class="section">
          <div class="section-title">检测到的模式</div>
          <div class="pattern-row">
            <div v-for="p in store.insightResult.insight.patterns" :key="p.name" class="pattern-chip">
              <span class="pattern-name">{{ p.name }}</span>
              <span class="pattern-conf">{{ Math.round(p.confidence * 100) }}%</span>
            </div>
          </div>
        </div>

        <button class="btn btn-secondary" style="margin-top:12px" @click="runFullAnalysis" :disabled="fullLoading">
          {{ fullLoading ? '分析中...' : '生成完整报告' }}
        </button>
      </div>

      <!-- No results yet, trigger button -->
      <div v-else-if="store.hasResults && !fullResult" class="trigger-section">
        <button class="btn btn-primary" @click="runFullAnalysis" :disabled="fullLoading">
          {{ fullLoading ? '分析中...' : '一键生成分析报告' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.insight-panel { height: 100%; overflow-y: auto; }

.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  text-align: center;
  padding: 40px;
}
.welcome-icon { font-size: 64px; margin-bottom: 16px; }
.welcome h2 { font-size: 22px; margin-bottom: 8px; color: var(--text); }
.welcome p { color: var(--text-dim); margin-bottom: 24px; font-size: 14px; }

.feature-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 24px;
  max-width: 500px;
}
.feature-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
  text-align: left;
}
.feature-icon { font-size: 28px; margin-bottom: 8px; }
.feature-title { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
.feature-desc { font-size: 14px; color: var(--text-dim); }

.hint { font-size: 14px; color: var(--text-muted); margin-bottom: 24px; }

.history-section { width: 100%; max-width: 500px; }
.history-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.history-title { font-size: 14px; font-weight: 600; color: var(--text-dim); }
.history-clear { font-size: 14px; color: var(--text-muted); background: none; border: none; cursor: pointer; }
.history-clear:hover { color: var(--error); }
.history-list { display: flex; flex-direction: column; gap: 6px; }
.history-item {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.history-item:hover { border-color: var(--primary); }
.history-func { font-size: 14px; font-weight: 600; }
.history-insight { font-size: 14px; color: var(--text-dim); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-meta { display: flex; gap: 8px; margin-top: 4px; font-size: 14px; }
.history-algo { color: var(--primary); }
.history-time { color: var(--text-muted); }

/* Results */
.results { padding: 0; }

.loading-inline {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px;
  color: var(--text-dim);
  font-size: 14px;
}
.spinner {
  width: 18px; height: 18px;
  border: 2px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.error-box {
  background: rgba(239,68,68,0.08);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: 8px;
  padding: 12px 16px;
  color: var(--error);
  font-size: 14px;
  margin-bottom: 12px;
}

.unified-result, .fallback-result { display: flex; flex-direction: column; gap: 16px; }

/* Summary Hero */
.summary-hero {
  background: linear-gradient(135deg, rgba(251,114,153,0.06), rgba(99,102,241,0.06));
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}
.summary-label { font-size: 14px; font-weight: 600; color: var(--primary); margin-bottom: 8px; }
.summary-text { font-size: 16px; line-height: 1.6; color: var(--text); }
.summary-tags { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.tag { display: inline-block; padding: 3px 10px; border-radius: 6px; font-size: 14px; font-weight: 600; }
.tag-algo { background: rgba(99,102,241,0.1); color: #6366f1; }
.tag-conf { background: rgba(34,197,94,0.1); color: #16a34a; }
.tag-steps { background: rgba(245,158,11,0.1); color: #d97706; }

/* Result */
.result-box {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 16px;
}
.result-label { font-size: 14px; font-weight: 600; color: var(--text-dim); white-space: nowrap; }
.result-value { font-size: 14px; font-family: monospace; color: var(--text); word-break: break-all; }

/* Section */
.section {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
}
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 12px;
}
.section-title.clickable { cursor: pointer; user-select: none; }
.section-title.clickable:hover { color: var(--primary); }
.toggle-arrow { font-size: 14px; margin-left: 6px; color: var(--text-muted); }

/* Patterns */
.pattern-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.pattern-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(99,102,241,0.08);
  border: 1px solid rgba(99,102,241,0.15);
  border-radius: 8px;
  padding: 6px 12px;
}
.pattern-name { font-size: 14px; font-weight: 600; color: #6366f1; }
.pattern-conf { font-size: 14px; color: var(--text-dim); }
.pattern-cmplx { font-size: 14px; color: var(--text-muted); }
.pattern-descs { display: flex; flex-direction: column; gap: 4px; }
.pattern-desc-item { font-size: 14px; color: var(--text-dim); }

/* Phases */
.phase-bar { display: flex; gap: 2px; border-radius: 8px; overflow: hidden; }
.phase-segment {
  background: rgba(99,102,241,0.1);
  padding: 8px 6px;
  text-align: center;
  min-width: 0;
}
.phase-segment:nth-child(2) { background: rgba(34,197,94,0.1); }
.phase-segment:nth-child(3) { background: rgba(245,158,11,0.1); }
.phase-segment:nth-child(4) { background: rgba(239,68,68,0.1); }
.phase-name { font-size: 14px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.phase-count { font-size: 14px; color: var(--text-dim); }

/* Variable Evolution */
.var-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.var-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}
.var-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.var-name { font-size: 14px; font-weight: 700; font-family: monospace; }
.var-type { font-size: 14px; color: var(--text-muted); }
.var-changes { font-size: 14px; color: var(--primary); margin-left: auto; }
.var-flow { display: flex; align-items: center; gap: 6px; }
.var-val {
  font-size: 14px;
  font-family: monospace;
  padding: 2px 6px;
  border-radius: 4px;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.var-first { background: rgba(239,68,68,0.08); color: #dc2626; }
.var-last { background: rgba(34,197,94,0.08); color: #16a34a; }
.var-arrow { color: var(--text-muted); font-size: 14px; }

/* Timeline */
.timeline-list { display: flex; flex-direction: column; gap: 4px; }
.timeline-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 14px;
  background: var(--bg);
}
.timeline-step.loop { background: rgba(99,102,241,0.05); }
.timeline-step.return { background: rgba(34,197,94,0.05); }
.timeline-step.changed { background: rgba(245,158,11,0.03); }
.step-num { font-family: monospace; color: var(--text-muted); font-size: 14px; min-width: 28px; }
.step-code { font-family: monospace; color: var(--text); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step-changed { font-size: 14px; color: var(--primary); font-family: monospace; }
.step-event { font-size: 14px; color: var(--text-muted); padding: 1px 6px; background: rgba(0,0,0,0.04); border-radius: 4px; }

/* Causal Chain */
.causal-mini { display: flex; flex-direction: column; gap: 4px; }
.causal-link {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  padding: 4px 8px;
  border-radius: 4px;
  background: var(--bg);
}
.causal-step { font-family: monospace; color: var(--text-dim); }
.causal-kind { font-size: 14px; padding: 1px 6px; border-radius: 4px; }
.causal-kind.data { background: rgba(99,102,241,0.1); color: #6366f1; }
.causal-kind.control { background: rgba(245,158,11,0.1); color: #d97706; }
.causal-var { font-family: monospace; color: var(--primary); }
.causal-arrow { color: var(--text-muted); }

.trigger-section {
  display: flex;
  justify-content: center;
  padding: 40px;
}
</style>
