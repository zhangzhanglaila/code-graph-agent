const API_BASE = ''

// ── Core Types ──────────────────────────────────────────────────

export interface DetectedPattern {
  [key: string]: any
  pattern_name: string
  display_name: string
  description: string
  start_step: number
  end_step: number
  confidence: number
  key_steps: number[]
  sub_patterns?: string[]
}

export interface InsightResponse {
  success?: boolean
  error?: string
  error_type?: string
  session_id?: string
  result: any
  func_name: string
  insight: {
    one_liner: string
    algorithm_type: string
    confidence: number
    patterns: { name: string; confidence: number; description: string }[]
    phases: { name: string; start_step: number; end_step: number; description: string; key_variables: string[]; step_count: number }[]
    explanation_levels: Record<string, string>
  }
  explanation: any
  timeline: StepData[]
  timeline_url: string
  total_steps: number
  detected_patterns?: DetectedPattern[]
}

export interface StepData {
  index: number
  file: string
  line: number
  code: string
  func: string
  vars: Record<string, { value: string; type: string; changed: boolean; is_new: boolean }>
  changed: string[]
  new_vars: string[]
  depth?: number
  call_id?: number
  event_type?: string
  narration?: string
  semantic_tags?: string[]
  visual_priority?: number
}

export interface AnalyzeResponse {
  stats: { nodes: number; edges: number; edge_types: Record<string, number> }
  error_chain: { node_id: string; file_path: string; line_number: number; code_content: string; node_type: string; semantic_label: string; depth: number }[]
  graph_url: string
  nodes: any[]
  edges: any[]
}

export interface DSStepData {
  index: number
  line: number
  code: string
  nodes: Record<string, { id: number; type: string; val: string; attrs: Record<string, string>; refs: Record<string, number>; changed: boolean }>
  edges: { from: number; to: number; label: string; changed: boolean }[]
  var_bindings: Record<string, number>
  changed_objects: number[]
}

export interface DSVizResponse {
  success?: boolean
  error?: string
  result: any
  func_name: string
  steps: DSStepData[]
  total_steps: number
  ds_viz_url: string
}

export interface ExplainResponse {
  success?: boolean
  error?: string
  llm_explanation?: {
    what_it_does?: string
    how_it_works?: string
    why_it_works?: string
    complexity?: { time?: string; space?: string }
    key_moments?: { step: number; what_happened: string; why_it_matters: string }[]
    aha_insight?: string
    teaching_example?: string
  }
  result?: any
  func_name?: string
  total_steps?: number
}

export interface StepExplanation {
  [key: string]: any
  step: number
  explanation: string
  importance: 'high' | 'medium' | 'low'
  importance_score: number
  importance_percentile?: number
  importance_reasons: string[]
  importance_explanation?: string
  affects?: number[]
  signals: { structural: number; dynamic: number; llm: number; future?: number }
  turning_point?: boolean
}

export interface ControlEdge { from: number; to: number; type: 'control' }
export interface LoopGroup { line: number; steps: number[]; label: string }

export interface FocusedExplanation {
  step: number
  explanation: string
  importance: 'high' | 'medium' | 'low'
  importance_score: number
  importance_percentile?: number
  importance_reasons: string[]
  importance_explanation?: string
  affects?: number[]
  signals: { structural: number; dynamic: number; llm: number; future?: number }
  turning_point: boolean
  what_changed: string
}

export interface PatternNarrativeResponse {
  success?: boolean
  error?: string
  pattern: string
  dominant_property: string
  properties: Record<string, { confidence: number; evidence_count: number; evidence_sample: string[] }>
  narrative: string
  complexity: string
  property_names: string[]
}

export interface SubproblemGraphNode { id: string; args: string[]; result: any; call_count: number }
export interface SubproblemGraphEdge { from: string; to: string }
export interface SubproblemGraphLayout {
  nodes: { id: string; x: number; y: number; label: string; result: any; call_count: number; is_reused: boolean; depth?: number; state_size?: number }[]
  edges: { from: string; to: string; from_pos: { x: number; y: number }; to_pos: { x: number; y: number }; label?: string; size_label?: string }[]
  level_info?: { depth: number; node_count: number; total_calls: number; avg_problem_size: number | null; level_cost: number | null; node_ids: string[] }[]
  width: number; height: number; nodeW: number; nodeH: number
}
export interface CallTreeNode { id: string; args: string[]; result?: any; children: CallTreeNode[] }

