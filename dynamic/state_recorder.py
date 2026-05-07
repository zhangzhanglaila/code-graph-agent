"""Execution State Recorder — captures variable snapshots at each line.

Unlike tracer.py which records WHERE execution went,
this records WHAT the state looked like at each step.

Output: a timeline of (line, locals_snapshot, diff_from_previous, depth, call_id)
"""

from __future__ import annotations
import copy
import sys
import os
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


@dataclass
class VariableSnapshot:
    """Snapshot of a single variable at a point in time."""
    name: str
    value_repr: str
    value_type: str
    memory_id: int                  # id() — tracks object identity
    is_reference_to: Optional[str] = None  # if points to another tracked var
    container_keys: Optional[List] = None   # shallow keys/indexes for containers


@dataclass
class ExecutionStep:
    """One step in the execution timeline."""
    step_index: int
    file_path: str
    line_number: int
    code_line: str
    function_name: str
    variables: Dict[str, VariableSnapshot]
    changed_vars: List[str]         # which vars changed since last step
    new_vars: List[str]             # newly created vars
    removed_vars: List[str]         # vars that went out of scope
    mutated_vars: List[str] = field(default_factory=list)   # same object, value changed (e.g., lst.append)
    rebound_vars: List[str] = field(default_factory=list)   # different object assigned (e.g., x = new_val)
    alias_groups: List[List[str]] = field(default_factory=list)  # [[a, b]] means a and b alias same object
    container_deltas: List[dict] = field(default_factory=list)  # [{var, type, added, removed, updated}]
    depth: int = 0                  # call-stack depth (0 = top-level)
    call_id: int = 0                # which call frame this step belongs to
    indent: int = 0                 # indentation level (spaces)
    block_id: int = 0               # which block scope this step belongs to


@dataclass
class ExecutionTimeline:
    """Complete execution timeline with variable states."""
    steps: List[ExecutionStep]
    target_files: Set[str]
    block_meta: Dict[int, dict] = field(default_factory=dict)  # block_id → {parent, indent, condition_step}

    def get_variable_history(self, var_name: str) -> List[Tuple[int, Any]]:
        """Get the history of a variable across all steps."""
        history = []
        for step in self.steps:
            if var_name in step.variables:
                history.append((step.step_index, step.variables[var_name]))
        return history

    def get_step(self, index: int) -> Optional[ExecutionStep]:
        if 0 <= index < len(self.steps):
            return self.steps[index]
        return None

    def summary(self) -> dict:
        all_vars = set()
        for step in self.steps:
            all_vars.update(step.variables.keys())
        return {
            "total_steps": len(self.steps),
            "files_traced": list(self.target_files),
            "variables_tracked": list(all_vars),
        }

    def get_block_structure(self) -> dict:
        """Return block structure: block_id → {parent, indent, condition_step, children}."""
        blocks: dict = {}
        for step in self.steps:
            bid = step.block_id
            if bid not in blocks:
                blocks[bid] = {
                    'id': bid,
                    'indent': step.indent,
                    'steps': [],
                    'first_line': step.line_number,
                    'last_line': step.line_number,
                }
            blocks[bid]['steps'].append(step.step_index)
            blocks[bid]['last_line'] = step.line_number
        return blocks


def _safe_repr(val: Any, max_len: int = 200) -> str:
    """Safe string representation of any value."""
    try:
        r = repr(val)
        if len(r) > max_len:
            r = r[:max_len] + "..."
        return r
    except Exception:
        return f"<{type(val).__name__}>"


def _safe_type(val: Any) -> str:
    try:
        return type(val).__name__
    except Exception:
        return "unknown"


def _container_keys(val: Any) -> Optional[list]:
    """Shallow snapshot of container contents for delta tracking."""
    try:
        if isinstance(val, list):
            return list(range(len(val)))
        if isinstance(val, dict):
            return list(val.keys())
        if isinstance(val, set):
            return list(val)
    except Exception:
        pass
    return None


