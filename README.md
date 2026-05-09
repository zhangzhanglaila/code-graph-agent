# Why-Code-Agent

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**秒级定位 Bug 根因。解释任意一行代码为什么存在。**

---

## 它能做什么

每个开发者都会问的两个问题：

| 问题 | 命令 | 输出 |
|------|------|------|
| **这个 Bug 为什么发生？** | `python main.py analyze --error auth.py:37` | 从报错行回溯到根因的因果链 |
| **这行代码为什么存在？** | `python main.py explain --file auth.py --line 17` | 用途、依赖、删除风险 |
| **结果为什么是 X？** | `python main.py explain-why --module mymod --func foo` | 变量血缘 + 关键路径 |
| **逐步展示执行过程** | `python main.py timeline --module mymod --func foo` | 交互式执行时间轴 |
| **因果图 + 时间轴联动** | `python main.py unified --module mymod --func foo` | 左图右时间轴，点击联动 |

---

## 杀手级 Demo：配置 Bug

```bash
python main.py demo
```

**场景**：登录永远失败。报错在 `auth.py:37`：

```python
raise RuntimeError(f"Token expired immediately! TTL={ttl}s is invalid")
```

**常规调试**：看第 37 行，修 raise？错。

**Why-Code-Agent 输出**：

```
因果链（报错 → 根因）：

  auth.py:37    raise RuntimeError(...)        ← 报错在这里
  token.py:22   return is_valid
  token.py:21   is_valid = current_time < expires_at
  token.py:8    token_data = { ... expires_at: time.time() + ttl ... }
  auth.py:33    token = create_token(username, ttl)
  auth.py:22    ttl = config["auth"]["token_ttl"]    ← 读取配置
  config.yaml   auth.token_ttl = -300                ← 根因在这里
```

Bug 在 **config.yaml**，不在代码。`token_ttl: -300` 导致 Token 创建即过期。

---

## 三层架构

```
┌─────────────────────────────────────────────┐
│  WHY + HOW 统一视图                          │
│  （点击时间轴步骤 → 高亮因果图节点）          │
├──────────────────────┬──────────────────────┤
│  WHY（因果图）        │  HOW（时间轴）        │
│  静态分析             │  状态录制             │
│  配置关联             │  变量 diff            │
│  调用链               │  逐步回放             │
├──────────────────────┴──────────────────────┤
│  融合引擎（静态 + 动态合并）                  │
│  LLM 推理器（结构化 JSON 输出）               │
└─────────────────────────────────────────────┘
```

**WHY 层**：AST 静态分析 → 因果图，6 种边类型（数据依赖、调用关系、配置影响、运行时路径、异常传播、控制流）。

**HOW 层**：`sys.settrace` 逐行录制变量状态。计算 diff：什么变了、什么是新增的、什么消失了。检测变量间引用关系。

**融合层**：合并静态结构与运行时行为。图同时知道"什么可能影响什么"和"什么实际影响了什么"。

---

## 快速开始

```bash
pip install pyyaml

# 运行杀手级 Demo
python main.py demo

# 解释函数为什么返回这个结果
python main.py explain-why --module demo.timeline_demo --func fibonacci

# 因果图 + 时间轴统一视图
python main.py unified --module demo.timeline_demo --func list_traversal --project demo/

# 分析你自己的代码
python main.py analyze --project src/ --error src/auth.py:42 --config config.yaml
```

---

## 输出文件

| 文件 | 内容 |
|------|------|
| `output/causal_graph.html` | 交互式因果图（点击节点、悬停查看详情） |
| `output/execution_timeline.html` | 逐步回放，带变量状态 |
| `output/unified_view.html` | 图 + 时间轴并排，点击联动 |
| `output/explain_why.json` | 结构化结果解释 |
| `output/analysis_results.json` | 根因分析数据 |

---

## 6 种因果边

| 边类型 | 颜色 | 含义 |
|--------|------|------|
| DATA_DEPENDENCY | 蓝色 | 变量/参数在行间流动 |
| CALL_RELATION | 绿色 | 函数调用链 |
| CONFIG_INFLUENCE | 橙色虚线 | 配置项 → 读取它的代码 |
| RUNTIME_TRACE | 粉色 | 实际执行路径 |
| THROWS | 红色虚线 | 异常传播 |
| CONTROL_FLOW | 紫色 | 分支（if/for/while） |

---

## 目录结构

```
core/              图抽象层（内存图，可替换 Neo4j）
static/            静态分析（Python AST / JS 正则 / 配置关联）
dynamic/           动态追踪（sys.settrace / 状态录制 / 异常解析）
fusion/            图融合引擎（静态 + 动态合并、增量更新）
reasoning/         LLM 推理（结构化 Prompt / 结果解释器）
query/             根因查询（反向 BFS / 因果链生成）
visualization/     可视化（因果图 / 时间轴 / 统一视图）
demo/              演示场景（登录失败 Bug / 遍历演示）
```

---

## LLM 集成

```bash
export ANTHROPIC_API_KEY=sk-...   # Claude
export OPENAI_API_KEY=sk-...      # GPT-4
```