export interface SubproblemGraphResponse {
  success?: boolean
  error?: string
  is_recursive: boolean
  result?: any
  dag?: { nodes: SubproblemGraphNode[]; edges: SubproblemGraphEdge[]; unique_count: number; total_count: number }
  call_tree?: CallTreeNode
  layout?: SubproblemGraphLayout
  complexity?: {
    recurrence: string; branching_factor: number; depth: number
    without_cache: string; with_cache: string; speedup: string
    total_calls: number; unique_calls: number
    shared_subproblems: { id: string; called: number }[]
    pattern?: string; shrink?: string; execution?: string; median_ratio?: number
    explanation?: string; semantic_explanation?: string
    combine_operation?: string; combine_operation_label?: string
    pattern_hint?: string; pattern_description?: string; cognitive_narrative?: string
    auto_summary?: {
      total_calls: number; unique_subproblems: number; repeated_calls: number
      depth: number; branching_factor: number; complexity: string
      optimized_complexity: string; speedup: string; operation: string
      pattern: string; has_memoization_benefit: boolean
    }
  }
  narrative?: string
}

export interface GitHubAnalyzeRequest { repo_url: string; file_path?: string; func_name?: string; max_files?: number }
export interface GitHubFileAnalysis { file: string; code_lines?: number; insight?: { one_liner?: string; algorithm_type?: string; confidence?: number; patterns?: { name: string; confidence: number; description: string }[] }; total_steps?: number; func_name?: string; error?: string }
export interface GitHubAnalyzeResponse {
  success: boolean; error?: string; error_type?: string; repo_url?: string
  summary?: { total_files: number; analyzed_files: number; total_lines: number; total_execution_steps: number; top_patterns: { name: string; count: number }[] }
  files?: GitHubFileAnalysis[]
}

export interface Narrative {
  title: string; summary: string
  segments: { role: string; heading: string; content: string; priority: number }[]
  variable_stories: { name: string; story: string; versions: number; first_value: string; last_value: string }[]
  metadata: Record<string, unknown>
}

export interface SemanticFact { kind: string; subject: string; description: string; evidence: number[]; confidence: number; metadata: Record<string, unknown> }
export interface QueryResult { success: boolean; error?: string; type?: string; [key: string]: unknown }

export interface FailureAttributionResult {
  success: boolean; error?: string; func_name?: string
  attribution?: { success: boolean; severity: 'healthy' | 'warning' | 'error' | 'critical'; summary: string; findings: { type: string; severity: string; title: string; description: string; steps: number[]; suggestion: string }[]; total_steps: number; max_depth: number }
}

export interface CausalChainResult {
  success: boolean; error?: string; func_name?: string
  causal_chain?: { success: boolean; failure_point?: { type: string; step: number; code: string; line: number }; target_var?: string; causal_chain?: { step: number; var: string; value: string; code: string; line: number; depth: number; role: string }[]; causal_sentences?: string[]; causal_distance?: number; divergence_point?: any; graph_stats?: { total_edges: number; unique_vars: number; max_fan_in: number; versioned?: boolean } }
  pdg_stats?: { nodes: number; edges: number; edge_kinds: Record<string, number>; variables: number; max_depth: number; functions: number }
}

export interface AgentResult {
  success: boolean
  agent?: {
    success: boolean; observation_count: number
    state: { observation_count: number; step_range: number[]; variables: Record<string, { name: string; values: any[]; mutations: number }>; branch_count: number; mutation_count: number; functions: string[] }
    reasoning: { depth: number; overall_confidence: number; steps: Array<{ hypothesis: { id: string; description: string; confidence: number }; evidence: Array<{ kind: string; var?: string; description?: string }>; conclusion: string }> }
    action_plan: { action_count: number }
    action_results: Array<{ action: { kind: string }; success: boolean }>
    duration_ms: number
  }
  error?: string
}

export interface QueryMetrics { total_queries: number; errors: number; uptime_seconds: number; latency: { p50: number; p95: number; p99: number; avg: number; min: number; max: number; count: number }; by_type: Record<string, { count: number; avg_ms: number }>; cache: { hits: number; misses: number; hit_rate: number } }
export interface ExecutionMetrics { stages: Record<string, { count: number; avg_ms: number; p50: number; p95: number; total_ms: number }>; endpoints: Record<string, { count: number; avg_ms: number; p50: number; p95: number; total_ms: number; errors: number }> }
export interface AgentMetricsData { total_runs: number; reasoning: { avg_hypotheses: number; avg_depth: number; avg_evidence_per_hypothesis: number; max_depth: number }; actions: { total: number; success: number; failure: number; success_rate: number }; performance: { avg_duration_ms: number; p95_duration_ms: number } }
export interface AllMetrics { query: QueryMetrics; execution: ExecutionMetrics; agent: AgentMetricsData }

// ── Helpers ─────────────────────────────────────────────────────

