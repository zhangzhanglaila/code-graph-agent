"""Parse exception tracebacks and build THROWS causal edges."""

from __future__ import annotations
import os
import traceback
import sys
from dataclasses import dataclass
from typing import List, Optional

from core.graph import CausalGraph
from core.node import CodeNode
from core.edge_types import EdgeType


@dataclass
class ExceptionFrame:
    """A single frame in an exception traceback."""
    file_path: str
    line_number: int
    function_name: str
    code_line: str


@dataclass
class ParsedException:
    """Structured exception information."""
    exception_type: str
    message: str
    frames: List[ExceptionFrame]
    error_frame: Optional[ExceptionFrame] = None

    @property
    def error_file(self) -> Optional[str]:
        return self.error_frame.file_path if self.error_frame else None

    @property
    def error_line(self) -> Optional[int]:
        return self.error_frame.line_number if self.error_frame else None


class ExceptionParser:
    """Parse exceptions and build causal graph edges."""

    def parse_current_exception(self) -> Optional[ParsedException]:
        """Parse the current exception from sys.exc_info()."""
        exc_type, exc_value, exc_tb = sys.exc_info()
        if exc_type is None:
            return None
        return self._parse(exc_type, exc_value, exc_tb)

    def parse_traceback_string(self, tb_string: str) -> Optional[ParsedException]:
        """Parse a traceback string (e.g., from log files)."""
        lines = tb_string.strip().splitlines()
        if not lines:
            return None

        exc_type = "UnknownError"
        message = ""
        frames: List[ExceptionFrame] = []

        for line in lines:
            line = line.strip()
            if line.startswith('File "'):
                # Parse: File "path", line N, in func
                try:
                    parts = line.split('", line ')
                    fpath = parts[0].replace('File "', '')
                    rest = parts[1].split(", in ")
                    line_no = int(rest[0].strip())
                    func_name = rest[1].strip() if len(rest) > 1 else "<module>"
                    frames.append(ExceptionFrame(
                        file_path=os.path.abspath(fpath),
                        line_number=line_no,
                        function_name=func_name,
                        code_line="",
                    ))
                except (IndexError, ValueError):
                    pass
            elif frames and not line.startswith("Traceback") and ":" in line:
                # This might be the code line
                frames[-1].code_line = line
            elif ":" in line and not line.startswith("Traceback"):
                # Exception type and message
                parts = line.split(":", 1)
                exc_type = parts[0].strip()
                message = parts[1].strip() if len(parts) > 1 else ""

        error_frame = frames[-1] if frames else None
        return ParsedException(
            exception_type=exc_type,
            message=message,
            frames=frames,
            error_frame=error_frame,
        )

    def _parse(self, exc_type, exc_value, exc_tb) -> ParsedException:
        """Parse from exception objects."""
        frames: List[ExceptionFrame] = []
        tb = exc_tb
        while tb is not None:
            frame = tb.tb_frame
            fpath = os.path.abspath(frame.f_code.co_filename)
            frames.append(ExceptionFrame(
                file_path=fpath,
                line_number=tb.tb_lineno,
                function_name=frame.f_code.co_name,
                code_line="",
            ))
            tb = tb.tb_next

        error_frame = frames[-1] if frames else None
        return ParsedException(
            exception_type=exc_type.__name__,
            message=str(exc_value),
            frames=frames,
            error_frame=error_frame,
        )

    def build_graph(self, parsed: ParsedException) -> CausalGraph:
        """Build THROWS causal edges from parsed exception."""
        graph = CausalGraph()

        if not parsed.frames:
            return graph

        # Add error node
        err = parsed.error_frame
        if err:
            err_nid = CodeNode.make_id(err.file_path, err.line_number)
            graph.add_node(CodeNode(
                node_id=err_nid,
                file_path=err.file_path,
                line_number=err.line_number,
                node_type="ERROR",
                semantic_label=f"{parsed.exception_type}: {parsed.message}",
            ))

        # Add call chain nodes and THROWS edges
        for i, frame in enumerate(parsed.frames):
            nid = CodeNode.make_id(frame.file_path, frame.line_number)
            if not graph.has_node(nid):
                graph.add_node(CodeNode(
                    node_id=nid,
                    file_path=frame.file_path,
                    line_number=frame.line_number,
                    node_type="CODE",
                    semantic_label=f"in {frame.function_name}",
                ))

        # Connect frames: each upstream frame THROWS to the next
        for i in range(len(parsed.frames) - 1):
            src = parsed.frames[i]
            dst = parsed.frames[i + 1]
            src_id = CodeNode.make_id(src.file_path, src.line_number)
            dst_id = CodeNode.make_id(dst.file_path, dst.line_number)
            graph.add_edge(src_id, dst_id, EdgeType.THROWS)

        return graph


def catch_and_parse(func, *args, **kwargs):
    """Run func, catch any exception, return (result, parsed_exception)."""
    parser = ExceptionParser()
    try:
        result = func(*args, **kwargs)
        return result, None
    except Exception:
        parsed = parser.parse_current_exception()
        return None, parsed
