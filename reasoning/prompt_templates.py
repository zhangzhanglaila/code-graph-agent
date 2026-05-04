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


STEP_EXPLAIN_BATCH = """You are a programming teacher explaining code execution step by step.

A student is stepping through code execution. For EACH step below, explain what happens and why it matters.

## Code
```python
{code}
```

## Context
Function `{func_name}` — {algorithm_summary}

## Steps to explain
{steps_json}

For each step, write a 1-2 sentence explanation. Be specific about:
- WHAT changed (variable values, state)
- WHY this step matters for the algorithm
- The INVARIANT or insight at this moment

Return a JSON array with one object per step:
```json
[
    {{"step": 0, "explanation": "...", "importance": "high|medium|low"}},
    {{"step": 1, "explanation": "...", "importance": "high|medium|low"}}
]
```

Rules:
- "importance" = "high" for steps that are algorithmically critical (key assignments, loop boundaries, returns)
- "importance" = "medium" for meaningful state changes
- "importance" = "low" for boilerplate / minor updates
- Be concise. Each explanation should be 1-2 sentences max.
- Use the variable values from the trace to make explanations concrete.
- Reference what CHANGED at this step, not what the line generally does.
"""


EXECUTION_EXPLAIN = """You are a world-class programming teacher and code explainer.

A user ran the following code and you have FULL access to its execution trace.
Your job is to explain this code at a cognitive level — not what each line does, but WHY it works and HOW it thinks.

## Code
```python
{code}
```

## Execution Result
Function `{func_name}()` returned: `{result}`

## Execution Timeline ({total_steps} steps)
{timeline}

## Detected Patterns
{patterns}

## Execution Phases
{phases}

## Variable Lineage (how the result was computed)
{lineage}

---

Produce a JSON explanation with this structure:

```json
{{
    "what_it_does": "One sentence: what this code accomplishes (the GOAL, not the mechanics)",
    "how_it_works": "2-3 sentences: the algorithm/approach explained like a senior dev would to a junior. Use analogies if helpful.",
    "why_it_works": "1-2 sentences: the key insight that makes this approach correct. What invariant or property holds?",
    "complexity": {{
        "time": "O(...) with brief justification",
        "space": "O(...) with brief justification"
    }},
    "key_moments": [
        {{
            "step": 3,
            "what_happened": "brief description",
            "why_it_matters": "why this step is important to understanding the code"
        }}
    ],
    "aha_insight": "The ONE thing a student should remember about this code. The 'aha' moment. 1 sentence.",
    "teaching_example": "If you were teaching this concept, what real-world analogy would you use? 1-2 sentences."
}}
```

Rules:
- Write for a CS student who knows basics but hasn't seen this algorithm
- Focus on the WHY, not the WHAT
- The "aha_insight" should be genuinely insightful — something that makes the code "click"
- key_moments should pick the 2-3 most important steps, not all steps
- Be concise. Every word should earn its place.
"""
