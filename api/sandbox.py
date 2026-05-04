"""Sandboxed code execution — subprocess isolation with timeout and restricted builtins."""

from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from typing import Any, Optional


# Forbidden modules
BLOCKED_MODULES = {
    "os", "sys", "subprocess", "shutil", "pathlib",
    "socket", "http", "urllib", "requests",
    "ctypes", "signal", "multiprocessing", "threading",
    "importlib", "code", "codeop", "compileall",
    "pickle", "shelve", "dbm", "sqlite3",
    "webbrowser", "cgi", "cgitb",
}

# Timeout in seconds
DEFAULT_TIMEOUT = 10
MAX_TIMEOUT = 30


def run_sandboxed(
    code: str,
    func_name: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    capture_state: bool = True,
) -> dict:
    """Run user code in an isolated subprocess with timeout.

    Returns:
        {
            "success": bool,
            "result": any,
            "error": str | None,
            "timed_out": bool,
            "stdout": str,
            "stderr": str,
        }
    """
    timeout = min(timeout, MAX_TIMEOUT)

    # Build wrapper script that captures result and state
    wrapper = _build_wrapper(code, func_name, capture_state)

    # Write to temp file
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    )
    tmp.write(wrapper)
    tmp.close()

    try:
        proc = subprocess.run(
            [sys.executable, tmp.path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env=_restricted_env(),
        )

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        # Parse result from stdout (JSON on last line)
        result = None
        error = None
        timed_out = False

        if proc.returncode == 0:
            try:
                # Last line is JSON result
                lines = stdout.splitlines()
                if lines:
                    result = json.loads(lines[-1])
                    stdout = "\n".join(lines[:-1])
            except (json.JSONDecodeError, IndexError):
                result = stdout
        else:
            error = stderr or f"Process exited with code {proc.returncode}"
            # Check for specific errors
            if "ForbiddenModuleError" in error:
                error = "Security error: blocked module import"
            elif "TimeoutError" in error or "timed out" in error.lower():
                error = f"Execution timed out ({timeout}s)"
                timed_out = True

        return {
            "success": proc.returncode == 0,
            "result": result,
            "error": error,
            "timed_out": timed_out,
            "stdout": stdout,
            "stderr": stderr,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "result": None,
            "error": f"Execution timed out ({timeout}s)",
            "timed_out": True,
            "stdout": "",
            "stderr": "",
        }
    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": str(e),
            "timed_out": False,
            "stdout": "",
            "stderr": "",
        }
    finally:
        try:
            os.unlink(tmp.path)
        except OSError:
            pass


def _restricted_env() -> dict:
    """Create restricted environment variables."""
    env = os.environ.copy()
    # Remove sensitive variables
    for key in list(env.keys()):
        if any(s in key.upper() for s in ["KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL"]):
            del env[key]
    return env


def _build_wrapper(code: str, func_name: str, capture_state: bool) -> str:
    """Build a wrapper script that runs user code with restrictions."""
    # Escape code for embedding
    escaped_code = json.dumps(code)

    return textwrap.dedent(f'''\
import json
import sys
import builtins

# Block dangerous modules
BLOCKED = {json.dumps(list(BLOCKED_MODULES))}

class ForbiddenModuleError(ImportError):
    pass

_original_import = builtins.__import__

def restricted_import(name, *args, **kwargs):
    top = name.split(".")[0]
    if top in BLOCKED:
        raise ForbiddenModuleError(f"Import of '{{name}}' is blocked in sandbox")
    return _original_import(name, *args, **kwargs)

builtins.__import__ = restricted_import

# Block dangerous builtins
for attr in ["exec", "eval", "compile", "__import__", "open"]:
    if attr == "__import__":
        continue  # already replaced
    # Don't delete, just shadow with restricted version
    if attr == "open":
        def restricted_open(*a, **kw):
            raise PermissionError("File I/O is blocked in sandbox")
        builtins.open = restricted_open

# Run user code
_code = {escaped_code}

try:
    exec(compile(_code, "<user_code>", "exec"))

    func_name = {json.dumps(func_name)}
    if func_name and func_name in dir():
        func = locals()[func_name]
        result = func()
        print(json.dumps(result, default=str))
    elif "result" in dir():
        print(json.dumps(locals()["result"], default=str))
    else:
        # Find first callable
        for name, obj in list(locals().items()):
            if callable(obj) and not name.startswith("_") and name not in ("restricted_import", "restricted_open"):
                try:
                    result = obj()
                    print(json.dumps(result, default=str))
                    break
                except TypeError:
                    continue

except ForbiddenModuleError as e:
    print(f"ForbiddenModuleError: {{e}}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"{{type(e).__name__}}: {{e}}", file=sys.stderr)
    sys.exit(1)
''')
