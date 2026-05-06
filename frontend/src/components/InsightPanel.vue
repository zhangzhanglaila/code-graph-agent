<script setup lang="ts">
import { useAnalysisStore } from '../store/analysisStore'
import { getInsight, analyzeCode, getDSViz } from '../api/analysis'

const store = useAnalysisStore()

function timeAgo(ts: number): string {
  const diff = Date.now() - ts
  if (diff < 60000) return 'just now'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
  return `${Math.floor(diff / 86400000)}d ago`
}

async function loadHistory(entry: any) {
  store.loadFromHistory(entry)
  store.loading = true
  store.error = ''
  store.reset()
  try {
    const results = await Promise.allSettled([
      getInsight(store.code, store.funcName, store.language),
      analyzeCode(store.code, store.language),
      getDSViz(store.code, store.funcName, store.language),
    ])
    if (results[0].status === 'fulfilled') store.insightResult = results[0].value
    if (results[1].status === 'fulfilled') store.analyzeResult = results[1].value
    if (results[2].status === 'fulfilled') store.dsVizResult = results[2].value
  } catch (e: any) {
    store.error = e.message
  } finally {
    store.loading = false
  }
}
</script>

<template>
  <div class="insight-panel">
    <!-- Welcome state -->
    <div v-if="!(store?.hasResults ?? false)" class="welcome">
      <div class="welcome-icon">&#x1F9E0;</div>
      <h2>粘贴代码，理解一切</h2>
      <p>Why-Code-Agent 分析你的代码并解释：</p>
      <div class="feature-grid">
        <div class="feature-card">
          <div class="feature-icon">&#x1F50D;</div>
          <div class="feature-title">为什么是这个结果</div>
          <div class="feature-desc">变量谱系与关键路径追踪</div>
        </div>
        <div class="feature-card">
          <div class="feature-icon">&#x1F4CA;</div>
          <div class="feature-title">算法结构</div>
          <div class="feature-desc">模式检测与阶段压缩</div>
        </div>
        <div class="feature-card">
          <div class="feature-icon">&#x1F4A1;</div>
          <div class="feature-title">一句话洞察</div>
          <div class="feature-desc">认知级解释生成</div>
        </div>
        <div class="feature-card">
          <div class="feature-icon">&#x1F9EC;</div>
          <div class="feature-title">数据结构</div>
          <div class="feature-desc">指针动画与遍历可视化</div>
        </div>
      </div>
      <p class="hint">在上方粘贴代码并点击 <strong>分析</strong>，或尝试示例</p>

      <!-- History -->
      <div v-if="(store?.history ?? []).length" class="history-section">
        <div class="history-header">
          <span class="history-title">最近分析</span>
          <button class="history-clear" @click="store?.clearHistory()">清空</button>
        </div>
        <div class="history-list">
          <div
            v-for="entry in (store?.history ?? []).slice(0, 5)" :key="entry.id"
            class="history-item"
            @click="loadHistory(entry)"
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
    <div v-else class="results animate-slide-up">
      <!-- One-liner insight -->
      <div class="insight-hero">
        <div class="insight-label">分析洞察</div>
        <div class="insight-text">{{ store?.insightResult?.insight.one_liner }}</div>
        <div class="insight-meta">
          <span class="tag tag-confidence">{{ store?.insightResult?.insight.algorithm_type }}</span>
          <span class="tag tag-confidence">{{ Math.round((store?.insightResult?.insight.confidence ?? 0) * 100) }}% 置信度</span>
          <span class="tag tag-pattern">{{ store?.insightResult?.total_steps ?? 0 }} 步</span>
        </div>
      </div>

      <!-- AI Explanation (LLM-powered) -->
      <div v-if="store?.explainResult?.llm_explanation" class="ai-explain">
        <div class="ai-header">
          <span class="ai-icon">AI</span>
          <span class="ai-title">执行感知解释</span>
        </div>

        <div class="ai-section" v-if="store?.explainResult.llm_explanation.what_it_does">
          <div class="ai-label">做了什么</div>
          <div class="ai-text">{{ store?.explainResult.llm_explanation.what_it_does }}</div>
        </div>

        <div class="ai-section" v-if="store?.explainResult.llm_explanation.how_it_works">
          <div class="ai-label">如何运作</div>
          <div class="ai-text">{{ store?.explainResult.llm_explanation.how_it_works }}</div>
        </div>

        <div class="ai-section" v-if="store?.explainResult.llm_explanation.why_it_works">
          <div class="ai-label">为什么有效</div>
          <div class="ai-text">{{ store?.explainResult.llm_explanation.why_it_works }}</div>
        </div>

        <div class="ai-complexity" v-if="store?.explainResult.llm_explanation.complexity">
          <span v-if="store?.explainResult.llm_explanation.complexity.time" class="complexity-tag">
            时间: {{ store?.explainResult.llm_explanation.complexity.time }}
          </span>
          <span v-if="store?.explainResult.llm_explanation.complexity.space" class="complexity-tag">
            空间: {{ store?.explainResult.llm_explanation.complexity.space }}
          </span>
        </div>

        <div class="ai-section" v-if="store?.explainResult.llm_explanation.aha_insight">
          <div class="ai-label aha-label">顿悟</div>
          <div class="ai-text aha-text">{{ store?.explainResult.llm_explanation.aha_insight }}</div>
        </div>

        <div class="ai-section" v-if="store?.explainResult.llm_explanation.teaching_example">
          <div class="ai-label">类比</div>
          <div class="ai-text">{{ store?.explainResult.llm_explanation.teaching_example }}</div>
        </div>

        <div class="ai-moments" v-if="store?.explainResult.llm_explanation.key_moments?.length">
          <div class="ai-label">关键时刻</div>
          <div v-for="m in store?.explainResult.llm_explanation.key_moments" :key="m.step" class="moment-card">
            <span class="moment-step">步骤 {{ m.step }}</span>
            <div class="moment-info">
              <div class="moment-what">{{ m.what_happened }}</div>
              <div class="moment-why">{{ m.why_it_matters }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Result -->
      <div class="result-box">
        <div class="result-label">结果</div>
        <div class="result-value">{{ formatResult(store?.insightResult?.result) }}</div>
      </div>

      <!-- Patterns -->
      <div class="section" v-if="store?.insightResult?.insight.patterns.length">
        <div class="section-title">检测到的模式</div>
        <div class="patterns">
          <div v-for="p in store?.insightResult?.insight.patterns" :key="p.name" class="pattern-card">
            <div class="pattern-name">{{ p.name }}</div>
            <div class="pattern-desc">{{ p.description }}</div>
            <div class="pattern-conf">{{ Math.round(p.confidence * 100) }}%</div>
          </div>
        </div>
      </div>

      <!-- Phases -->
      <div class="section" v-if="store?.insightResult?.insight.phases.length">
        <div class="section-title">执行阶段</div>
        <div class="phases">
          <div v-for="(phase, i) in store?.insightResult?.insight.phases" :key="i" class="phase-card">
            <div class="phase-num">{{ i + 1 }}</div>
            <div class="phase-info">
              <div class="phase-name">{{ phase.name }}</div>
              <div class="phase-desc">{{ phase.description }}</div>
              <div class="phase-meta">
                步骤 {{ phase.start_step }}-{{ phase.end_step }} ({{ phase.step_count }} 步)
                <span v-if="phase.key_variables.length"> | {{ phase.key_variables.join(', ') }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Explanation levels -->
      <div class="section">
        <div class="section-title">解释层级</div>
        <div class="levels">
          <div v-for="(val, key) in store?.insightResult?.insight.explanation_levels" :key="key" class="level-block">
            <div class="level-label">{{ key }}</div>
            <pre class="level-content">{{ val }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
function formatResult(result: any): string {
  if (result === null || result === undefined) return 'null'
  if (typeof result === 'object') {
    const s = JSON.stringify(result)
    return s.length > 200 ? s.slice(0, 200) + '...' : s
  }
  return String(result)
}
</script>

<style scoped>
.insight-panel { height: 100%; }

.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: 40px;
}

.welcome-icon { font-size: 64px; margin-bottom: 16px; }

.welcome h2 {
  font-size: 22px;
  margin-bottom: 8px;
  color: var(--text);
}

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
  transition: all 0.3s;
}

.feature-card:hover {
  border-color: var(--primary);
  transform: translateY(-2px);
}

.feature-icon { font-size: 24px; margin-bottom: 8px; }
.feature-title { font-size: 13px; font-weight: 600; color: var(--text); }
.feature-desc { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

.hint { color: var(--text-muted); font-size: 12px; }
.hint strong { color: var(--primary); }

.history-section {
  margin-top: 32px;
  width: 100%;
  max-width: 500px;
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.history-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-dim);
}

.history-clear {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 8px;
  border-radius: 4px;
}

.history-clear:hover {
  color: var(--primary);
  background: rgba(251,114,153,0.1);
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.history-item {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.history-item:hover {
  border-color: var(--primary);
  transform: translateX(4px);
}

.history-func {
  font-size: 13px;
  font-weight: 600;
  color: var(--highlight);
  font-family: monospace;
}

.history-insight {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
}

.history-algo {
  font-size: 10px;
  color: var(--primary);
}

.history-time {
  font-size: 10px;
  color: var(--text-muted);
}

/* Results */
.results { padding: 0; }

.insight-hero {
  background: linear-gradient(135deg, rgba(251,114,153,0.08), rgba(0,161,214,0.08));
  border: 1px solid rgba(251,114,153,0.15);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
}

.insight-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  letter-spacing: 2px;
  margin-bottom: 8px;
}

.insight-text {
  font-size: 18px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--text);
}

.insight-meta {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.result-box {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 16px;
}

/* AI Explanation */
.ai-explain {
  background: linear-gradient(135deg, rgba(0,161,214,0.05), rgba(167,139,250,0.05));
  border: 1px solid rgba(0,161,214,0.15);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
}

.ai-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.ai-icon {
  background: linear-gradient(135deg, var(--highlight), var(--accent));
  color: #1e293b;
  font-size: 10px;
  font-weight: 800;
  padding: 3px 8px;
  border-radius: 4px;
  letter-spacing: 1px;
}

.ai-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--highlight);
}

