const API_BASE = ''

export interface InsightResponse {
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

export async function analyzeCode(code: string, language = 'python', errorLine?: number, config?: string): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_BASE}/api/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, language, error_line: errorLine, config }),
  })
  if (!res.ok) throw new Error((await res.json()).detail || 'Analysis failed')
  return res.json()
}

export async function getInsight(code: string, funcName = '', language = 'python'): Promise<InsightResponse> {
  const res = await fetch(`${API_BASE}/api/insight`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  if (!res.ok) throw new Error((await res.json()).detail || 'Insight failed')
  return res.json()
}

export async function getDSViz(code: string, funcName = '', language = 'python'): Promise<DSVizResponse> {
  const res = await fetch(`${API_BASE}/api/ds-viz`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, func_name: funcName, language }),
  })
  if (!res.ok) throw new Error((await res.json()).detail || 'DS Viz failed')
  return res.json()
}
