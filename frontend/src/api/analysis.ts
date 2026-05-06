const API_BASE = ''

export interface InsightResponse {
  success?: boolean
  error?: string
  error_type?: string
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
}

export interface AnalyzeResponse {
  stats: { nodes: number; edges: number; edge_types: Record<string, number> }
  error_chain: { node_id: string; file_path: string; line_number: number; code_content: string; node_type: string; semantic_label: string; depth: number }[]
  graph_url: string
  nodes: any[]
  edges: any[]
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

export interface DSStepData {
  index: number
  line: number
  code: string
  nodes: Record<string, { id: number; type: string; val: string; attrs: Record<string, string>; refs: Record<string, number>; changed: boolean }>
  edges: { from: number; to: number; label: string; changed: boolean }[]
  var_bindings: Record<string, number>
  changed_objects: number[]
}

function _friendlyError(msg: string, errorType?: string): string {
  if (errorType === 'SyntaxError') return `Syntax error: ${msg}`
  if (errorType === 'IndentationError') return `Indentation error: ${msg}`
  if (errorType === 'NameError') return `Name error: ${msg}`
  if (errorType === 'TypeError') return `Type error: ${msg}`
  if (errorType === 'AttributeError') return `Attribute error: ${msg}`
  if (msg.includes('No function found')) return msg
  return msg
}

export async function analyzeCode(code: string, language = 'python', errorLine?: number, config?: string): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_BASE}/api/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, language, error_line: errorLine, config }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || 'Analysis failed')
  if (data.success === false) throw new Error(_friendlyError(data.error, data.error_type))
  return data
}

export async function getInsight(code: string, funcName = '', language = 'python'): Promise<InsightResponse> {
  const res = await fetch(`${API_BASE}/api/insight`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || 'Insight failed')
  if (data.success === false) throw new Error(_friendlyError(data.error, data.error_type))
  return data
}

export async function getDSViz(code: string, funcName = '', language = 'python'): Promise<DSVizResponse> {
  const res = await fetch(`${API_BASE}/api/ds-viz`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || 'DS Viz failed')
  if (data.success === false) throw new Error(_friendlyError(data.error, data.error_type))
  return data
}

export async function runCode(code: string, funcName = '', timeout = 10): Promise<{ success: boolean; result?: any; error?: string; timed_out?: boolean; stdout?: string; stderr?: string }> {
  const res = await fetch(`${API_BASE}/api/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, timeout }),
  })
  return res.json()
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

export async function getExplain(code: string, funcName = '', language = 'python', provider = 'mock', apiKey = ''): Promise<ExplainResponse> {
  const res = await fetch(`${API_BASE}/api/explain`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language, provider, api_key: apiKey }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || 'Explain failed')
  if (data.success === false) throw new Error(_friendlyError(data.error, data.error_type))
  return data
}

export interface StepExplanation {
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

export interface ExplainStepsResponse {
  explanations: StepExplanation[]
  control_edges?: ControlEdge[]
  loop_groups?: LoopGroup[]
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

export async function getExplainSteps(code: string, funcName = '', language = 'python', provider = 'mock', apiKey = '', sessionId = ''): Promise<ExplainStepsResponse> {
  const res = await fetch(`${API_BASE}/api/explain_steps`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language, provider, api_key: apiKey, session_id: sessionId }),
  })
  const data = await res.json()
  if (!res.ok || data.success === false) return { explanations: [] }
  return {
    explanations: data.explanations || [],
    control_edges: data.control_edges || [],
    loop_groups: data.loop_groups || [],
  }
}

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

export async function getExplainStepFocus(
  code: string, stepIndex: number, funcName = '', language = 'python',
  windowBefore = 2, windowAfter = 2, provider = 'mock', apiKey = '', sessionId = ''
): Promise<FocusedExplanation | null> {
  const res = await fetch(`${API_BASE}/api/explain_step_focus`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      code, func_name: funcName, language, step_index: stepIndex,
      window_before: windowBefore, window_after: windowAfter,
      provider, api_key: apiKey, session_id: sessionId,
    }),
  })
  const data = await res.json()
  if (!res.ok || data.success === false) return null
  return data.explanation || null
}

export async function getPatternNarrative(code: string, funcName = '', language = 'python', sessionId = ''): Promise<PatternNarrativeResponse | null> {
  const res = await fetch(`${API_BASE}/api/pattern_narrative`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language, session_id: sessionId }),
  })
  const data = await res.json()
  if (!res.ok || data.success === false) return null
  return data
}

export interface SubproblemGraphNode {
  id: string
  args: string[]
  result: any
  call_count: number
}

export interface SubproblemGraphEdge {
  from: string
  to: string
}

export interface SubproblemGraphLayout {
  nodes: { id: string; x: number; y: number; label: string; result: any; call_count: number; is_reused: boolean; depth?: number; state_size?: number }[]
  edges: { from: string; to: string; from_pos: { x: number; y: number }; to_pos: { x: number; y: number }; label?: string; size_label?: string }[]
  level_info?: { depth: number; node_count: number; total_calls: number; avg_problem_size: number | null; level_cost: number | null; node_ids: string[] }[]
  width: number
  height: number
  nodeW: number
  nodeH: number
}

export interface CallTreeNode {
  id: string
  args: string[]
  result?: any
  children: CallTreeNode[]
}

export interface SubproblemGraphResponse {
  success?: boolean
  error?: string
  is_recursive: boolean
  result?: any
  dag?: {
    nodes: SubproblemGraphNode[]
    edges: SubproblemGraphEdge[]
    unique_count: number
    total_count: number
  }
  call_tree?: CallTreeNode
  layout?: SubproblemGraphLayout
  complexity?: {
    recurrence: string
    branching_factor: number
    depth: number
    without_cache: string
    with_cache: string
    speedup: string
    total_calls: number
    unique_calls: number
    shared_subproblems: { id: string; called: number }[]
    pattern?: string
    shrink?: string
    execution?: string
    median_ratio?: number
    explanation?: string
    semantic_explanation?: string
    combine_operation?: string
    combine_operation_label?: string
    pattern_hint?: string
    pattern_description?: string
    cognitive_narrative?: string
    auto_summary?: {
      total_calls: number
      unique_subproblems: number
      repeated_calls: number
      depth: number
      branching_factor: number
      complexity: string
      optimized_complexity: string
      speedup: string
      operation: string
      pattern: string
      has_memoization_benefit: boolean
    }
  }
  narrative?: string
}

export async function getSubproblemGraph(code: string, funcName = '', language = 'python'): Promise<SubproblemGraphResponse | null> {
  const res = await fetch(`${API_BASE}/api/subproblem_graph`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  const data = await res.json()
  if (!res.ok || data.success === false) return null
  return data
}
