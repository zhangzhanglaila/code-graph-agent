"""Execution State Recorder — captures variable snapshots at each line.

Unlike tracer.py which records WHERE execution went,
this records WHAT the state looked like at each step.

Output: a timeline of (line, locals_snapshot, diff_from_previous, depth, call_id)
"""

from __future__ import annotations
import ast
import copy
import inspect
import linecache
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
    ast_reads: List[str] = field(default_factory=list)   # variables read (AST Load context)
    ast_writes: List[str] = field(default_factory=list)  # variables written (AST Store context)
    ssa_versions: Dict[str, int] = field(default_factory=dict)  # var → SSA version at this step


@dataclass
class ExecutionTimeline:
    """Complete execution timeline with variable states."""
    steps: List[ExecutionStep]
    target_files: Set[str]
    block_meta: Dict[int, dict] = field(default_factory=dict)  # block_id → {parent, indent, condition_step}
    call_events: List[CallEvent] = field(default_factory=list)
    parameter_bindings: List[ParameterBinding] = field(default_factory=list)
    return_bindings: List[ReturnBinding] = field(default_factory=list)
    frame_contexts: Dict[int, FrameContext] = field(default_factory=dict)  # call_id → FrameContext
    data_dependencies: List[DataDependency] = field(default_factory=list)  # RAW edges

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

    def backward_slice(self, target_step: int, target_var: str = '') -> dict:
        """Dynamic backward slicing: trace from a target step back to root causes.

        Follows:
          1. Data dependencies (RAW edges) — variable-level
          2. Control dependencies (block_meta condition_step) — block-level
          3. Cross-function: parameter bindings and return bindings

        Returns: {slice_steps, slice_edges, root_causes, depth_map}
        """
        # Build lookup structures
        # data_dep_lookup[(target_step, var)] = [DataDependency, ...]
        data_dep_lookup: Dict[Tuple[int, str], list] = {}
        for dd in self.data_dependencies:
            key = (dd.target_step, dd.variable)
            data_dep_lookup.setdefault(key, []).append(dd)

        # control_lookup[block_id] = condition_step
        control_lookup: Dict[int, int] = {}
        for bid, meta in self.block_meta.items():
            cond = meta.get('condition_step', -1)
            if cond >= 0:
                control_lookup[bid] = cond

        # step_index → block_id
        step_to_block: Dict[int, int] = {}
        for step in self.steps:
            step_to_block[step.step_index] = step.block_id

        # parameter_bindings: callee_param → (caller_var, caller_step, call_id)
        param_lookup: Dict[str, list] = {}
        for pb in self.parameter_bindings:
            param_lookup.setdefault(pb.callee_param, []).append(pb)

        # return_bindings: call_id → (caller_step, assigned_to)
        return_lookup: Dict[int, list] = {}
        for rb in self.return_bindings:
            return_lookup.setdefault(rb.call_id, []).append(rb)

        # BFS/DFS backward through the dependency graph
        visited_steps: Set[int] = set()
        visited_edges: List[dict] = []
        root_causes: List[int] = []
        depth_map: Dict[int, int] = {}  # step → distance from target

        # Queue: (step_index, variable, depth)
        queue = [(target_step, target_var, 0)]

        while queue:
            step_idx, var, depth = queue.pop(0)  # BFS
            if step_idx in visited_steps:
                continue
            visited_steps.add(step_idx)
            depth_map[step_idx] = depth

            step = self.steps[step_idx] if 0 <= step_idx < len(self.steps) else None
            if not step:
                continue

            # 1. Data dependencies: follow RAW edges backward
            if var:
                key = (step_idx, var)
                deps = data_dep_lookup.get(key, [])
                for dd in deps:
                    visited_edges.append({
                        'from': dd.source_step,
                        'to': dd.target_step,
                        'var': dd.variable,
                        'type': 'data',
                        'source_version': dd.source_version,
                        'target_version': dd.target_version,
                    })
                    if dd.source_step not in visited_steps:
                        queue.append((dd.source_step, dd.variable, depth + 1))

                # Also check all vars read at this step
                for read_var in step.ast_reads:
                    if read_var == var:
                        continue
                    read_key = (step_idx, read_var)
                    for dd in data_dep_lookup.get(read_key, []):
                        visited_edges.append({
                            'from': dd.source_step,
                            'to': dd.target_step,
                            'var': dd.variable,
                            'type': 'data',
                            'source_version': dd.source_version,
                            'target_version': dd.target_version,
                        })
                        if dd.source_step not in visited_steps:
                            queue.append((dd.source_step, dd.variable, depth + 1))

            # 2. Control dependencies: follow block condition backward
            block_id = step_to_block.get(step_idx, 0)
            if block_id in control_lookup:
                cond_step = control_lookup[block_id]
                if cond_step not in visited_steps:
                    visited_edges.append({
                        'from': cond_step,
                        'to': step_idx,
                        'var': '',
                        'type': 'control',
                    })
                    queue.append((cond_step, '', depth + 1))

            # 3. Cross-function: if this step reads a parameter, follow to caller
            for read_var in step.ast_reads:
                bindings = param_lookup.get(read_var, [])
                for pb in bindings:
                    if pb.caller_step not in visited_steps:
                        visited_edges.append({
                            'from': pb.caller_step,
                            'to': step_idx,
                            'var': pb.caller_var,
                            'type': 'parameter',
                        })
                        queue.append((pb.caller_step, pb.caller_var, depth + 1))

            # 4. If this step has no incoming data deps and no control dep, it's a root cause
            has_incoming = False
            for dd in self.data_dependencies:
                if dd.target_step == step_idx:
                    has_incoming = True
                    break
            if not has_incoming and block_id not in control_lookup:
                root_causes.append(step_idx)

        return {
            'slice_steps': sorted(visited_steps),
            'slice_edges': visited_edges,
            'root_causes': root_causes,
            'depth_map': depth_map,
        }