class StateRecorder:
    """Records variable state at every executed line.

    Usage:
        recorder = StateRecorder()
        recorder.start()
        some_function(args)
        recorder.stop()
        timeline = recorder.get_timeline()
    """

    SKIP_TYPES = (type(None), bool, int, float, str, bytes, type, type(...))

    def __init__(
        self,
        target_files: Optional[Set[str]] = None,
        track_types: Optional[Set[str]] = None,
        max_value_len: int = 200,
        skip_private: bool = True,
    ):
        self.target_files = target_files
        self.track_types = track_types  # e.g. {"list", "dict", "MyClass"}
        self.max_value_len = max_value_len
        self.skip_private = skip_private

        self._steps: List[ExecutionStep] = []
        self._prev_locals: Dict[str, VariableSnapshot] = {}
        self._step_index = 0
        self._active = False
        self._depth = 0
        self._call_counter = 0
        self._call_stack: List[int] = []  # stack of call_ids

        # Block scope tracking (indent-based)
        self._block_counter: int = 0            # unique block ID generator
        self._block_stack: List[tuple] = [(0, 0)]  # (block_id, indent) stack
        self._block_meta: Dict[int, dict] = {}  # block_id → {parent, indent, condition_step}
        self._block_conditions: Dict[int, int] = {}  # block_id → condition_step
        self._indent_first_line: Dict[int, int] = {}  # indent → first line_no at this indent
        self._indent_block_id: Dict[int, int] = {}   # indent → block_id
        self._last_loop_indent: int = -1        # indent of last for/while line
        self._pending_condition_step: int = -1  # step index of pending condition
        self._pending_condition_indent: int = -1  # indent of pending condition
        self._prev_indent: int = 0              # indent of previous step

    def start(self) -> None:
        self._active = True
        self._steps = []
        self._prev_locals = {}
        self._step_index = 0
        self._depth = 0
        self._call_counter = 0
        self._call_stack = []
        self._block_counter = 0
        self._block_stack = [(0, 0)]
        self._block_meta = {}
        self._block_conditions = {}
        self._indent_first_line = {}
        self._indent_block_id = {}
        self._last_loop_indent = -1
        self._pending_condition_step = -1
        self._pending_condition_indent = -1
        self._prev_indent = 0
        sys.settrace(self._trace)

    def stop(self) -> None:
        self._active = False
        sys.settrace(None)

    def get_timeline(self) -> ExecutionTimeline:
        return ExecutionTimeline(
            steps=list(self._steps),
            target_files=self.target_files or set(),
            block_meta=dict(self._block_meta),
        )

    def _should_trace(self, file_path: str) -> bool:
        if self.target_files is None:
            return not any(skip in file_path for skip in [
                "site-packages", "lib/python", "<frozen>", "__pycache__"
            ])
        return file_path in self.target_files

    def _trace(self, frame, event, arg):
        if not self._active:
            return None

        file_path = os.path.abspath(frame.f_code.co_filename)
        if not self._should_trace(file_path):
            return None

        if event == "call":
            self._depth += 1
            self._call_counter += 1
            self._call_stack.append(self._call_counter)
            self._record_state(frame, file_path)
            return self._trace
        elif event == "return":
            self._record_state(frame, file_path)
            self._depth = max(0, self._depth - 1)
            if self._call_stack:
                self._call_stack.pop()
        elif event == "line":
            self._record_state(frame, file_path)
        elif event == "exception":
            self._record_state(frame, file_path)

        return self._trace

    def _record_state(self, frame, file_path: str) -> None:
        line_no = frame.f_lineno
        func_name = frame.f_code.co_name

        # Read code line (raw for indent, stripped for display)
        code_line = ""
        indent = 0
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if 1 <= line_no <= len(lines):
                raw_line = lines[line_no - 1]
                code_line = raw_line.strip()
                indent = len(raw_line) - len(raw_line.lstrip())
        except Exception:
            pass

        # Skip function/method definition lines — they are not execution steps
        if code_line.startswith("def ") or code_line.startswith("async def "):
            return

        # Skip duplicate consecutive steps (same line + same depth — return double-fire)
        if self._steps:
            prev = self._steps[-1]
            if prev.line_number == line_no and prev.depth == self._depth and prev.function_name == func_name:
                return

        # ── Block scope tracking via indent ──
        is_condition = code_line.startswith(('if ', 'elif ', 'while ', 'for '))
        prev_indent = self._prev_indent

        # Is this a loop back-edge? (for/while line at shallower indent about to re-enter body)
        is_loop_header = is_condition and code_line.startswith(('for ', 'while '))
        is_loop_reentry = is_loop_header and indent < prev_indent

        if indent > prev_indent:
            # Entering a deeper indent
            is_loop_body = prev_indent == self._last_loop_indent
            first_line = self._indent_first_line.get(indent)

            if is_loop_body and first_line is not None and line_no >= first_line:
                # Re-entering loop body
                current_block_id = self._indent_block_id[indent]
                self._block_stack.append((current_block_id, indent))
            else:
                # Genuinely new block
                self._block_counter += 1
                current_block_id = self._block_counter
                parent_id = self._block_stack[-1][0]
                # Use pending condition if it controls this indent level
                cond_step = -1
                if hasattr(self, '_pending_condition_step') and indent > self._pending_condition_indent:
                    cond_step = self._pending_condition_step
                self._block_meta[current_block_id] = {
                    'parent': parent_id,
                    'indent': indent,
                    'condition_step': cond_step,
                }
                self._indent_first_line[indent] = line_no
                self._indent_block_id[indent] = current_block_id
                self._block_stack.append((current_block_id, indent))
        elif indent < prev_indent:
            # Leaving block(s) — pop stack, clear deeper indent tracking
            while len(self._block_stack) > 1 and self._block_stack[-1][1] > indent:
                popped_indent = self._block_stack[-1][1]
                self._block_stack.pop()
                # Clear tracking unless this is a loop back-edge
                if not is_loop_reentry:
                    self._indent_first_line.pop(popped_indent, None)
                    self._indent_block_id.pop(popped_indent, None)
            current_block_id = self._indent_block_id.get(indent, 0)
        else:
            # Same indent — stay in current block
            current_block_id = self._indent_block_id.get(indent, 0)

        # Track loop headers
        if is_loop_header:
            self._last_loop_indent = indent
        elif is_condition:
            # Non-loop condition (if/elif) — reset loop tracking
            self._last_loop_indent = -1

        # Track condition lines — the condition controls the NEXT deeper block
        # Store condition_step keyed by the indent it controls (indent + 1 level)
        if is_condition:
            # This condition will control blocks at deeper indents
            # Store as pending condition for the next indent level
            self._pending_condition_step = self._step_index
            self._pending_condition_indent = indent

        self._prev_indent = indent

        # Capture locals
        current_snapshots: Dict[str, VariableSnapshot] = {}
        try:
            for name, val in frame.f_locals.items():
                if self.skip_private and name.startswith("_"):
                    continue
                if callable(val) and not isinstance(val, type):
                    continue
                if isinstance(val, type):
                    continue

                current_snapshots[name] = VariableSnapshot(
                    name=name,
                    value_repr=_safe_repr(val, self.max_value_len),
                    value_type=_safe_type(val),
                    memory_id=id(val),
                    container_keys=_container_keys(val),
                )
        except Exception:
            pass

        # Compute diffs — distinguish mutation from rebind
        prev_names = set(self._prev_locals.keys())
        curr_names = set(current_snapshots.keys())

        changed = []
        mutated = []
        rebound = []
        for name in prev_names & curr_names:
            old = self._prev_locals[name]
            new = current_snapshots[name]
            if old.value_repr != new.value_repr or old.memory_id != new.memory_id:
                changed.append(name)
                if old.memory_id == new.memory_id:
                    # Same object, value changed → mutation (e.g., lst.append, dict[key] = val)
                    mutated.append(name)
                else:
                    # Different object → rebind (e.g., x = new_value)
                    rebound.append(name)

        new_vars = list(curr_names - prev_names)
        removed_vars = list(prev_names - curr_names)

        # Compute container deltas for mutated vars
        container_deltas = []
        for name in mutated:
            old = self._prev_locals.get(name)
            new = current_snapshots.get(name)
            if not old or not new or not old.container_keys or not new.container_keys:
                continue
            old_keys = set(old.container_keys)
            new_keys = set(new.container_keys)
            delta: dict = {'var': name, 'type': new.value_type}
            if new.value_type == 'list':
                added = [k for k in new.container_keys if k not in old_keys]
                removed = [k for k in old.container_keys if k not in new_keys]
                if added: delta['added_indices'] = added
                if removed: delta['removed_indices'] = removed
                # Check for value updates at shared indices
                shared = old_keys & new_keys
                # We don't store values per-key, so we can only detect structural changes
            elif new.value_type == 'dict':
                added = [k for k in new.container_keys if k not in old_keys]
                removed = [k for k in old.container_keys if k not in new_keys]
                if added: delta['added_keys'] = added
                if removed: delta['removed_keys'] = removed
            elif new.value_type == 'set':
                added = [k for k in new.container_keys if k not in old_keys]
                removed = [k for k in old.container_keys if k not in new_keys]
                if added: delta['added_values'] = added
                if removed: delta['removed_values'] = removed
            if len(delta) > 2:  # more than just var + type
                container_deltas.append(delta)

        # Detect references between tracked vars
        alias_groups = self._detect_references(current_snapshots, frame)

        current_call_id = self._call_stack[-1] if self._call_stack else 0

        step = ExecutionStep(
            step_index=self._step_index,
            file_path=file_path,
            line_number=line_no,
            code_line=code_line,
            function_name=func_name,
            variables=current_snapshots,
            changed_vars=changed,
            new_vars=new_vars,
            removed_vars=removed_vars,
            mutated_vars=mutated,
            rebound_vars=rebound,
            alias_groups=alias_groups,
            container_deltas=container_deltas,
            depth=self._depth,
            call_id=current_call_id,
            indent=indent,
            block_id=current_block_id,
        )

        self._steps.append(step)
        self._prev_locals = current_snapshots
        self._step_index += 1

    def _detect_references(
        self, snapshots: Dict[str, VariableSnapshot], frame
    ) -> List[List[str]]:
        """Detect which variables reference the same object. Returns alias groups."""
        id_to_names: Dict[int, List[str]] = {}
        for name, snap in snapshots.items():
            id_to_names.setdefault(snap.memory_id, []).append(name)

        alias_groups = []
        for mem_id, names in id_to_names.items():
            if len(names) > 1:
                alias_groups.append(sorted(names))
                for name in names:
                    others = [n for n in names if n != name]
                    if others:
                        snapshots[name].is_reference_to = others[0]
        return alias_groups


def record_function(
    func: Callable,
    *args,
    target_files: Optional[Set[str]] = None,
    **kwargs,
) -> Tuple[Any, ExecutionTimeline]:
    """Run function, return (result, timeline)."""
    recorder = StateRecorder(target_files=target_files)
    recorder.start()
    result = None
    exc = None
    try:
        result = func(*args, **kwargs)
    except Exception as e:
        exc = e
    finally:
        recorder.stop()
    if exc:
        raise exc
    return result, recorder.get_timeline()