function _friendlyError(msg: string, errorType?: string): string {
  if (errorType === 'SyntaxError') return `Syntax error: ${msg}`
  if (errorType === 'IndentationError') return `Indentation error: ${msg}`
  if (errorType === 'NameError') return `Name error: ${msg}`
  if (errorType === 'TypeError') return `Type error: ${msg}`
  if (errorType === 'AttributeError') return `Attribute error: ${msg}`
  if (msg.includes('No function found')) return msg
  return msg
}

function _snippet(text: string): string {
  return text.replace(/\s+/g, ' ').trim().slice(0, 180)
}

async function _readJson<T = any>(res: Response, label: string): Promise<T> {
  const text = await res.text()
  const status = `${res.status} ${res.statusText}`.trim()

  if (!text.trim()) {
    const hint = res.status >= 500 ? ' Backend service may be down or the dev proxy failed.' : ''
    throw new Error(`${label}: empty response from server (${status}).${hint}`)
  }

  try {
    return JSON.parse(text) as T
  } catch {
    const body = _snippet(text)
    throw new Error(`${label}: expected JSON but received ${res.headers.get('content-type') || 'unknown content'} (${status})${body ? `: ${body}` : ''}`)
  }
}

async function _requestJson<T = any>(res: Response, label: string): Promise<T> {
  const data = await _readJson<any>(res, label)
  if (!res.ok) {
    throw new Error(_friendlyError(data.detail || data.error || `${label} failed (${res.status} ${res.statusText})`, data.error_type))
  }
  if (data.success === false) {
    throw new Error(_friendlyError(data.error || data.detail || `${label} failed`, data.error_type))
  }
  return data as T
}

// ── Analysis API ────────────────────────────────────────────────

