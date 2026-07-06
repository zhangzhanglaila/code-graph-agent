import { computed } from 'vue'
import type { StepData } from '../api/analysis'
import { useAnalysisStore } from '../store/analysisStore'

type PhaseKind = 'input' | 'setup' | 'loop' | 'branch' | 'mutation' | 'output'

export interface SemanticPhase {
  id: PhaseKind
  title: string
  summary: string
  color: string
  steps: number[]
  lines: number[]
  variables: string[]
  signals: string[]
}

export interface SemanticStep {
  index: number
  line: number
  code: string
  kind: PhaseKind
  title: string
  variables: string[]
  reads: string[]
  writes: string[]
  evidence: string
}

export interface VariableRole {
  name: string
  role: string
  confidence: number
  changes: number
  reads: number
  firstStep: number
  lastStep: number
  firstValue: string
  lastValue: string
  evidence: string[]
  color: string
}

export interface SemanticMetric {
  label: string
  value: string | number
}

export interface SemanticLink {
  from: number
  to: number
  variable: string
}

interface VarStats {
  name: string
  changes: number
  reads: number
  firstStep: number
  lastStep: number
  firstValue: string
  lastValue: string
  values: string[]
  evidence: string[]
  loopWrites: number
}

const PHASE_META: Record<PhaseKind, { title: string; summary: string; color: string }> = {
  input: { title: '输入与调用', summary: '函数参数和初始运行上下文进入执行轨迹', color: '#2563eb' },
  setup: { title: '状态准备', summary: '初始化临时变量、容器或默认状态', color: '#7c3aed' },
  loop: { title: '迭代推进', summary: '循环、遍历或游标推进形成主要执行节奏', color: '#0891b2' },
  branch: { title: '分支判断', summary: '条件保护、边界判断或提前跳出', color: '#d97706' },
  mutation: { title: '状态更新', summary: '变量、容器或对象引用发生关键变化', color: '#059669' },
  output: { title: '结果输出', summary: '返回值或最终状态被交付', color: '#dc2626' },
}

const BUILTINS = new Set([
  'if', 'else', 'elif', 'for', 'while', 'return', 'def', 'class', 'import', 'from', 'as',
  'with', 'try', 'except', 'finally', 'raise', 'pass', 'break', 'continue', 'and', 'or',
  'not', 'in', 'is', 'True', 'False', 'None', 'range', 'len', 'int', 'str', 'float',
  'list', 'dict', 'set', 'tuple', 'print', 'append', 'extend', 'sorted', 'reversed',
  'enumerate', 'zip', 'map', 'filter', 'sum', 'min', 'max', 'abs', 'type', 'isinstance',
  'self', 'cls', 'super', 'lambda', 'yield', 'global', 'nonlocal', 'key', 'item', 'value',
])

function cleanCode(code?: string): string {
  return String(code || '').trim()
}

function valueOf(raw: unknown): string {
  if (raw == null) return ''
  if (typeof raw === 'object' && 'value' in (raw as any)) return String((raw as any).value)
  return String(raw)
}

function unique<T>(items: T[]): T[] {
  return [...new Set(items)]
}

function extractIdentifiers(code: string): string[] {
  return unique((code.match(/\b[a-zA-Z_]\w*\b/g) || []).filter(x => !BUILTINS.has(x)))
}

function isAssignment(code: string): boolean {
  return /(^|[^=!<>])=([^=>]|$)/.test(code) || /\+=|-=|\*=|\/=|%=/.test(code)
}

function classifyStep(step: StepData, position: number): PhaseKind {
  const code = cleanCode(step.code)
  const writes = unique([...(step.changed || []), ...(step.new_vars || [])])
  if (position === 0 && !writes.length) return 'input'
  if (/^return\b/.test(code)) return 'output'
  if (/^(if|elif)\b|^else\b|^try\b|^except\b/.test(code)) return 'branch'
  if (/^(for|while)\b/.test(code) || /\bcontinue\b|\bbreak\b/.test(code)) return 'loop'
  if (/\.(append|extend|insert|pop|add|remove|update)\s*\(/.test(code)) return 'mutation'
  if (/\[[^\]]+\]\s*=/.test(code) || /\.\w+\s*=/.test(code)) return 'mutation'
  if (writes.length && (position <= 2 || step.new_vars?.length)) return 'setup'
  if (writes.length || isAssignment(code)) return 'mutation'
  return 'loop'
}