@dataclass
class CallEvent:
    """A function call or return event."""
    call_id: int
    parent_call_id: Optional[int]       # call_id of the caller frame
    function_name: str
    caller_step: int                    # step index of the call site
    callee_first_step: Optional[int]    # first step inside callee
    args: Dict[str, dict]               # {param_name: {value, type, memory_id}}
    start_line: int
    end_line: Optional[int] = None
    depth: int = 0
    return_value: Optional[dict] = None  # {value, type, memory_id}
    return_step: Optional[int] = None


@dataclass
class FrameContext:
    """Semantic stack frame — tracks per-call variable versions."""
    call_id: int
    function_name: str
    file_path: str
    local_versions: Dict[str, int] = field(default_factory=dict)  # var → version count
    entry_step: int = 0
    exit_step: Optional[int] = None
    parent_call_id: Optional[int] = None


@dataclass
class ParameterBinding:
    """Links a caller argument to a callee parameter."""
    call_id: int
    caller_var: str
    callee_param: str
    caller_memory_id: int
    callee_memory_id: int
    is_alias: bool              # True if same object (shared mutation risk)
    caller_step: int


@dataclass
class ReturnBinding:
    """Links a callee return value to a caller variable."""
    call_id: int
    return_step: int
    caller_step: int            # step where caller captures return
    return_memory_id: int
    assigned_to: Optional[str]  # caller variable name


@dataclass
class DataDependency:
    """A read-after-write (RAW) data dependency edge."""
    source_step: int        # step that wrote the value
    target_step: int        # step that read the value
    variable: str           # variable name
    source_version: int     # SSA version at write
    target_version: int     # SSA version at read (same or next)
    dependency_type: str = "read-after-write"


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


# Python builtins that should not be treated as variable reads
_BUILTIN_NAMES = frozenset({
    'range', 'len', 'int', 'str', 'float', 'list', 'dict', 'set',
    'tuple', 'bool', 'type', 'isinstance', 'enumerate', 'zip', 'map',
    'filter', 'sorted', 'sum', 'min', 'max', 'abs', 'print', 'repr',
    'round', 'any', 'all', 'next', 'iter', 'open', 'input', 'super',
    'True', 'False', 'None', 'self', 'cls',
})