.ai-section {
  margin-bottom: 12px;
}

.ai-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 4px;
}

.ai-text {
  font-size: 14px;
  color: var(--text);
  line-height: 1.6;
}

.ai-complexity {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.complexity-tag {
  font-size: 12px;
  font-family: monospace;
  background: rgba(167,139,250,0.1);
  color: var(--accent);
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid rgba(167,139,250,0.2);
}

.aha-label {
  color: var(--primary);
}

.aha-text {
  font-size: 16px;
  font-weight: 600;
  color: var(--primary);
  line-height: 1.5;
}

.ai-moments {
  margin-top: 12px;
}

.moment-card {
  display: flex;
  gap: 10px;
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-top: 6px;
}

.moment-step {
  font-size: 11px;
  font-weight: 700;
  color: var(--highlight);
  min-width: 50px;
  flex-shrink: 0;
}

.moment-what {
  font-size: 12px;
  color: var(--text);
}

.moment-why {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.result-label { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }
.result-value { font-family: monospace; font-size: 14px; color: var(--highlight); word-break: break-all; }

.section { margin-bottom: 16px; }
.section-title { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 8px; }

.patterns { display: flex; flex-wrap: wrap; gap: 8px; }

.pattern-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  flex: 1;
  min-width: 150px;
}

.pattern-name { font-size: 13px; font-weight: 600; color: var(--highlight); }
.pattern-desc { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
.pattern-conf { font-size: 11px; color: var(--success); margin-top: 4px; }

.phases { display: flex; flex-direction: column; gap: 8px; }

.phase-card {
  display: flex;
  gap: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}

.phase-num {
  width: 28px;
  height: 28px;
  background: var(--primary);
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.phase-name { font-size: 13px; font-weight: 600; }
.phase-desc { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
.phase-meta { font-size: 10px; color: var(--text-muted); margin-top: 4px; }

.levels { display: flex; flex-direction: column; gap: 8px; }

.level-block {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.level-label {
  padding: 6px 12px;
  background: rgba(251,114,153,0.1);
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
  border-bottom: 1px solid var(--border);
}

.level-content {
  padding: 10px 12px;
  font-size: 12px;
  font-family: monospace;
  color: var(--text-dim);
  white-space: pre-wrap;
  margin: 0;
  max-height: 200px;
  overflow-y: auto;
}
</style>