function stepTitle(kind: PhaseKind, code: string): string {
  if (kind === 'input') return '进入函数'
  if (kind === 'setup') return '准备状态'
  if (kind === 'loop') {
    if (/^for\b/.test(code)) return '遍历循环'
    if (/^while\b/.test(code)) return '条件循环'
    return '推进迭代'
  }
  if (kind === 'branch') return '执行判断'
  if (kind === 'output') return '返回结果'
  if (/\[[^\]]+\]\s*=/.test(code)) return '写入容器'
  if (/\+=|-=|\*=|\/=|%=/.test(code)) return '累积更新'
  if (/,.*=.*,\s*/.test(code)) return '并行状态迁移'
  return '更新状态'
}

function inferReads(step: StepData, writes: string[]): string[] {
  const vars = Object.keys(step.vars || {})
  const writeSet = new Set(writes)
  return extractIdentifiers(cleanCode(step.code)).filter(name => vars.includes(name) && !writeSet.has(name))
}

function evidenceFor(kind: PhaseKind, step: StepData, reads: string[], writes: string[]): string {
  if (kind === 'input') return `第 ${step.index} 步建立调用上下文`
  if (kind === 'output') return `第 ${step.index} 步返回 ${cleanCode(step.code).replace(/^return\s*/, '') || '结果'}`
  if (kind === 'branch') return `第 ${step.index} 步读取 ${reads.join(', ') || '当前状态'} 做判断`
  if (kind === 'loop') return `第 ${step.index} 步位于循环/推进路径`
  if (kind === 'setup') return `第 ${step.index} 步创建 ${writes.join(', ') || '初始状态'}`
  return `第 ${step.index} 步写入 ${writes.join(', ') || '运行状态'}`
}

function roleColor(role: string): string {
  if (role.includes('累加')) return '#059669'
  if (role.includes('迭代')) return '#0891b2'
  if (role.includes('结果')) return '#dc2626'
  if (role.includes('映射') || role.includes('表')) return '#7c3aed'
  if (role.includes('游标') || role.includes('指针')) return '#2563eb'
  if (role.includes('集合')) return '#9333ea'
  return '#475569'
}

