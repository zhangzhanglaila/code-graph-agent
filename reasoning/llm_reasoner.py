"""LLM-based structured causal reasoning engine."""

from __future__ import annotations
import json
import os
import re
from typing import Any, Dict, List, Optional

from core.graph import CausalGraph
from core.node import CodeNode
from core.edge_types import EdgeType
from reasoning.prompt_templates import (
    ROOT_CAUSE_ANALYSIS,
    CODE_EXISTENCE_REASON,
    QUICK_EXPLAIN,
    EXECUTION_EXPLAIN,
    STEP_EXPLAIN_BATCH,
)


class LLMReasoner:
    """Structured causal reasoning using LLM (supports Anthropic/OpenAI)."""

    def __init__(self, provider: str = "anthropic", model: str = "claude-sonnet-4-20250514", api_key: Optional[str] = None):
        self.provider = provider
        self.model = model
        self.api_key = api_key or os.environ.get(
            "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY", ""
        )

    # ── Public API ───────────────────────────────────────────────────

    def analyze_root_cause(
        self,
        error_info: str,
        graph: CausalGraph,
        error_node_id: Optional[str] = None,
    ) -> dict:
        """Analyze root cause of an error given the causal graph."""
        context = self._build_error_context(graph, error_node_id)
        prompt = ROOT_CAUSE_ANALYSIS.format(**context)
        raw = self._call_llm(prompt)
        return self._extract_json(raw)

    def explain_code_existence(
        self,
        file_path: str,
        line_number: int,
        graph: CausalGraph,
    ) -> dict:
        """Explain why a code line exists."""
        node_id = CodeNode.make_id(file_path, line_number)
        node = graph.get_node(node_id)
        if not node:
            return {"error": f"Node {node_id} not found in graph"}

        context = self._build_existence_context(file_path, line_number, node, graph)
        prompt = CODE_EXISTENCE_REASON.format(**context)
        raw = self._call_llm(prompt)
        result = self._extract_json(raw)

        # Store result on node
        node.existence_reason = result.get("purpose", "")
        node.root_cause_info = result
        return result

    def quick_explain(
        self,
        file_path: str,
        line_number: int,
        code_line: str,
        context: str = "",
    ) -> dict:
        """Quick one-shot explanation of a code line."""
        prompt = QUICK_EXPLAIN.format(
            file_path=file_path,
            line_number=line_number,
            code_line=code_line,
            context=context,
        )
        raw = self._call_llm(prompt)
        return self._extract_json(raw)

    def explain_execution(
        self,
        code: str,
        func_name: str,
        result: Any,
        timeline_steps: list,
        patterns: list,
        phases: list,
        lineage: str = "",
    ) -> dict:
        """Generate cognitive-level explanation from execution trace data."""
        # Format timeline (compact — key steps only)
        timeline_lines = []
        for step in timeline_steps[:40]:  # Cap at 40 steps to control prompt size
            vars_str = ", ".join(
                f"{k}={v['value'][:30]}" for k, v in list(step.get("vars", {}).items())[:6]
            )
            marker = " >>" if step.get("changed") else "   "
            timeline_lines.append(
                f"{marker} step {step['index']}: line {step['line']} | {step['code'][:60]} | {vars_str}"
            )
        timeline_text = "\n".join(timeline_lines) if timeline_lines else "(no steps)"

        # Format patterns
        patterns_text = "\n".join(
            f"- {p['name']} ({p['confidence']*100:.0f}%): {p['description']}"
            for p in patterns
        ) if patterns else "(none detected)"

        # Format phases
        phases_text = "\n".join(
            f"- {p['name']} (steps {p['start_step']}-{p['end_step']}): {p['description']}"
            for p in phases
        ) if phases else "(none detected)"

        prompt = EXECUTION_EXPLAIN.format(
            code=code,
            func_name=func_name,
            result=repr(result)[:200],
            total_steps=len(timeline_steps),
            timeline=timeline_text,
            patterns=patterns_text,
            phases=phases_text,
            lineage=lineage or "(not available)",
        )
        raw = self._call_llm(prompt)
        return self._extract_json(raw)

    def explain_steps_batch(
        self,
        code: str,
        func_name: str,
        timeline_steps: list,
        algorithm_summary: str = "",
    ) -> list:
        """Generate step-by-step explanations for all steps in one batch call."""
        # Build compact step descriptions
        step_lines = []
        for step in timeline_steps[:60]:
            changed = step.get("changed", [])
            new_vars = step.get("new_vars", [])
            var_snippets = []
            for name, v in list(step.get("vars", {}).items())[:5]:
                marker = "*" if name in changed else ("+" if name in new_vars else " ")
                var_snippets.append(f"{marker}{name}={v['value'][:25]}")
            vars_str = ", ".join(var_snippets)
            step_lines.append(
                f"Step {step['index']}: line {step['line']} | {step.code if hasattr(step, 'code') else step.get('code', '')[:50]} | {vars_str}"
            )

        steps_text = "\n".join(step_lines)

        prompt = STEP_EXPLAIN_BATCH.format(
            code=code,
            func_name=func_name,
            algorithm_summary=algorithm_summary or f"Execution of {func_name}()",
            steps_json=steps_text,
        )
        raw = self._call_llm(prompt)
        result = self._extract_json(raw)

        if isinstance(result, list):
            return result
        # If wrapped in an object, try to extract array
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return v
        return [{"step": i, "explanation": "", "importance": "medium"} for i in range(len(timeline_steps))]

    # ── Context builders ─────────────────────────────────────────────

    def _build_error_context(self, graph: CausalGraph, error_node_id: Optional[str]) -> dict:
        error_info = ""
        code_lines = []
        runtime_lines = []
        config_lines = []
        edge_lines = []

        # Find error node
        if error_node_id:
            enode = graph.get_node(error_node_id)
            if enode:
                error_info = f"{enode.semantic_label}\n  at {enode.file_path}:{enode.line_number}"

        # Collect relevant nodes
        for nid, node in graph.nodes.items():
            line = f"  {nid}: {node.code_content}"
            if node.node_type == "CONFIG":
                config_lines.append(line)
            elif node.node_type == "ERROR":
                error_info = error_info or node.semantic_label
            else:
                code_lines.append(line)

        # Collect edges
        for src, dst, etype, _ in graph.edges:
            edge_lines.append(f"  {src} --[{etype.value}]--> {dst}")

        return {
            "error_info": error_info or "(no error node found)",
            "code_context": "\n".join(code_lines[:50]) or "(none)",
            "runtime_trace": "\n".join(runtime_lines[:30]) or "(no runtime trace)",
            "config_context": "\n".join(config_lines[:20]) or "(no config items)",
            "graph_edges": "\n".join(edge_lines[:50]) or "(no edges)",
        }

    def _build_existence_context(
        self, file_path: str, line_number: int, node: CodeNode, graph: CausalGraph
    ) -> dict:
        # Surrounding context
        surrounding = self._read_surrounding(file_path, line_number, context_lines=5)

        # Dependencies (incoming edges)
        deps = []
        for src_id, etype in graph.get_incoming(node.node_id):
            src = graph.get_node(src_id)
            if src:
                deps.append(f"  [{etype.value}] {src_id}: {src.code_content}")

        # Dependents (outgoing edges)
        for dst_id, etype in graph.get_outgoing(node.node_id):
            dst = graph.get_node(dst_id)
            if dst:
                deps.append(f"  [{etype.value}] -> {dst_id}: {dst.code_content}")

        # Config refs
        config_refs = []
        for src_id, etype in graph.get_incoming(node.node_id):
            if etype == EdgeType.CONFIG_INFLUENCE:
                src = graph.get_node(src_id)
                if src:
                    config_refs.append(f"  {src_id}: {src.code_content}")

        return {
            "file_path": file_path,
            "line_number": line_number,
            "code_line": node.code_content,
            "surrounding_context": surrounding or "(unavailable)",
            "dependencies": "\n".join(deps[:20]) or "(none)",
            "config_refs": "\n".join(config_refs[:10]) or "(none)",
            "runtime_info": f"Node type: {node.node_type}, Label: {node.semantic_label}",
        }

    def _read_surrounding(self, file_path: str, line: int, context_lines: int = 5) -> str:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            start = max(0, line - 1 - context_lines)
            end = min(len(lines), line + context_lines)
            result = []
            for i in range(start, end):
                marker = ">>>" if i == line - 1 else "   "
                result.append(f"{marker} {i+1}: {lines[i].rstrip()}")
            return "\n".join(result)
        except Exception:
            return ""

    # ── LLM calls ────────────────────────────────────────────────────

    def _call_llm(self, prompt: str) -> str:
        """Call the configured LLM provider."""
        if self.provider == "anthropic":
            return self._call_anthropic(prompt)
        elif self.provider == "openai":
            return self._call_openai(prompt)
        else:
            return self._mock_response(prompt)

    def _call_anthropic(self, prompt: str) -> str:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except ImportError:
            return self._mock_response(prompt)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _call_openai(self, prompt: str) -> str:
        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            return response.choices[0].message.content
        except ImportError:
            return self._mock_response(prompt)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _mock_response(self, prompt: str) -> str:
        """Mock response for testing without API key."""
        if "root cause" in prompt.lower():
            return json.dumps({
                "symptom": "Error detected at the specified location",
                "direct_cause": "Code logic issue at the error line",
                "root_cause": "Requires LLM API key for full analysis",
                "confidence": 0.5,
                "related_nodes": [],
                "fix_suggestion": "Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable",
            })
        elif "why" in prompt.lower() or "exist" in prompt.lower():
            return json.dumps({
                "purpose": "Requires LLM API key for full analysis of code existence reason",
                "depends_on": [],
                "removal_consequence": "Cannot determine without LLM analysis",
                "upstream_logic": "Set API key for detailed analysis",
                "confidence": 0.5,
            })
        return json.dumps({"result": "mock", "confidence": 0.5})

    # ── JSON extraction ──────────────────────────────────────────────

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM response, handling markdown code blocks."""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from code block
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding JSON object in text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return {"raw_response": text, "confidence": 0.0}
