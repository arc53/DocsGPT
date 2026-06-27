"""Per-session isolation hardening for the Jupyter gateway sandbox.

Covers the env-scrubbing kernel launcher (`deployment/sandbox/kernel-launch.sh`)
and the `0700` per-session workspace perms applied by `_prime`. Hermetic: the
launcher test runs the wrapper with a fake `python` on PATH, and the `_prime`
test executes the wrapper's setup code against a real temp directory by
stubbing `_run` -- no gateway / kernel process required.
"""

import json
import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

from application.sandbox import jupyter_gateway
from application.sandbox.base import ExecResult
from application.sandbox.jupyter_gateway import JupyterKernelGatewaySandbox, _Kernel

_SANDBOX_DIR = Path(__file__).resolve().parents[2] / "deployment" / "sandbox"
_WRAPPER = _SANDBOX_DIR / "kernel-launch.sh"
_KERNEL_NAME = "docsgpt-python"
_KERNELSPEC = _SANDBOX_DIR / "kernels" / _KERNEL_NAME / "kernel.json"


# -- Env-scrubbing kernel launcher ---------------------------------------------


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX sh not available")
def test_kernel_launch_scrubs_secrets_keeps_runtime_env(tmp_path):
    """The wrapper drops *_API_KEY/*_TOKEN but keeps PATH/HOME/JUPYTER_* for ipykernel."""
    # Fake `python` on PATH: ignore `-m ipykernel_launcher` and dump the env it was given.
    fake_python = tmp_path / "python"
    fake_python.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            env
            """
        )
    )
    fake_python.chmod(0o755)

    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "LANG": "C.UTF-8",
        "JUPYTER_RUNTIME_DIR": str(tmp_path / "runtime"),
        "JUPYTER_DATA_DIR": str(tmp_path / "data"),
        # Secrets that must NOT reach the kernel.
        "OPENAI_API_KEY": "sk-super-secret",
        "SANDBOX_GATEWAY_AUTH_TOKEN": "gateway-token",
        "POSTGRES_URI": "postgresql://u:p@h/db",
    }
    proc = subprocess.run(
        ["sh", str(_WRAPPER), "-f", "/tmp/conn.json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    # Secrets stripped.
    assert "OPENAI_API_KEY" not in out
    assert "sk-super-secret" not in out
    assert "SANDBOX_GATEWAY_AUTH_TOKEN" not in out
    assert "POSTGRES_URI" not in out
    # Allowlisted runtime env kept.
    assert "PATH=" in out
    assert f"HOME={tmp_path}" in out
    assert f"JUPYTER_RUNTIME_DIR={tmp_path / 'runtime'}" in out
    assert f"JUPYTER_DATA_DIR={tmp_path / 'data'}" in out
    # The connection-file args were forwarded to ipykernel (reachability preserved).
    # The fake python prints env only, so just assert it was invoked with no crash above.


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX sh not available")
def test_kernel_launch_is_valid_sh():
    """The wrapper parses under POSIX sh (`sh -n`)."""
    proc = subprocess.run(["sh", "-n", str(_WRAPPER)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# -- Scrubbing kernelspec is selectable ----------------------------------------


def test_kernelspec_argv_points_at_scrubbing_wrapper():
    """The shipped kernel.json launches the env-scrubbing wrapper, not bare ipykernel."""
    spec = json.loads(_KERNELSPEC.read_text())
    argv = spec["argv"]
    assert argv[0].endswith("kernel-launch.sh")
    assert "{connection_file}" in argv


def test_distinct_kernel_name_resolves_to_scrubbing_spec(tmp_path, monkeypatch):
    """A distinct kernel name resolves to the scrubbing wrapper (never the stock python3 spec)."""
    kernelspec = pytest.importorskip("jupyter_client.kernelspec")

    # Seed a Jupyter data dir with the custom spec under its distinct name.
    data_dir = tmp_path / "jupyter"
    spec_dir = data_dir / "kernels" / _KERNEL_NAME
    spec_dir.mkdir(parents=True)
    shutil.copy(_KERNELSPEC, spec_dir / "kernel.json")
    monkeypatch.setenv("JUPYTER_PATH", str(data_dir))

    manager = kernelspec.KernelSpecManager()
    resolved = manager.get_kernel_spec(_KERNEL_NAME)
    assert resolved.argv[0].endswith("kernel-launch.sh")
    assert "{connection_file}" in resolved.argv


# -- Per-session workspace perms (0700) ----------------------------------------


def _exec_setup_in_tmp(code: str) -> None:
    """Run the kernel-side setup snippet in-process (it is plain os.* calls)."""
    exec(compile(code, "<setup>", "exec"), {})


def test_prime_creates_workspace_mode_0700(tmp_path, monkeypatch):
    """`_prime` creates the workspace root and per-session dir at mode 0700."""
    root = tmp_path / "docsgpt-sandbox"
    monkeypatch.setattr(jupyter_gateway, "_WORKSPACE_ROOT", str(root))

    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    workspace = f"{root}/conv-perms"
    kernel = _Kernel("kid", workspace)

    captured = {}

    def fake_run(_kernel, code, _timeout):
        captured["code"] = code
        _exec_setup_in_tmp(code)
        return ExecResult(status="ok", exit_code=0)

    monkeypatch.setattr(sb, "_run", fake_run)
    monkeypatch.chdir(tmp_path)  # _prime's os.chdir must land somewhere harmless
    sb._prime(kernel)

    assert kernel.initialized
    assert stat.S_IMODE(os.stat(root).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(workspace).st_mode) == 0o700