export async function analyzeCode(code: string, language = 'python', errorLine?: number, config?: string): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_BASE}/api/analyze`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, language, error_line: errorLine, config }),
  })
  return _requestJson<AnalyzeResponse>(res, 'Graph')
}

export async function getInsight(code: string, funcName = '', language = 'python'): Promise<InsightResponse> {
  const res = await fetch(`${API_BASE}/api/insight`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  return _requestJson<InsightResponse>(res, 'Insight')
}

export interface AnalyzeFullResponse {
  success: boolean; summary: string; one_liner: string; algorithm: string; confidence: number; result: string; total_steps: number
  key_patterns: { name: string; description: string; confidence: number; complexity: string }[]
  variables: Record<string, { name: string; first_value: string; last_value: string; type: string; changes: number; first_step: number; last_step: number }>
  key_timeline: { step: number; line: number; code: string; changed_vars: string[]; event: string }[]
  causal_chain: { step: number; target: number; var: string; kind: string }[]
  root_causes: number[]
  phases: { name: string; start_step: number; end_step: number; description: string; key_variables: string[]; step_count: number }[]
  visualizations: { graph_url: string | null }
  error?: string
}

export async function analyzeFull(code: string, funcName = '', language = 'python'): Promise<AnalyzeFullResponse> {
  const res = await fetch(`${API_BASE}/api/analyze_full`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  return _requestJson<AnalyzeFullResponse>(res, 'Analyze full')
}

export async function getDSViz(code: string, funcName = '', language = 'python'): Promise<DSVizResponse> {
  const res = await fetch(`${API_BASE}/api/ds-viz`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  return _requestJson<DSVizResponse>(res, 'DS Viz')
}

export async function getExplain(code: string, funcName = '', language = 'python', provider = 'mock', apiKey = ''): Promise<ExplainResponse> {
  const res = await fetch(`${API_BASE}/api/explain`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language, provider, api_key: apiKey }),
  })
  return _requestJson<ExplainResponse>(res, 'Explain')
}

export async function getExplainSteps(code: string, funcName = '', language = 'python', provider = 'mock', apiKey = '', sessionId = ''): Promise<{ explanations: StepExplanation[]; control_edges?: ControlEdge[]; loop_groups?: LoopGroup[] }> {
  const res = await fetch(`${API_BASE}/api/explain_steps`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language, provider, api_key: apiKey, session_id: sessionId }),
  })
  const data = await _readJson<any>(res, 'Explain steps')
  if (!res.ok || data.success === false) return { explanations: [] }
  return { explanations: data.explanations || [], control_edges: data.control_edges || [], loop_groups: data.loop_groups || [] }
}

export async function getExplainStepFocus(
  code: string, stepIndex: number, funcName = '', language = 'python',
  windowBefore = 2, windowAfter = 2, provider = 'mock', apiKey = '', sessionId = ''
): Promise<FocusedExplanation | null> {
  const res = await fetch(`${API_BASE}/api/explain_step_focus`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language, step_index: stepIndex, window_before: windowBefore, window_after: windowAfter, provider, api_key: apiKey, session_id: sessionId }),
  })
  const data = await _readJson<any>(res, 'Explain step focus')
  if (!res.ok || data.success === false) return null
  return data.explanation || null
}

export async function getPatternNarrative(code: string, funcName = '', language = 'python', sessionId = ''): Promise<PatternNarrativeResponse | null> {
  const res = await fetch(`${API_BASE}/api/pattern_narrative`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language, session_id: sessionId }),
  })
  const data = await _readJson<any>(res, 'Pattern narrative')
  if (!res.ok || data.success === false) return null
  return data
}

export async function getSubproblemGraph(code: string, funcName = '', language = 'python'): Promise<SubproblemGraphResponse | null> {
  const res = await fetch(`${API_BASE}/api/subproblem_graph`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  const data = await _readJson<any>(res, 'Subproblem graph')
  if (!res.ok || data.success === false) return null
  return data
}

export async function getFailureAttribution(code: string, funcName: string, language: string): Promise<FailureAttributionResult> {
  const res = await fetch(`${API_BASE}/api/failure_attribution`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  return _requestJson<FailureAttributionResult>(res, 'Failure attribution')
}

export async function getCausalChain(code: string, funcName: string, language: string): Promise<CausalChainResult> {
  const res = await fetch(`${API_BASE}/api/causal_chain`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  return _requestJson<CausalChainResult>(res, 'Causal chain')
}

// ── GitHub API ──────────────────────────────────────────────────

export async function analyzeGitHubRepo(req: GitHubAnalyzeRequest): Promise<GitHubAnalyzeResponse> {
  const res = await fetch(`${API_BASE}/api/github_analyze`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  return _requestJson<GitHubAnalyzeResponse>(res, 'GitHub analyze')
}

export async function getImportGraph(req: GitHubAnalyzeRequest): Promise<{ success: boolean; error?: string; nodes?: { id: string; module: string; import_count: number }[]; edges?: { from: string; to: string; type: string; name?: string; line?: number }[]; stats?: any }> {
  const res = await fetch(`${API_BASE}/api/import_graph`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  return _requestJson<{ success: boolean; error?: string; nodes?: { id: string; module: string; import_count: number }[]; edges?: { from: string; to: string; type: string; name?: string; line?: number }[]; stats?: any }>(res, 'Import graph')
}

// ── Query API ───────────────────────────────────────────────────

export async function query(code: string, funcName: string, language: string, q: Record<string, unknown>): Promise<QueryResult> {
  const res = await fetch(`${API_BASE}/api/query`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language, query: q }),
  })
  return _requestJson<QueryResult>(res, 'Query')
}

export async function textQuery(code: string, funcName: string, language: string, text: string): Promise<QueryResult> {
  const res = await fetch(`${API_BASE}/api/query`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language, text }),
  })
  return _requestJson<QueryResult>(res, 'Text query')
}

export async function getIdentity(code: string, funcName: string, language: string): Promise<QueryResult> {
  const res = await fetch(`${API_BASE}/api/identity`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  return _requestJson<QueryResult>(res, 'Identity')
}

export async function semanticDiff(codeA: string, codeB: string, funcName: string, language: string): Promise<QueryResult> {
  const res = await fetch(`${API_BASE}/api/semantic_diff`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code_a: codeA, code_b: codeB, func_name: funcName, language }),
  })
  return _requestJson<QueryResult>(res, 'Semantic diff')
}

export async function getSimilarity(codeA: string, codeB: string, funcName: string, language: string): Promise<QueryResult> {
  const res = await fetch(`${API_BASE}/api/similarity`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code_a: codeA, code_b: codeB, func_name: funcName, language }),
  })
  return _requestJson<QueryResult>(res, 'Similarity')
}

// ── Agent API ───────────────────────────────────────────────────

export async function agentAnalyze(code: string, funcName = '', language = 'python', question = ''): Promise<AgentResult> {
  const res = await fetch(`${API_BASE}/api/agent/analyze`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language, question }),
  })
  return _requestJson<AgentResult>(res, 'Agent analyze')
}

// ── Metrics API ─────────────────────────────────────────────────

export async function getAllMetrics(): Promise<AllMetrics> {
  const res = await fetch(`${API_BASE}/api/metrics`)
  return _requestJson<AllMetrics>(res, 'Metrics')
}

export async function resetMetrics(): Promise<{ success: boolean }> {
  const res = await fetch(`${API_BASE}/api/metrics/reset`, { method: 'POST' })
  return _requestJson<{ success: boolean }>(res, 'Reset metrics')
}