function inferVariableRole(name: string, stats: VarStats, steps: StepData[]): { role: string; confidence: number; evidence: string[] } {
  const evidence = [...stats.evidence]
  const lower = name.toLowerCase()
  const last = stats.lastValue
  const codes = steps.map(s => cleanCode(s.code))
  const writesInLoop = stats.loopWrites > 0
  const returned = codes.some(c => new RegExp(`^return\\b.*\\b${name}\\b`).test(c))
  const iterated = codes.some(c => new RegExp(`^for\\s+${name}\\b`).test(c))
  const indexedWrite = codes.some(c => new RegExp(`\\b${name}\\s*\\[`).test(c))
  const pointerMove = codes.some(c => new RegExp(`\\b${name}\\s*=\\s*\\b${name}\\.`).test(c))

  if (returned) {
    evidence.push('出现在 return 语句中')
    return { role: '结果载体', confidence: 0.95, evidence }
  }
  if (/memo|cache|dp|table|map|dict/.test(lower) || indexedWrite || /^\{/.test(last)) {
    evidence.push(indexedWrite ? '存在下标写入' : '值形态像映射表')
    return { role: '映射/记忆表', confidence: 0.9, evidence }
  }
  if (/visited|seen|set/.test(lower) || /^set\(|^\{.*\}$/.test(last)) {
    evidence.push('变量名或值形态像集合')
    return { role: '集合状态', confidence: 0.84, evidence }
  }
  if (/node|cur|curr|current|head|tail|root|left|right|next/.test(lower) || pointerMove) {
    evidence.push(pointerMove ? '自引用字段推进' : '变量名像遍历游标')
    return { role: '游标/指针', confidence: 0.86, evidence }
  }
  if (iterated) {
    evidence.push('作为 for 循环变量出现')
    return { role: '迭代变量', confidence: 0.92, evidence }
  }
  if (stats.changes >= 2 && writesInLoop && /^-?\d+(\.\d+)?$/.test(last)) {
    evidence.push('在循环中多次变化且保持数值形态')
    return { role: '累加/计数状态', confidence: 0.9, evidence }
  }
  if (stats.changes >= 2 && writesInLoop) {
    evidence.push('在迭代过程中多次更新')
    return { role: '滚动状态', confidence: 0.78, evidence }
  }
  if (/^\[/.test(last) || /^\(/.test(last)) {
    evidence.push('最终值是序列形态')
    return { role: '序列状态', confidence: 0.72, evidence }
  }
  if (stats.changes > 0) {
    evidence.push('被执行轨迹写入')
    return { role: '中间状态', confidence: 0.65, evidence }
  }
  evidence.push('被执行轨迹读取')
  return { role: '输入/只读值', confidence: 0.62, evidence }
}

function buildVarStats(steps: StepData[], semanticSteps: SemanticStep[]): Map<string, VarStats> {
  const stats = new Map<string, VarStats>()

  function ensure(name: string, step: StepData): VarStats {
    if (!stats.has(name)) {
      stats.set(name, {
        name,
        changes: 0,
        reads: 0,
        firstStep: step.index,
        lastStep: step.index,
        firstValue: valueOf(step.vars?.[name]),
        lastValue: valueOf(step.vars?.[name]),
        values: [],
        evidence: [],
        loopWrites: 0,
      })
    }
    return stats.get(name)!
  }

  for (const step of steps) {
    for (const name of Object.keys(step.vars || {})) {
      const s = ensure(name, step)
      const value = valueOf(step.vars[name])
      if (!s.firstValue) s.firstValue = value
      s.lastValue = value
      s.lastStep = step.index
      if (value) s.values.push(value)
    }
  }

  const stepByIndex = new Map(semanticSteps.map(s => [s.index, s]))
  for (const step of steps) {
    const sem = stepByIndex.get(step.index)
    const writes = unique([...(step.changed || []), ...(step.new_vars || [])])
    const reads = sem?.reads || []
    for (const name of writes) {
      const s = ensure(name, step)
      s.changes++
      if (sem?.kind === 'loop' || sem?.kind === 'mutation') s.loopWrites++
      s.evidence.push(`第 ${step.index} 步写入`)
    }
    for (const name of reads) {
      const s = ensure(name, step)
      s.reads++
    }
  }

  return stats
}

export function useSemanticModel() {
  const store = useAnalysisStore()

  const steps = computed<StepData[]>(() => store.timeline || [])

  const semanticSteps = computed<SemanticStep[]>(() => {
    return steps.value.map((step, position) => {
      const writes = unique([...(step.changed || []), ...(step.new_vars || [])])
      const reads = inferReads(step, writes)
      const kind = classifyStep(step, position)
      const code = cleanCode(step.code)
      return {
        index: step.index,
        line: step.line,
        code,
        kind,
        title: stepTitle(kind, code),
        variables: unique([...writes, ...reads]),
        reads,
        writes,
        evidence: evidenceFor(kind, step, reads, writes),
      }
    })
  })

  const phases = computed<SemanticPhase[]>(() => {
    const groups = new Map<PhaseKind, SemanticStep[]>()
    for (const step of semanticSteps.value) {
      if (!groups.has(step.kind)) groups.set(step.kind, [])
      groups.get(step.kind)!.push(step)
    }

    return (Object.keys(PHASE_META) as PhaseKind[])
      .filter(kind => groups.has(kind))
      .map(kind => {
        const items = groups.get(kind)!
        const meta = PHASE_META[kind]
        const variables = unique(items.flatMap(s => s.variables)).slice(0, 8)
        const repeatedLines = unique(items.map(s => s.line).filter(Boolean))
        return {
          id: kind,
          title: meta.title,
          summary: meta.summary,
          color: meta.color,
          steps: items.map(s => s.index),
          lines: repeatedLines,
          variables,
          signals: [
            `${items.length} 个步骤`,
            repeatedLines.length ? `代码行 ${repeatedLines.join(', ')}` : '无行号',
            variables.length ? `变量 ${variables.join(', ')}` : '无变量变化',
          ],
        }
      })
  })

  const variableRoles = computed<VariableRole[]>(() => {
    const stats = buildVarStats(steps.value, semanticSteps.value)
    return [...stats.values()]
      .filter(s => s.name && !s.name.startsWith('__'))
      .map(s => {
        const inferred = inferVariableRole(s.name, s, steps.value)
        return {
          name: s.name,
          role: inferred.role,
          confidence: inferred.confidence,
          changes: s.changes,
          reads: s.reads,
          firstStep: s.firstStep,
          lastStep: s.lastStep,
          firstValue: s.firstValue,
          lastValue: s.lastValue,
          evidence: unique(inferred.evidence).slice(0, 4),
          color: roleColor(inferred.role),
        }
      })
      .sort((a, b) => b.confidence - a.confidence || b.changes - a.changes || a.name.localeCompare(b.name))
  })

  const algorithmLabel = computed(() => {
    const insight = store.insightResult?.insight
    const fromInsight = insight?.algorithm_type && insight.algorithm_type !== 'unknown' ? insight.algorithm_type : ''
    if (fromInsight) return fromInsight
    const hasLoop = phases.value.some(p => p.id === 'loop')
    const hasTable = variableRoles.value.some(v => v.role.includes('表'))
    const hasBranch = phases.value.some(p => p.id === 'branch')
    if (hasLoop && hasTable) return '迭代 + 状态表'
    if (hasLoop && hasBranch) return '迭代 + 条件控制'
    if (hasLoop) return '线性迭代'
    if (hasBranch) return '条件分支'
    return '顺序执行'
  })

  const metrics = computed<SemanticMetric[]>(() => {
    const loopLines = phases.value.find(p => p.id === 'loop')?.lines.length || 0
    const branchSteps = phases.value.find(p => p.id === 'branch')?.steps.length || 0
    const mutations = semanticSteps.value.filter(s => s.kind === 'mutation' || s.writes.length).length
    return [
      { label: '执行步数', value: steps.value.length },
      { label: '语义阶段', value: phases.value.length },
      { label: '变量角色', value: variableRoles.value.length },
      { label: '循环行数', value: loopLines },
      { label: '分支次数', value: branchSteps },
      { label: '状态更新', value: mutations },
    ]
  })

  const semanticLinks = computed<SemanticLink[]>(() => {
    const raw = store.causalEdges || []
    return raw.slice(0, 24).map((edge: any) => ({
      from: Number(edge.from),
      to: Number(edge.to),
      variable: String(edge.var || edge.variable || ''),
    }))
  })

  const hotLines = computed(() => {
    const counts = new Map<number, number>()
    for (const step of steps.value) {
      if (!step.line) continue
      counts.set(step.line, (counts.get(step.line) || 0) + 1)
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([line, count]) => ({ line, count }))
  })

  const summary = computed(() => {
    const first = store.insightResult?.insight?.one_liner
    if (first) return first
    const mainVars = variableRoles.value.slice(0, 3).map(v => `${v.name}=${v.role}`).join('，')
    return `${algorithmLabel.value}，围绕 ${mainVars || '运行状态'} 展开。`
  })

  return {
    steps,
    semanticSteps,
    phases,
    variableRoles,
    algorithmLabel,
    metrics,
    semanticLinks,
    hotLines,
    summary,
  }
}
