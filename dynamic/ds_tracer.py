"""Data Structure Tracer — captures object identity and reference relationships.

Unlike StateRecorder which records value_repr, this captures:
- Object identity (id())
- Attribute references (.next, .prev, .left, .right)
- Which objects reference which
"""

from __future__ import annotations
import sys
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


@dataclass
class ObjectSnapshot:
    """Snapshot of an object's identity and attributes at a point in time."""
    obj_id: int
    type_name: str
    val_repr: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    ref_ids: Dict[str, int] = field(default_factory=dict)  # attr_name → referenced obj_id


@dataclass
class DSStep:
    """One step in data structure evolution."""
    step_index: int
    file_path: str
    line_number: int
    code_line: str
    function_name: str
    # All tracked objects at this step
    objects: Dict[int, ObjectSnapshot] = field(default_factory=dict)
    # Variable name → object id
    var_to_obj: Dict[str, int] = field(default_factory=dict)
    # Which objects were modified this step
    changed_objects: List[int] = field(default_factory=list)
    # Which references changed this step
    changed_refs: List[Tuple[int, str, int]] = field(default_factory=list)  # (from_id, attr, to_id)


@dataclass
class DSTimeline:
    """Complete timeline of data structure evolution."""
    steps: List[DSStep]
    target_files: Set[str]


def _safe_repr(val: Any, max_len: int = 100) -> str:
    try:
        r = repr(val)
        return r[:max_len] + "..." if len(r) > max_len else r
    except Exception:
        return f"<{type(val).__name__}>"


def _get_ref_ids(obj: Any, visited: Optional[Set[int]] = None) -> Dict[str, int]:
    """Get object ids that this object references via attributes."""
    if visited is None:
        visited = set()
    if id(obj) in visited:
        return {}
    visited.add(id(obj))

    refs: Dict[str, int] = {}
    if hasattr(obj, "__dict__"):
        for attr_name, attr_val in obj.__dict__.items():
            if not attr_name.startswith("_") and not callable(attr_val):
                refs[attr_name] = id(attr_val)
    return refs


def _collect_reachable(obj: Any, seen: Optional[Set[int]] = None, depth: int = 0) -> Dict[int, Any]:
    """Collect all objects reachable from obj via attribute references."""
    if seen is None:
        seen = set()
    if depth > 20 or id(obj) in seen:
        return {}
    seen.add(id(obj))

    result: Dict[int, Any] = {id(obj): obj}

    if hasattr(obj, "__dict__"):
        for attr_name, attr_val in obj.__dict__.items():
            if not attr_name.startswith("_") and not callable(attr_val) and hasattr(attr_val, "__dict__"):
                result.update(_collect_reachable(attr_val, seen, depth + 1))

    return result


class DSTracer:
    """Tracer that captures data structure state at every line."""

    def __init__(self, target_files: Optional[Set[str]] = None):
        self.target_files = target_files
        self.steps: List[DSStep] = []
        self._step_index = 0
        self._active = False
        self._tracked_classes: Set[str] = set()

    def start(self) -> None:
        self._active = True
        self.steps = []
        self._step_index = 0
        sys.settrace(self._trace)

    def stop(self) -> None:
        self._active = False
        sys.settrace(None)

    def get_timeline(self) -> DSTimeline:
        return DSTimeline(
            steps=list(self.steps),
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

        return self._trace

    def _record_state(self, frame, file_path: str) -> None:
        line_no = frame.f_lineno
        func_name = frame.f_code.co_name

        code_line = ""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if 1 <= line_no <= len(lines):
                code_line = lines[line_no - 1].strip()
        except Exception:
            pass

        # Collect all objects reachable from local variables
        all_objects: Dict[int, Any] = {}
        var_to_obj: Dict[str, int] = {}

        for name, val in frame.f_locals.items():
            if name.startswith("_"):
                continue
            if callable(val) and not isinstance(val, type):
                continue
            if isinstance(val, type):
                continue

            # Track this variable
            var_to_obj[name] = id(val)

            # If it's a custom object, collect all reachable objects
            if hasattr(val, "__dict__") and not isinstance(val, (int, float, str, bool, list, dict, tuple, type(None))):
                reachable = _collect_reachable(val)
                all_objects.update(reachable)

        # Build snapshots
        obj_snapshots: Dict[int, ObjectSnapshot] = {}
        for obj_id, obj in all_objects.items():
            refs = _get_ref_ids(obj)
            obj_snapshots[obj_id] = ObjectSnapshot(
                obj_id=obj_id,
                type_name=type(obj).__name__,
                val_repr=_safe_repr(obj),
                attributes={k: _safe_repr(v) for k, v in (obj.__dict__.items() if hasattr(obj, "__dict__") else {})},
                ref_ids=refs,
            )

        # Detect changes from previous step
        changed_objects: List[int] = []
        changed_refs: List[Tuple[int, str, int]] = []

        if self.steps:
            prev = self.steps[-1]
            for obj_id, snap in obj_snapshots.items():
                if obj_id not in prev.objects:
                    changed_objects.append(obj_id)
                else:
                    prev_snap = prev.objects[obj_id]
                    if snap.ref_ids != prev_snap.ref_ids:
                        changed_objects.append(obj_id)
                        for attr, new_target in snap.ref_ids.items():
                            old_target = prev_snap.ref_ids.get(attr)
                            if old_target != new_target:
                                changed_refs.append((obj_id, attr, new_target))

        step = DSStep(
            step_index=self._step_index,
            file_path=file_path,
            line_number=line_no,
            code_line=code_line,
            function_name=func_name,
            objects=obj_snapshots,
            var_to_obj=var_to_obj,
            changed_objects=changed_objects,
            changed_refs=changed_refs,
        )

        self.steps.append(step)
        self._step_index += 1


def trace_ds_function(func: Callable, *args, target_files: Optional[Set[str]] = None, **kwargs):
    """Run function and capture data structure evolution."""
    tracer = DSTracer(target_files=target_files)
    tracer.start()
    result = None
    exc = None
    try:
        result = func(*args, **kwargs)
    except Exception as e:
        exc = e
    finally:
        tracer.stop()
    if exc:
        raise exc
    return result, tracer.get_timeline()