def _extract_reads_writes(code_line: str) -> Dict[str, List[str]]:
    """Parse a single code line with AST to extract variable reads and writes.

    Returns {"reads": [...], "writes": [...]}.
    Reads are variables in Load context; writes are variables in Store context.
    Handles: assignment, augmented assignment, for-loop target, with-as, etc.
    """
    import re
    reads: List[str] = []
    writes: List[str] = []
    stripped = code_line.strip()

    # For/while/with headers can't be parsed alone (need body) — use regex fallback
    for_match = re.match(r'for\s+(\w+)\s+in\s+(.+):', stripped)
    if for_match:
        target = for_match.group(1)
        iterable = for_match.group(2)
        if target not in _BUILTIN_NAMES:
            writes.append(target)
        # Extract variable names from iterable expression
        for token in re.findall(r'\b([a-zA-Z_]\w*)\b', iterable):
            if token not in _BUILTIN_NAMES and token != target:
                reads.append(token)
        return {"reads": reads, "writes": writes}

    with_match = re.match(r'with\s+.+\s+as\s+(\w+):', stripped)
    if with_match:
        target = with_match.group(1)
        if target not in _BUILTIN_NAMES:
            writes.append(target)
        return {"reads": reads, "writes": writes}

    try:
        tree = ast.parse(stripped)
    except SyntaxError:
        return {"reads": reads, "writes": writes}

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                if node.id not in _BUILTIN_NAMES:
                    reads.append(node.id)
            elif isinstance(node.ctx, ast.Store):
                if node.id not in _BUILTIN_NAMES:
                    writes.append(node.id)
        # Handle augmented assignment: x += 1 → x is both read and written
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name):
                name = node.target.id
                if name not in _BUILTIN_NAMES:
                    writes.append(name)
                    reads.append(name)  # augmented reads before writing

    # Deduplicate while preserving order
    seen_r: set = set()
    unique_reads = []
    for r in reads:
        if r not in seen_r:
            seen_r.add(r)
            unique_reads.append(r)
    seen_w: set = set()
    unique_writes = []
    for w in writes:
        if w not in seen_w:
            seen_w.add(w)
            unique_writes.append(w)

    return {"reads": unique_reads, "writes": unique_writes}


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

        # Interprocedural tracking
        self._call_events: List[CallEvent] = []
        self._frame_contexts: Dict[int, FrameContext] = {}
        self._parameter_bindings: List[ParameterBinding] = []
        self._return_bindings: List[ReturnBinding] = []
        self._frame_to_call_id: Dict[int, int] = {}  # id(frame) → call_id
        self._pending_return: Dict[int, dict] = {}    # call_id → return value info
        self._caller_snapshots: Dict[int, Dict[str, VariableSnapshot]] = {}  # call_id → caller locals at call site

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

        # Data dependency tracking (SSA versioning + RAW edges)
        self._data_dependencies: List[DataDependency] = []
        self._last_write_by_var: Dict[Tuple[int, str], dict] = {}  # (call_id, var) → {step, version}

    def start(self) -> None:
        self._active = True
        self._steps = []
        self._prev_locals = {}
        self._step_index = 0
        self._depth = 0
        self._call_counter = 0
        self._call_stack = []
        self._call_events = []
        self._frame_contexts = {}
        self._parameter_bindings = []
        self._return_bindings = []
        self._frame_to_call_id = {}
        self._pending_return = {}
        self._caller_snapshots = {}
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
        self._data_dependencies = []
        self._last_write_by_var = {}
        sys.settrace(self._trace)

    def stop(self) -> None:
        self._active = False
        sys.settrace(None)

    def get_timeline(self) -> ExecutionTimeline:
        return ExecutionTimeline(
            steps=list(self._steps),
            target_files=self.target_files or set(),
            block_meta=dict(self._block_meta),
            call_events=list(self._call_events),
            parameter_bindings=list(self._parameter_bindings),
            return_bindings=list(self._return_bindings),
            frame_contexts=dict(self._frame_contexts),
            data_dependencies=list(self._data_dependencies),
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
            self._handle_call(frame, file_path)
            return self._trace
        elif event == "return":
            self._handle_return(frame, file_path, arg)
        elif event == "line":
            self._record_state(frame, file_path)
        elif event == "exception":
            self._record_state(frame, file_path)

        return self._trace

    def _handle_call(self, frame, file_path: str) -> None:
        """Process a function call event — capture args, create frame context."""
        self._depth += 1
        self._call_counter += 1
        call_id = self._call_counter
        parent_call_id = self._call_stack[-1] if self._call_stack else None
        self._call_stack.append(call_id)
        self._frame_to_call_id[id(frame)] = call_id

        func_name = frame.f_code.co_name
        line_no = frame.f_lineno

        # Capture callee parameters from frame.f_locals
        callee_args: Dict[str, dict] = {}
        for name, val in frame.f_locals.items():
            if name.startswith('_'):
                continue
            callee_args[name] = {
                'value': _safe_repr(val, self.max_value_len),
                'type': _safe_type(val),
                'memory_id': id(val),
            }

        # Build parameter bindings by matching with caller's locals
        # Read caller's frame from f_back (the frame that called us)
        caller_frame = frame.f_back
        caller_locals_snapshot: Dict[str, VariableSnapshot] = {}
        if caller_frame:
            for name, val in caller_frame.f_locals.items():
                if name.startswith('_') or callable(val) and not isinstance(val, type):
                    continue
                if isinstance(val, type):
                    continue
                caller_locals_snapshot[name] = VariableSnapshot(
                    name=name,
                    value_repr=_safe_repr(val, self.max_value_len),
                    value_type=_safe_type(val),
                    memory_id=id(val),
                )

        for param_name, param_info in callee_args.items():
            param_mem_id = param_info['memory_id']
            for caller_var, caller_snap in caller_locals_snapshot.items():
                if caller_snap.memory_id == param_mem_id:
                    self._parameter_bindings.append(ParameterBinding(
                        call_id=call_id,
                        caller_var=caller_var,
                        callee_param=param_name,
                        caller_memory_id=caller_snap.memory_id,
                        callee_memory_id=param_mem_id,
                        is_alias=True,
                        caller_step=self._step_index - 1,
                    ))
                    break

        # Create call event
        call_event = CallEvent(
            call_id=call_id,
            parent_call_id=parent_call_id,
            function_name=func_name,
            caller_step=self._step_index - 1,
            callee_first_step=self._step_index,
            args=callee_args,
            start_line=line_no,
            depth=self._depth,
        )
        self._call_events.append(call_event)

        # Create frame context
        self._frame_contexts[call_id] = FrameContext(
            call_id=call_id,
            function_name=func_name,
            file_path=file_path,
            entry_step=self._step_index,
            parent_call_id=parent_call_id,
        )

        # Store caller snapshot for return binding
        self._caller_snapshots[call_id] = dict(caller_locals_snapshot)

        # Record the first state inside the callee
        self._record_state(frame, file_path)

    def _handle_return(self, frame, file_path: str, return_val) -> None:
        """Process a return event — capture return value, build return binding."""
        self._record_state(frame, file_path)

        call_id = self._call_stack[-1] if self._call_stack else 0

        # Capture return value
        ret_info = {
            'value': _safe_repr(return_val, self.max_value_len),
            'type': _safe_type(return_val),
            'memory_id': id(return_val),
        }

        # Store pending return — will be matched when caller resumes
        self._pending_return[call_id] = {
            'return_step': self._step_index,
            'memory_id': id(return_val),
        }

        # Create return binding (assigned_to filled in later by _match_pending_returns)
        self._return_bindings.append(ReturnBinding(
            call_id=call_id,
            return_step=self._step_index,
            caller_step=self._step_index,
            return_memory_id=id(return_val),
            assigned_to=None,
        ))

        # Update call event with return info
        for evt in reversed(self._call_events):
            if evt.call_id == call_id:
                evt.return_value = ret_info
                evt.return_step = self._step_index
                evt.end_line = frame.f_lineno
                break

        # Close frame context
        if call_id in self._frame_contexts:
            self._frame_contexts[call_id].exit_step = self._step_index

        # Cleanup
        self._caller_snapshots.pop(call_id, None)
        self._depth = max(0, self._depth - 1)
        if self._call_stack:
            self._call_stack.pop()

    def _record_state(self, frame, file_path: str) -> None:
        line_no = frame.f_lineno
        func_name = frame.f_code.co_name

        # Read code line (raw for indent, stripped for display)
        # Use linecache as primary source — works for <string>, deleted files, and normal files
        code_line = ""
        indent = 0
        raw_line = linecache.getline(file_path, line_no)
        if raw_line:
            code_line = raw_line.strip()
            indent = len(raw_line) - len(raw_line.lstrip())
        else:
            # Fallback: direct file read
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

        # Match pending return values with caller's new variables
        if self._pending_return and new_vars:
            matched_call_ids = []
            for pending_call_id, pending_info in self._pending_return.items():
                ret_mem_id = pending_info['memory_id']
                for var_name in new_vars:
                    var_snap = current_snapshots.get(var_name)
                    if var_snap and var_snap.memory_id == ret_mem_id:
                        # Found the assignment — update the return binding
                        for rb in self._return_bindings:
                            if rb.call_id == pending_call_id and rb.assigned_to is None:
                                rb.assigned_to = var_name
                                rb.caller_step = self._step_index
                                break
                        matched_call_ids.append(pending_call_id)
                        break
            for cid in matched_call_ids:
                self._pending_return.pop(cid, None)

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

        # Use frame-based call_id if available, fall back to call stack
        current_call_id = self._frame_to_call_id.get(id(frame), self._call_stack[-1] if self._call_stack else 0)

        # ── AST read/write extraction + SSA versioning + RAW edges ──
        ast_rw = _extract_reads_writes(code_line)
        ast_reads = ast_rw["reads"]
        ast_writes_raw = ast_rw["writes"]

        # For SSA versioning, use AST writes as the primary signal.
        # The `changed` list from sys.settrace has a one-step delay and is unreliable.
        # Trust AST Store context completely — it knows which vars are being assigned,
        # even if sys.settrace hasn't seen them in locals yet (fires BEFORE execution).
        actual_writes = list(ast_writes_raw)  # AST writes are authoritative
        for v in mutated:
            if v not in actual_writes and v in current_snapshots:
                actual_writes.append(v)

        # IMPORTANT: Build RAW edges BEFORE bumping write versions.
        # For `a, b = b, a + b`, both `a` and `b` are reads AND writes.
        # The read uses the PREVIOUS version; the write creates the NEW version.
        # We must look up the previous write for reads before overwriting it.
        step_ssa: Dict[str, int] = {}

        # 1. Build RAW edges for reads (using previous write versions)
        for v in ast_reads:
            if v not in current_snapshots:
                continue
            key = (current_call_id, v)
            last = self._last_write_by_var.get(key)
            if last and last["step"] < self._step_index:
                read_ver = last["version"]
                self._data_dependencies.append(DataDependency(
                    source_step=last["step"],
                    target_step=self._step_index,
                    variable=v,
                    source_version=read_ver,
                    target_version=read_ver,  # read uses the version that was written
                    dependency_type="read-after-write",
                ))

        # 2. Bump SSA version for each write (per-variable versioning)
        for v in actual_writes:
            key = (current_call_id, v)
            prev_ver = self._last_write_by_var.get(key, {}).get("version", 0)
            new_ver = prev_ver + 1
            self._last_write_by_var[key] = {"step": self._step_index, "version": new_ver}
            step_ssa[v] = new_ver

        # 3. Carry forward versions for vars that exist but weren't written
        for name in current_snapshots:
            if name not in step_ssa:
                key = (current_call_id, name)
                step_ssa[name] = self._last_write_by_var.get(key, {}).get("version", 0)

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
            ast_reads=ast_reads,
            ast_writes=actual_writes,
            ssa_versions=step_ssa,
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
