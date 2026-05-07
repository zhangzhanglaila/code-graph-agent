const API_BASE = ''

export interface SemanticOperation {
  op: string
  structure: string
  actors: string[]
  direction: string
  combines: string
  terminates: string
}

export interface CognitiveNarrative {
  headline: string
  mechanism: string
  strategy: string
  temporal_facts: string[]
  analogies: string[]
  lattice_path: string[]
  confidence: number
}

export interface TemporalFactData {
  predicate: string
  subject: string
  confidence: number
  description: string
}

export interface InvariantData {
  name: string
  predicate: string
  category: string
  confidence: number
  description: string
  holds: number
  violations: number
  depends_on: string[]
}

export interface CausalEdgeData {
  cause: number
  effect: number
  type: string
  variable?: string
  confidence: number
  description: string
}

export interface GoalData {
  type: string
  target: string
  variable?: string
  evidence: string[]
  confidence: number
  description: string
}

export interface CounterfactualData {
  condition: string
  consequence: string
  severity: string
  confidence: number
  affected_invariant: string
  category: string
}

export interface ComputationalMotifData {
  motif: string
  description: string
  evidence: string[]
  confidence: number
  depth: number
}

export interface ConstraintSummary {
  total_facts: number
  observed: number
  derived: number
  by_kind: Record<string, number>
  rules_applied: number
  strata?: Record<string, number>
}

export interface ReasoningDAGNode {
  id: string
  kind: string
  subject: string
  relation: string
  value: any
  source: string
  confidence: number
  evidence: string
  rule: string
  stratum?: number
  stratum_name?: string
}

export interface ReasoningDAGEdge {
  from: string
  to: string
  rule: string
}

export interface ReasoningDAG {
  nodes: ReasoningDAGNode[]
  edges: ReasoningDAGEdge[]
}

export interface DetectedPattern {
  pattern_name: string
  display_name: string
  description: string
  start_step: number
  end_step: number
  confidence: number
  key_steps: number[]
  sub_patterns?: string[]
  semantic?: SemanticOperation
  narrative?: CognitiveNarrative
  temporal?: TemporalFactData[]
  invariants?: InvariantData[]
  causal_edges?: CausalEdgeData[]
  goals?: GoalData[]
  counterfactuals?: CounterfactualData[]
  motifs?: ComputationalMotifData[]
  constraint_summary?: ConstraintSummary
  reasoning_dag?: ReasoningDAG
  conflicts?: ConflictData[]
  actions?: ActionData[]
}

export interface ConflictData {
  fact_a: string
  fact_b: string
  kind: string
  relation_a: string
  relation_b: string
  subject: string
}

export interface ActionData {
  action_type: string
  title: string
  description: string
  priority: number
  confidence: number
  target_line?: number
  target_variable?: string
  evidence: string[]
  preconditions: string[]
  expected_outcome: string
  effort: string
  impact: string
  from_goal?: string
  from_invariant?: string
  from_counterfactual?: string
}

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
  detected_patterns?: DetectedPattern[]
}

