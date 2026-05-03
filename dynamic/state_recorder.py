"""Execution State Recorder — captures variable snapshots at each line.

Unlike tracer.py which records WHERE execution went,
this records WHAT the state looked like at each step.

Output: a timeline of (line, locals_snapshot, diff_from_previous)
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


@dataclass
class ExecutionTimeline:
    """Complete execution timeline with variable states."""
    steps: List[ExecutionStep]
    target_files: Set[str]

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

    def start(self) -> None:
        self._active = True
        self._steps = []
        self._prev_locals = {}
        self._step_index = 0
        sys.settrace(self._trace)

    def stop(self) -> None:
        self._active = False
        sys.settrace(None)

    def get_timeline(self) -> ExecutionTimeline:
        return ExecutionTimeline(
            steps=list(self._steps),
            target_files=self.target_files or set(),
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

        if event == "line":
            self._record_state(frame, file_path)
        elif event == "call":
            self._record_state(frame, file_path)
            return self._trace
        elif event == "return":
            self._record_state(frame, file_path)
        elif event == "exception":
            self._record_state(frame, file_path)

        return self._trace

    def _record_state(self, frame, file_path: str) -> None:
        line_no = frame.f_lineno
        func_name = frame.f_code.co_name

        # Read code line
        code_line = ""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if 1 <= line_no <= len(lines):
                code_line = lines[line_no - 1].strip()
        except Exception:
            pass

        # Capture locals
        current_snapshots: Dict[str, VariableSnapshot] = {}
        try:
            for name, val in frame.f_locals.items():
                if self.skip_private and name.startswith("_"):
                    continue
                # Skip module/function/class objects (not interesting for state)
                if callable(val) and not isinstance(val, type):
                    continue
                if isinstance(val, type):
                    continue

                current_snapshots[name] = VariableSnapshot(
                    name=name,
                    value_repr=_safe_repr(val, self.max_value_len),
                    value_type=_safe_type(val),
                    memory_id=id(val),
                )
        except Exception:
            pass

        # Compute diffs
        prev_names = set(self._prev_locals.keys())
        curr_names = set(current_snapshots.keys())

        changed = []
        for name in prev_names & curr_names:
            old = self._prev_locals[name]
            new = current_snapshots[name]
            if old.value_repr != new.value_repr or old.memory_id != new.memory_id:
                changed.append(name)

        new_vars = list(curr_names - prev_names)
        removed_vars = list(prev_names - curr_names)

        # Detect references between tracked vars
        self._detect_references(current_snapshots, frame)

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
        )

        self._steps.append(step)
        self._prev_locals = current_snapshots
        self._step_index += 1

    def _detect_references(
        self, snapshots: Dict[str, VariableSnapshot], frame
    ) -> None:
        """Detect which variables reference the same object."""
        id_to_names: Dict[int, List[str]] = {}
        for name, snap in snapshots.items():
            id_to_names.setdefault(snap.memory_id, []).append(name)

        for mem_id, names in id_to_names.items():
            if len(names) > 1:
                for name in names:
                    others = [n for n in names if n != name]
                    if others:
                        snapshots[name].is_reference_to = others[0]


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
