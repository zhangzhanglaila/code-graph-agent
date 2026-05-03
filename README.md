# Why-Code-Agent

Code Causality Intelligence — locate error root causes and explain why any code line exists.

## What It Does

**Why-Code-Agent** builds a causal graph of your codebase by fusing static analysis with runtime traces, then uses LLM reasoning to answer two questions:

1. **Why did this error happen?** — Trace backwards from an error through the causal graph to find the true root cause (often a wrong config value, not the line that threw).

2. **Why does this line exist?** — Given any code line, explain its purpose, dependencies, and what would break if you removed it.

### Key Differentiators

Unlike AST/CFG tools that show structure, Why-Code-Agent focuses on **causal relationships** — data flow, config influence, call chains, and runtime execution paths fused into a single graph.

| Feature | AST/CFG Tools | Why-Code-Agent |
|---------|--------------|----------------|
| Code structure | Yes | Yes |
| Config → code influence | No | Yes |
| Runtime trace fusion | No | Yes |
| "Why does this line exist?" | No | Yes |
| Structured root cause JSON | No | Yes |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the demo (login failure with planted config bug)
python main.py demo
```

The demo analyzes a login failure caused by a negative `token_ttl` in `demo/config.yaml`. The causal chain traces:

```
config:auth.token_ttl  --[CONFIG_INFLUENCE]-->  auth.py:17 (reads TTL)
auth.py:17  --[DATA_DEPENDENCY]-->  token.py:8 (creates token)
token.py:8  --[RUNTIME_TRACE]-->  token.py:14 (checks validity)
token.py:14  --[THROWS]-->  auth.py:29 (raises RuntimeError)
```

The root cause is `config.yaml` line `token_ttl: -300`, not the code that raises the error.

## Usage

### Full Analysis

```bash
# Analyze a project for a specific error
python main.py analyze --project demo/ --error demo/auth.py:29 --config demo/config.yaml

# With custom LLM provider
python main.py analyze --project demo/ --error demo/auth.py:29 --provider openai --model gpt-4
```

### Explain Code Line

```bash
# Ask why a specific line exists
python main.py explain --file demo/auth.py --line 17
```

Output:
```json
{
  "purpose": "Reads token TTL from configuration to set token expiration",
  "depends_on": [
    {"type": "config", "ref": "auth.token_ttl", "reason": "TTL value comes from config"},
    {"type": "function", "ref": "load_config", "reason": "Config loading function"}
  ],
  "removal_consequence": "Tokens would have no expiration, creating a security vulnerability",
  "confidence": 0.92
}
```

### Output

- `output/causal_graph.html` — Interactive graph (open in browser, nodes are clickable)
- `output/analysis_results.json` — Structured root cause analysis

## Architecture

```
core/           Graph abstraction (replaceable with Neo4j)
  graph.py      CausalGraph — directed graph with 6 edge types
  node.py       CodeNode — represents code lines and config items
  edge_types.py DATA_DEPENDENCY | CALL_RELATION | CONFIG_INFLUENCE |
                RUNTIME_TRACE | THROWS | CONTROL_FLOW

static/         Static analysis (AST-based for Python, regex for JS)
  python_analyzer.py   Python AST → causal graph
  js_analyzer.py       JS/TS regex → causal graph
  config_linker.py     Parse YAML/JSON config, link to code

dynamic/        Runtime tracing (non-invasive)
  tracer.py            sys.settrace line-level tracer
  exception_parser.py  Parse tracebacks → THROWS edges

fusion/         Merge static + dynamic graphs
  merge_engine.py      Dedup nodes, merge edges, incremental update

reasoning/      LLM-powered structured analysis
  prompt_templates.py  Standardized prompts for JSON output
  llm_reasoner.py      Anthropic/OpenAI integration with mock fallback

query/          Graph traversal for root cause
  root_cause.py        Reverse BFS, chain generation, existence queries

visualization/  Interactive graph rendering
  graph_ui.py          Pyvis HTML with edge-type coloring and tooltips

demo/           Planted bug scenario
  auth.py              Login logic (reads config, creates token)
  token.py             Token TTL validation
  config.yaml          BUG: token_ttl = -300
```

## Edge Types

| Type | Color | Meaning |
|------|-------|---------|
| DATA_DEPENDENCY | Blue | Variable/parameter flow between lines |
| CALL_RELATION | Green | Function call chain |
| CONFIG_INFLUENCE | Orange (dashed) | Config value → code that reads it |
| RUNTIME_TRACE | Pink | Actual execution path from tracing |
| THROWS | Red (dashed) | Exception propagation |
| CONTROL_FLOW | Purple | Branching (if/for/while) |

## Configuration

Set LLM API key:

```bash
export ANTHROPIC_API_KEY=sk-...   # For Anthropic Claude
export OPENAI_API_KEY=sk-...      # For OpenAI GPT
```

Without an API key, the system uses mock responses (confidence 0.5) for demonstration.

## Extending

### Add Python analyzer patterns
Edit `static/python_analyzer.py` — add new `visit_*` methods for additional AST node types.

### Add JS/TS analyzer patterns
Edit `static/js_analyzer.py` — extend the regex patterns.

### Use Neo4j instead of in-memory graph
Replace `CausalGraph` in `core/graph.py` with a Neo4j-backed implementation. The interface (`add_node`, `add_edge`, `get_incoming`, `reverse_bfs`) stays the same.

### Add new edge types
Add entries to `EdgeType` in `core/edge_types.py` and update `EDGE_STYLES`.

## Tech Stack

- **Python 3.10+** — core runtime
- **AST** — Python static analysis
- **sys.settrace** — non-invasive line-level tracing
- **Pyvis** — interactive graph visualization
- **Anthropic/OpenAI SDK** — LLM structured reasoning
- **PyYAML** — config parsing