export interface PointerMoveData {
  pointer: string
  from_object?: string
  to_object?: string
  via: string
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
  // Semantic IR fields (from AST narrator)
  event_type?: string
  narration?: string
  semantic_tags?: string[]
  visual_priority?: number
  pointer_move?: PointerMoveData
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


// ─── GitHub Repository Analysis ──────────────────────────────────

export interface GitHubAnalyzeRequest {
  repo_url: string
  file_path?: string
  func_name?: string
  max_files?: number
}

export interface GitHubFileAnalysis {
  file: string
  code_lines?: number
  insight?: {
    one_liner?: string
    algorithm_type?: string
    confidence?: number
    patterns?: { name: string; confidence: number; description: string }[]
  }
  total_steps?: number
  func_name?: string
  error?: string
}

export interface GitHubAnalyzeResponse {
  success: boolean
  error?: string
  error_type?: string
  repo_url?: string
  summary?: {
    total_files: number
    analyzed_files: number
    total_lines: number
    total_execution_steps: number
    top_patterns: { name: string; count: number }[]
  }
  files?: GitHubFileAnalysis[]
}

export async function analyzeGitHubRepo(req: GitHubAnalyzeRequest): Promise<GitHubAnalyzeResponse> {
  const res = await fetch(`${API_BASE}/api/github_analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  return res.json()
}


// ─── Failure Attribution API ──────────────────────────────────────

export interface FailureFinding {
  type: string
  severity: 'healthy' | 'warning' | 'error' | 'critical'
  title: string
  description: string
  steps: number[]
  suggestion: string
}

export interface FailureAttributionResult {
  success: boolean
  error?: string
  func_name?: string
  attribution?: {
    success: boolean
    severity: 'healthy' | 'warning' | 'error' | 'critical'
    summary: string
    findings: FailureFinding[]
    total_steps: number
    max_depth: number
  }
}

export async function getFailureAttribution(code: string, funcName: string, language: string): Promise<FailureAttributionResult> {
  const res = await fetch(`${API_BASE}/api/failure_attribution`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  return res.json()
}


// ─── Cross-file Import Graph API ─────────────────────────────────

export interface ImportGraphNode {
  id: string
  module: string
  import_count: number
}

export interface ImportGraphEdge {
  from: string
  to: string
  type: 'import' | 'from_import'
  name?: string
  line?: number
}

export interface ImportGraphResult {
  success: boolean
  error?: string
  repo_url?: string
  nodes?: ImportGraphNode[]
  edges?: ImportGraphEdge[]
  external_deps?: string[]
  stats?: {
    total_files: number
    total_edges: number
    external_deps: number
    most_imported: { file: string; count: number }[]
    most_dependencies: { file: string; count: number }[]
  }
}

export async function getImportGraph(req: GitHubAnalyzeRequest): Promise<ImportGraphResult> {
  const res = await fetch(`${API_BASE}/api/import_graph`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  return res.json()
}


// ─── P14: Execution Feedback Loop API ────────────────────────────

export interface ActionOutcomeRequest {
  execution_id: string
  action_type: string
  action_title: string
  step_count_before?: number
  step_count_after?: number
  time_complexity_before?: string
  time_complexity_after?: string
  invariant_violations_before?: number
  invariant_violations_after?: number
  total_calls_before?: number
  total_calls_after?: number
  code_before?: string
  code_after?: string
  user_feedback?: 'accepted' | 'rejected' | 'modified'
  notes?: string
}

export interface ActionOutcomeResponse {
  success: boolean
  execution_id?: string
  delta_metrics?: Record<string, number>
  memory_summary?: {
    total_executions: number
    success_rates: Record<string, number>
    title_success_rates: Record<string, number>
    best_actions: [string, number][]
    worst_actions: [string, number][]
  }
  error?: string
}

export interface FeedbackLoopStatus {
  success: boolean
  summary?: {
    memory: {
      total_executions: number
      success_rates: Record<string, number>
      title_success_rates: Record<string, number>
      best_actions: [string, number][]
      worst_actions: [string, number][]
    }
    pending_executions: number
    policy: {
      exploration_rate: number
    }
  }
}

export async function recordActionOutcome(req: ActionOutcomeRequest): Promise<ActionOutcomeResponse> {
  const res = await fetch(`${API_BASE}/api/action_outcome`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  return res.json()
}

export async function getFeedbackLoopStatus(): Promise<FeedbackLoopStatus> {
  const res = await fetch(`${API_BASE}/api/feedback_loop_status`)
  return res.json()
}

export interface PrepareExecutionRequest {
  action_type: string
  action_title: string
  step_count?: number
  time_complexity?: string
  invariant_violations?: number
  total_calls?: number
  code_before?: string
}

export interface PrepareExecutionResponse {
  success: boolean
  execution_id?: string
}

export async function prepareExecution(req: PrepareExecutionRequest): Promise<PrepareExecutionResponse> {
  const res = await fetch(`${API_BASE}/api/prepare_execution`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  return res.json()
}


// ─── P15: Memory Consolidation API ───────────────────────────────

export interface ConsolidationStatus {
  success: boolean
  summary?: {
    experience_buffer_size: number
    consolidation_count: number
    last_consolidation: number
    concept_memory: {
      total_concepts: number
      by_type: Record<string, number>
      avg_confidence: number
      avg_evidence: number
    }
  }
}

export interface ConceptData {
  concept_id: string
  name: string
  description: string
  pattern: string
  action_type: string
  confidence: number
  evidence_count: number
  success_rate: number
  tags: string[]
  use_count: number
}

export interface ConceptQueryRequest {
  action_type?: string
  tags?: string[]
  top_k?: number
}

export interface ConceptQueryResponse {
  success: boolean
  concepts?: ConceptData[]
}

export interface ConceptSummaryResponse {
  success: boolean
  summary?: {
    total_concepts: number
    by_type: Record<string, number>
    avg_confidence: number
    avg_evidence: number
  }
  top_concepts?: {
    name: string
    description: string
    confidence: number
    evidence_count: number
    success_rate: number
  }[]
}

export async function getConsolidationStatus(): Promise<ConsolidationStatus> {
  const res = await fetch(`${API_BASE}/api/consolidation_status`)
  return res.json()
}

export async function triggerConsolidation(): Promise<{ success: boolean; summary?: any }> {
  const res = await fetch(`${API_BASE}/api/consolidate`, { method: 'POST' })
  return res.json()
}

export async function queryConcepts(req: ConceptQueryRequest): Promise<ConceptQueryResponse> {
  const res = await fetch(`${API_BASE}/api/query_concepts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  return res.json()
}

export async function getConceptSummary(): Promise<ConceptSummaryResponse> {
  const res = await fetch(`${API_BASE}/api/concept_summary`)
  return res.json()
}


// ─── P16: Concept Validation API ─────────────────────────────────

export interface ValidationStatus {
  success: boolean
  summary?: {
    validation_count: number
    last_validation: number
    invalidator: {
      total_invalidated: number
      reasons: Record<string, string>
    }
    validator_history_count: number
  }
  lifecycle_distribution?: Record<string, number>
}

export interface InvalidConcept {
  concept_id: string
  name: string
  description: string
  confidence: number
  evidence_count: number
  success_rate: number
  reason: string
}

export interface ValidationHistoryEntry {
  concept_id: string
  timestamp: number
  old_state: string
  new_state: string
  reason: string
  evidence_count: number
  success_rate: number
  counter_examples: string[]
}

export async function getValidationStatus(): Promise<ValidationStatus> {
  const res = await fetch(`${API_BASE}/api/validation_status`)
  return res.json()
}

export async function validateConcepts(): Promise<{ success: boolean; results?: Record<string, string>; summary?: any }> {
  const res = await fetch(`${API_BASE}/api/validate_concepts`, { method: 'POST' })
  return res.json()
}

export async function getInvalidConcepts(): Promise<{ success: boolean; invalid_concepts?: InvalidConcept[] }> {
  const res = await fetch(`${API_BASE}/api/invalid_concepts`)
  return res.json()
}

export async function getValidationHistory(conceptId?: string): Promise<{ success: boolean; history?: ValidationHistoryEntry[] }> {
  const url = conceptId
    ? `${API_BASE}/api/validation_history?concept_id=${conceptId}`
    : `${API_BASE}/api/validation_history`
  const res = await fetch(url)
  return res.json()
}