未设置 API Key 时使用 mock 响应，可正常运行 Demo。

---

## 技术栈

- Python 3.10+ / AST / sys.settrace
- Pyvis（图可视化）
- Anthropic Claude / OpenAI GPT（结构化推理）
- PyYAML（配置解析）

---

---

# English

**Find the root cause of any bug in seconds. Explain why any line of code exists.**

---

## What It Does

Two questions every developer asks:

| Question | Command | Output |
|----------|---------|--------|
| **Why did this bug happen?** | `python main.py analyze --error auth.py:37` | Root cause chain from error to config |
| **Why does this line exist?** | `python main.py explain --file auth.py --line 17` | Purpose, dependencies, removal risk |
| **Why is the result X?** | `python main.py explain-why --module mymod --func foo` | Variable lineage + critical path |
| **Show me step by step** | `python main.py timeline --module mymod --func foo` | Interactive execution timeline |
| **Both at once** | `python main.py unified --module mymod --func foo` | Graph + timeline in one page |

---

## Killer Demo: Config Bug

```bash
python main.py demo
```

**Scenario**: Login always fails. The error is at `auth.py:37`:

```python
raise RuntimeError(f"Token expired immediately! TTL={ttl}s is invalid")
```

**Naive debugging**: The error is on line 37. Fix the raise? No.

**Why-Code-Agent output**:

```
Causal Chain (error → root cause):

  auth.py:37    raise RuntimeError(...)        ← error here
  token.py:22   return is_valid
  token.py:21   is_valid = current_time < expires_at
  token.py:8    token_data = { ... expires_at: time.time() + ttl ... }
  auth.py:33    token = create_token(username, ttl)
  auth.py:22    ttl = config["auth"]["token_ttl"]    ← reads config
  config.yaml   auth.token_ttl = -300                ← ROOT CAUSE
```

The bug is in **config.yaml**, not in the code. `token_ttl: -300` creates tokens that are already expired.

---

## The Three Layers

```
┌─────────────────────────────────────────────┐
│  WHY + HOW Unified View                     │
│  (click timeline step → highlight graph)    │
├──────────────────────┬──────────────────────┤
│  WHY (Causal Graph)  │  HOW (Timeline)      │
│  Static analysis     │  State recording     │
│  Config linking      │  Variable diffs      │
│  Call chains         │  Step-by-step replay │
├──────────────────────┴──────────────────────┤
│  Fusion Engine (merge static + dynamic)     │
│  LLM Reasoner (structured JSON output)      │
└─────────────────────────────────────────────┘
```

**WHY layer**: Static AST analysis → causal graph with 6 edge types (data dependency, call relation, config influence, runtime trace, throws, control flow).

**HOW layer**: `sys.settrace` records every variable at every line. Computes diffs: what changed, what's new, what's gone. Detects references between variables.

**Fusion**: Merge static structure with runtime behavior. The graph knows both "what could affect what" and "what actually affected what."

---

## Quick Start

```bash
pip install pyyaml

# Run the killer demo
python main.py demo

# Explain why a function returns its result
python main.py explain-why --module demo.timeline_demo --func fibonacci

# Unified graph + timeline view
python main.py unified --module demo.timeline_demo --func list_traversal --project demo/

# Analyze your own code
python main.py analyze --project src/ --error src/auth.py:42 --config config.yaml
```

---

## Output Files

| File | What |
|------|------|
| `output/causal_graph.html` | Interactive graph (click nodes, hover for details) |
| `output/execution_timeline.html` | Step-by-step replay with variable states |
| `output/unified_view.html` | Graph + timeline side by side, cross-linked |
| `output/explain_why.json` | Structured result explanation |
| `output/analysis_results.json` | Root cause analysis data |

---

## Edge Types

| Edge | Color | Meaning |
|------|-------|---------|
| DATA_DEPENDENCY | Blue | Variable flows between lines |
| CALL_RELATION | Green | Function call chain |
| CONFIG_INFLUENCE | Orange dashed | Config value → code that reads it |
| RUNTIME_TRACE | Pink | Actual execution path |
| THROWS | Red dashed | Exception propagation |
| CONTROL_FLOW | Purple | Branching (if/for/while) |

---

## Architecture

```
core/              Graph abstraction (in-memory, Neo4j-pluggable)
static/            Static analysis (Python AST / JS regex / config linking)
dynamic/           Runtime tracing (sys.settrace / state recorder / exception parser)
fusion/            Graph merging (static + dynamic, incremental update)
reasoning/         LLM reasoning (structured prompts / result explainer)
query/             Root cause queries (reverse BFS / chain generation)
visualization/     Interactive output (graph / timeline / unified view)
demo/              Demo scenarios (login failure bug / traversal demos)
```

---

## LLM Integration

```bash
export ANTHROPIC_API_KEY=sk-...   # Claude
export OPENAI_API_KEY=sk-...      # GPT-4
```

Without API key: mock responses for demo purposes.

---

## Tech Stack

- Python 3.10+ / AST / sys.settrace
- Pyvis (graph visualization)
- Anthropic Claude / OpenAI GPT (structured reasoning)
- PyYAML (config parsing)
