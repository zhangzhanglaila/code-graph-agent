"""Python line-level runtime tracer using sys.settrace."""

from __future__ import annotations
import sys
import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from core.graph import CausalGraph
from core.node import CodeNode
from core.edge_types import EdgeType


@dataclass
class TraceEvent:
    """A single line-level trace event."""
    file_path: str
    line_number: int
    event_type: str        # "line", "call", "return", "exception"
    function_name: str = ""
    local_vars: Dict[str, str] = field(default_factory=dict)


class LineTracer:
    """Non-invasive line-level tracer using sys.settrace."""

    def __init__(self, target_files: Optional[Set[str]] = None):
        self.target_files = target_files  # None = trace all
        self.events: List[TraceEvent] = []
        self._prev_line: Dict[str, int] = {}  # func_key -> prev line
        self._lock = threading.Lock()
        self._active = False

    def start(self) -> None:
        self._active = True
        sys.settrace(self._trace_func)

    def stop(self) -> None:
        self._active = False
        sys.settrace(None)

    def _should_trace(self, file_path: str) -> bool:
        if self.target_files is None:
            # Default: skip stdlib and site-packages
            return not any(skip in file_path for skip in [
                "site-packages", "lib/python", "<frozen>", "__pycache__"
            ])
        return file_path in self.target_files

    def _trace_func(self, frame, event, arg):
        if not self._active:
            return None

        file_path = os.path.abspath(frame.f_code.co_filename)

        if not self._should_trace(file_path):
            return None

        func_name = frame.f_code.co_name
        func_key = f"{file_path}:{func_name}"

        if event == "call":
            with self._lock:
                self.events.append(TraceEvent(
                    file_path=file_path,
                    line_number=frame.f_lineno,
                    event_type="call",
                    function_name=func_name,
                ))
            return self._trace_func

        elif event == "line":
            line_no = frame.f_lineno
            # Capture local variables (names only, values as repr)
            local_vars = {}
            try:
                for k, v in frame.f_locals.items():
                    if not k.startswith("_"):
                        try:
                            local_vars[k] = repr(v)[:200]
                        except Exception:
                            local_vars[k] = "<unrepr>"
            except Exception:
                pass

            with self._lock:
                self.events.append(TraceEvent(
                    file_path=file_path,
                    line_number=line_no,
                    event_type="line",
                    function_name=func_name,
                    local_vars=local_vars,
                ))

            # Build RUNTIME_TRACE edge from previous line
            prev = self._prev_line.get(func_key)
            if prev is not None and prev != line_no:
                with self._lock:
                    self.events.append(TraceEvent(
                        file_path=file_path,
                        line_number=line_no,
                        event_type="trace_edge",
                        function_name=func_name,
                    ))
            self._prev_line[func_key] = line_no

        elif event == "return":
            with self._lock:
                self.events.append(TraceEvent(
                    file_path=file_path,
                    line_number=frame.f_lineno,
                    event_type="return",
                    function_name=func_name,
                ))
            self._prev_line.pop(func_key, None)

        elif event == "exception":
            with self._lock:
                self.events.append(TraceEvent(
                    file_path=file_path,
                    line_number=frame.f_lineno,
                    event_type="exception",
                    function_name=func_name,
                ))

        return self._trace_func

    def run_function(self, func: Callable, *args, **kwargs):
        """Trace execution of a single function call."""
        self.start()
        result = None
        exception = None
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            exception = e
        finally:
            self.stop()
        if exception:
            raise exception
        return result

    def to_graph(self) -> CausalGraph:
        """Convert trace events to a causal graph."""
        graph = CausalGraph()
        prev_node_id: Optional[str] = None

        for event in self.events:
            if event.event_type == "trace_edge":
                continue

            nid = CodeNode.make_id(event.file_path, event.line_number)
            if not graph.has_node(nid):
                graph.add_node(CodeNode(
                    node_id=nid,
                    file_path=event.file_path,
                    line_number=event.line_number,
                    node_type="CODE",
                    semantic_label=f"[runtime] {event.event_type} in {event.function_name}",
                ))

            # Add RUNTIME_TRACE edge from previous line
            if prev_node_id and prev_node_id != nid:
                graph.add_edge(prev_node_id, nid, EdgeType.RUNTIME_TRACE)

            prev_node_id = nid

        return graph


def trace_function(func: Callable, target_files: Optional[Set[str]] = None):
    """Convenience: trace a function and return (result, tracer)."""
    tracer = LineTracer(target_files=target_files)
    result = tracer.run_function(func)
    return result, tracer
