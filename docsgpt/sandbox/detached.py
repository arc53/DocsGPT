"""Detached runs: a script started as its own process in the sandbox, followed by polling.

``code_executor`` starts a run detached when it may outlive the turn (a
background job): the script lives at ``scratch/jobs/<key>/main.py`` and its
output is read back when it exits, so whoever polls (the turn, or a Celery
poller after a hand-off) builds the same :class:`ExecResult` an ``exec`` would
have returned. The helpers here are shared by the Daytona and Jupyter
backends so both read a finished process the same way.
"""

from __future__ import annotations

import base64
import re
from typing import Iterable, Optional

from docsgpt.sandbox.base import ExecResult, Plot

#: Charts one run may return, and their size limits.
MAX_CHARTS = 4
MAX_CHART_PIXELS = 16_000_000
MAX_CHART_BYTES = 2_000_000

#: Run before the code: once it imports pyplot, ``plt.show()`` prints each open
#: figure as a PNG between chart markers and closes it.
CHART_PRELUDE = f"""\
import sys as _dg_sys

_dg_left = [{MAX_CHARTS}]


def _dg_show(*args, **kwargs):
    import base64, io
    plt = _dg_sys.modules["matplotlib.pyplot"]
    for number in plt.get_fignums():
        if _dg_left[0] <= 0:
            break
        figure = plt.figure(number)
        width, height = figure.get_size_inches() * figure.dpi
        if width * height > {MAX_CHART_PIXELS}:
            continue
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", bbox_inches="tight")
        if buffer.tell() <= {MAX_CHART_BYTES}:
            _dg_left[0] -= 1
            print("<<docsgpt-chart:" + base64.b64encode(buffer.getvalue()).decode() + ">>")
    plt.close("all")


class _DgPyplotHook:
    def find_spec(self, name, path=None, target=None):
        if name != "matplotlib.pyplot":
            return None
        _dg_sys.meta_path.remove(self)
        import importlib.util
        spec = importlib.util.find_spec(name)
        exec_module = spec.loader.exec_module

        def _exec(module):
            exec_module(module)
            module.show = _dg_show

        spec.loader.exec_module = _exec
        return spec


if "matplotlib.pyplot" in _dg_sys.modules:
    _dg_sys.modules["matplotlib.pyplot"].show = _dg_show
else:
    _dg_sys.meta_path.insert(0, _DgPyplotHook())
"""
CHART_RE = re.compile(r"<<docsgpt-chart:([A-Za-z0-9+/=]+)>>\n?")

#: Exit status of ``timeout`` when the command outlived it.
TIMEOUT_EXIT_CODE = 124

#: Exit codes of a SIGKILLed process: 128 + 9 through a shell, -9 from the process.
SIGKILL_EXIT_CODES = frozenset({137, -9})

#: Bytes of output a running job reports while it runs.
RUNNING_OUTPUT_BYTES = 8_192


def job_dir(key: str) -> str:
    """Workspace-relative directory of one detached run (under ``scratch/``, never captured)."""
    return f"scratch/jobs/{key}"


def split_leading_future_imports(code: str) -> tuple[str, str]:
    """Split leading ``from __future__`` imports from the rest so a prelude can go between.

    Args:
        code: The submitted source.

    Returns:
        ``(hoisted, rest)``; ``hoisted`` is empty when there is no future import.
    """
    lines = code.splitlines(keepends=True)
    saw_future = False
    split_at = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if stripped.startswith("from __future__ import"):
            saw_future = True
            continue
        split_at = i
        break
    else:
        split_at = len(lines)
    if not saw_future:
        return "", code
    hoisted = "".join(lines[:split_at])
    if hoisted and not hoisted.endswith("\n"):
        hoisted += "\n"
    return hoisted, "".join(lines[split_at:])


def script_for(workspace: str, code: str) -> str:
    """The detached script: chdir into the workspace, install the chart hook, run the code."""
    hoisted, rest = split_leading_future_imports(code)
    prelude = (
        "import os as _os\n"
        f"_os.makedirs({workspace!r}, exist_ok=True)\n"
        f"_os.chdir({workspace!r})\n"
        + CHART_PRELUDE
    )
    return hoisted + prelude + rest


