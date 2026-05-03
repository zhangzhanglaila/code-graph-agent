"""Prompt templates for LLM-based causal reasoning."""

ROOT_CAUSE_ANALYSIS = """You are a code causality analysis expert.

Given the following context, perform structured root cause analysis.

## Error Context
{error_info}

## Code Context (relevant lines)
{code_context}

## Runtime Trace
{runtime_trace}

## Configuration Context
{config_context}

## Causal Graph Edges
{graph_edges}

Analyze the root cause of this error. Return your analysis as a JSON object with EXACTLY this structure:

```json
{{
    "symptom": "The surface-level error symptom",
    "direct_cause": "The direct code line/logic that triggers the error",
    "root_cause": "The root cause (config issue / logic bug / dependency problem)",
    "confidence": 0.95,
    "related_nodes": ["file1.py:42", "file2.py:15"],
    "fix_suggestion": "Suggested fix for the root cause"
}}
```

Important:
- related_nodes must be node_id format (file_path:line_number)
- confidence must be between 0.0 and 1.0
- Be specific about which file and line is the root cause
- If the root cause is a config issue, explain which config key is wrong
"""


CODE_EXISTENCE_REASON = """You are a code causality analysis expert.

Explain WHY the following code line exists — its purpose, dependencies, and what would break if removed.

## Target Code Line
File: {file_path}
Line {line_number}: `{code_line}`

## Surrounding Context (5 lines above/below)
{surrounding_context}

## Callers / Dependencies
{dependencies}

## Configuration References
{config_refs}

## Runtime Execution Info
{runtime_info}

Return your analysis as a JSON object with EXACTLY this structure:

```json
{{
    "purpose": "The business/security/technical purpose of this code line",
    "depends_on": [
        {{"type": "function", "ref": "module.func_name", "reason": "why it depends"}},
        {{"type": "config", "ref": "config.key", "reason": "why it depends"}},
        {{"type": "variable", "ref": "var_name", "reason": "why it depends"}}
    ],
    "removal_consequence": "What would break or change if this line is removed",
    "upstream_logic": "The upstream design decision that necessitates this line",
    "confidence": 0.90
}}
```

Important:
- Be specific about dependencies (use file:line format where possible)
- Explain the "why" not just the "what"
- Consider security, performance, and correctness implications
"""


QUICK_EXPLAIN = """Briefly explain why this code line exists (1-2 sentences):

File: {file_path}
Line {line_number}: `{code_line}`
Context: {context}

Return JSON: {{"purpose": "...", "confidence": 0.85}}
"""