def result_from_output(
    stdout: str,
    exit_code: Optional[int],
    *,
    max_output_bytes: int = 0,
    extra_pngs: Iterable[str] = (),
) -> ExecResult:
    """Build an :class:`ExecResult` from a finished process's merged output and exit code.

    Charts the run showed are taken out of the output before it is capped. A
    SIGKILLed process (the sandbox's OOM killer) is reported as out of memory.

    Args:
        stdout: stdout and stderr, merged.
        exit_code: The process's exit status.
        max_output_bytes: Cap on the output kept (0 disables).
        extra_pngs: Base64 PNGs the backend extracted on its own.

    Returns:
        The result, as ``exec`` reports it.
    """
    exit_code = exit_code or 0
    charts = CHART_RE.findall(stdout)
    stdout = CHART_RE.sub("", stdout)
    truncated = False
    if max_output_bytes and len(stdout.encode("utf-8", "ignore")) > max_output_bytes:
        stdout = stdout.encode("utf-8", "ignore")[:max_output_bytes].decode("utf-8", "ignore")
        stdout += f"\n[output truncated at {max_output_bytes} bytes]"
        truncated = True
    result = ExecResult(status="ok" if exit_code == 0 else "error", stdout=stdout, exit_code=exit_code)
    result.truncated = truncated
    if exit_code in SIGKILL_EXIT_CODES:
        result.error_name = "ExecutionError"
        result.error_value = (
            f"the process was killed (exit code {exit_code}), most likely for using more memory than the "
            "sandbox allows"
        )
        result.out_of_memory = True
    elif exit_code != 0:
        result.error_name = "ExecutionError"
        result.error_value = stdout or f"exited with code {exit_code}"
    result.plots = [Plot(format="png", content_base64=png) for png in charts]
    result.plots.extend(Plot(format="png", content_base64=png) for png in extra_pngs if png)
    return result


def finished_result(
    output: str,
    exit_code: Optional[int],
    *,
    elapsed: float,
    wall: float,
    max_output_bytes: int = 0,
) -> ExecResult:
    """A detached run's result: a ``timeout`` exit becomes the same ``TimeoutError`` an ``exec`` reports.

    ``timeout -k`` escalates to SIGKILL when the process ignores SIGTERM, so a
    SIGKILL at or past the wall-clock cap is a timeout, not an OOM kill. Unlike
    an ``exec`` timeout, the output the run printed before it was stopped is kept.

    Args:
        output: Merged stdout and stderr.
        exit_code: The wrapper's exit status.
        elapsed: Seconds the run took.
        wall: Its wall-clock cap.
        max_output_bytes: Cap on the output kept.

    Returns:
        The result.
    """
    timed_out = exit_code == TIMEOUT_EXIT_CODE or (exit_code in SIGKILL_EXIT_CODES and elapsed >= wall)
    if not timed_out:
        return result_from_output(output, exit_code, max_output_bytes=max_output_bytes)
    result = result_from_output(output, 0, max_output_bytes=max_output_bytes)
    result.status = "error"
    result.exit_code = -1
    result.error_name = "TimeoutError"
    result.error_value = f"execution exceeded {int(wall)}s"
    return result


def tail_bytes(text: str, limit: int = RUNNING_OUTPUT_BYTES) -> str:
    """The last ``limit`` bytes of ``text`` (chart markers removed)."""
    clean = CHART_RE.sub("", text or "")
    encoded = clean.encode("utf-8", "ignore")
    if len(encoded) <= limit:
        return clean
    return encoded[-limit:].decode("utf-8", "ignore")


def decode_marker_json(stdout: str, begin: str, end: str) -> Optional[str]:
    """The text between ``begin`` and ``end`` markers in ``stdout``, or None."""
    start = stdout.find(begin)
    stop = stdout.find(end, start + len(begin)) if start != -1 else -1
    if start == -1 or stop == -1:
        return None
    return stdout[start + len(begin):stop]


def b64(text: str) -> str:
    """Base64 of ``text`` (UTF-8), for embedding untrusted strings in generated code."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")
