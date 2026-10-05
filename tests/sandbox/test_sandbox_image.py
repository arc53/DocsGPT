"""The self-hosted runner image: kernel environment, Dockerfile and the manifests that run it.

The kernel environment tests run ``kernel-env.sh`` with a stub command; the
rest read the Dockerfile, the compose overlay and the Kubernetes manifest and
check them against the sandbox manifest and each other.
"""

from __future__ import annotations

import os
import shutil
import site
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Dict

import pytest
import yaml

from docsgpt.core.settings.sandbox import SandboxSettings
from docsgpt.sandbox import manifest

_REPO = Path(__file__).resolve().parents[2]
_SANDBOX_DIR = _REPO / "deployment" / "sandbox"
_KERNEL_ENV = _SANDBOX_DIR / "kernel-env.sh"
_KERNEL_LAUNCH = _SANDBOX_DIR / "kernel-launch.sh"
_DOCKERFILE = _SANDBOX_DIR / "Dockerfile"
_COMPOSE = _REPO / "deployment" / "optional" / "docker-compose.optional.sandbox.yaml"
_K8S = _REPO / "deployment" / "k8s" / "deployments" / "sandbox-deploy.yaml"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX sh not available")


def _parse_env(out: str) -> Dict[str, str]:
    env = {}
    for line in out.splitlines():
        name, sep, value = line.partition("=")
        if sep:
            env[name] = value
    return env


def _run_kernel_env(tmp_path: Path, *command: str, script: Path = _KERNEL_ENV, **extra: str):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": "/home/sandbox",
        "LANG": "C.UTF-8",
        "JUPYTER_RUNTIME_DIR": str(tmp_path / "runtime"),
        "JUPYTER_DATA_DIR": str(tmp_path / "data"),
        "SANDBOX_KERNEL_HOME": str(tmp_path / "home"),
        "OPENAI_API_KEY": "sk-super-secret",
        "SANDBOX_GATEWAY_AUTH_TOKEN": "gateway-token",
        "POSTGRES_URI": "postgresql://u:p@h/db",
        **extra,
    }
    return subprocess.run(["sh", str(script), *command], env=env, capture_output=True, text=True, timeout=30)


# -- Kernel environment --------------------------------------------------------


def test_kernel_env_scrubs_secrets(tmp_path):
    proc = _run_kernel_env(tmp_path, "env")
    assert proc.returncode == 0, proc.stderr
    assert "sk-super-secret" not in proc.stdout
    assert "gateway-token" not in proc.stdout
    env = _parse_env(proc.stdout)
    for name in ("OPENAI_API_KEY", "SANDBOX_GATEWAY_AUTH_TOKEN", "POSTGRES_URI", "SANDBOX_KERNEL_HOME"):
        assert name not in env


def test_kernel_env_points_home_and_caches_at_a_writable_dir(tmp_path):
    """The root filesystem is read-only, so LibreOffice, Chromium, fontconfig and pip --user need a tmp HOME."""
    home = tmp_path / "home"
    proc = _run_kernel_env(tmp_path, "env")
    assert proc.returncode == 0, proc.stderr
    env = _parse_env(proc.stdout)
    assert env["HOME"] == str(home)
    assert env["XDG_CONFIG_HOME"] == str(home / ".config")
    assert env["XDG_CACHE_HOME"] == str(home / ".cache")
    assert env["PYTHONUSERBASE"] == str(home / ".local")
    assert env["PATH"].endswith(f":{home / '.local' / 'bin'}")
    for sub in (".config", ".cache", ".local/bin"):
        assert (home / sub).is_dir()
    assert oct(home.stat().st_mode & 0o777) == "0o700"


def test_kernel_env_keeps_the_jupyter_runtime_env(tmp_path):
    proc = _run_kernel_env(tmp_path, "env")
    env = _parse_env(proc.stdout)
    assert env["LANG"] == "C.UTF-8"
    assert env["JUPYTER_RUNTIME_DIR"] == str(tmp_path / "runtime")
    assert env["JUPYTER_DATA_DIR"] == str(tmp_path / "data")


def test_kernel_env_passes_the_manifest_env(tmp_path):
    env = _parse_env(_run_kernel_env(tmp_path, "env").stdout)
    for name, value in manifest.ENV.items():
        assert env[name] == value


def test_kernel_env_defaults_home_to_tmp_home():
    text = _KERNEL_ENV.read_text()
    assert 'KERNEL_HOME="${SANDBOX_KERNEL_HOME:-/tmp/home}"' in text


def test_kernel_env_creates_the_user_site_dir_so_pip_user_installs_import(tmp_path):
    """Python only puts the user site on sys.path if it exists at startup; create it before the kernel starts."""
    python_dir = Path(sys.executable).parent
    proc = _run_kernel_env(
        tmp_path,
        "python",
        "-c",
        "import site; print(site.getusersitepackages())",
        PATH=f"{python_dir}:{os.environ.get('PATH', '')}",
    )
    assert proc.returncode == 0, proc.stderr
    user_site = Path(proc.stdout.strip())
    assert user_site.is_relative_to(tmp_path / "home" / ".local")
    assert user_site.is_dir()


@pytest.mark.skipif(not site.ENABLE_USER_SITE, reason="user site disabled (running inside a virtualenv)")
def test_user_site_is_on_sys_path_in_the_kernel(tmp_path):
    python_dir = Path(sys.executable).parent
    proc = _run_kernel_env(
        tmp_path,
        "python",
        "-c",
        "import site, sys; print(site.getusersitepackages() in sys.path)",
        PATH=f"{python_dir}:{os.environ.get('PATH', '')}",
    )
    assert proc.stdout.strip() == "True", proc.stderr


def test_kernel_env_reads_its_env_file_and_skips_bad_lines(tmp_path):
    scripts = tmp_path / "opt"
    scripts.mkdir()
    shutil.copy(_KERNEL_ENV, scripts / "kernel-env.sh")
    (scripts / "sandbox.env").write_text("# comment\n\nFOO_BAR=1\nnot an assignment\nlower=x\nLAST=ok")
    proc = _run_kernel_env(tmp_path, "env", script=scripts / "kernel-env.sh")
    assert proc.returncode == 0, proc.stderr
    env = _parse_env(proc.stdout)
    assert env["FOO_BAR"] == "1"
    assert env["LAST"] == "ok"  # no trailing newline
    assert "lower" not in env
    assert "malformed" in proc.stderr


def test_kernel_env_works_without_an_env_file(tmp_path):
    scripts = tmp_path / "opt"
    scripts.mkdir()
    shutil.copy(_KERNEL_ENV, scripts / "kernel-env.sh")
    proc = _run_kernel_env(tmp_path, "env", script=scripts / "kernel-env.sh")
    assert proc.returncode == 0, proc.stderr
    assert "OMP_THREAD_LIMIT" not in _parse_env(proc.stdout)


def test_kernel_launch_runs_ipykernel_under_kernel_env(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "python").write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            echo "ARGS: $*"
            echo "HOME=$HOME"
            echo "LEAK=${OPENAI_API_KEY:-}"
            """
        )
    )
    (fake / "python").chmod(0o755)
    proc = _run_kernel_env(
        tmp_path, "-f", "/tmp/conn.json", script=_KERNEL_LAUNCH, PATH=f"{fake}:{os.environ.get('PATH', '')}"
    )
    assert proc.returncode == 0, proc.stderr
    assert "ARGS: -m ipykernel_launcher -f /tmp/conn.json" in proc.stdout
    assert f"HOME={tmp_path / 'home'}" in proc.stdout
    assert "LEAK=\n" in proc.stdout or proc.stdout.rstrip().endswith("LEAK=")


@pytest.mark.parametrize("script", [_KERNEL_ENV, _KERNEL_LAUNCH, _SANDBOX_DIR / "install-system.sh"])
def test_shell_scripts_parse(script):
    proc = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# -- Dockerfile ----------------------------------------------------------------


def test_dockerfile_installs_from_the_generated_files():
    text = _DOCKERFILE.read_text()
    assert "COPY requirements.txt" in text
    assert "pip install --no-cache-dir -r /opt/docsgpt/requirements.txt" in text
    assert "COPY install-system.sh" in text
    assert "sh /opt/docsgpt/install-system.sh" in text
    # No package pins left in the Dockerfile itself: they come from the manifest.
    for spec in manifest.pip_specs(include_runner=True):
        assert spec not in text


def test_dockerfile_installs_system_packages_and_python_before_dropping_root():
    text = _DOCKERFILE.read_text()
    user = text.index("USER 10001")
    assert text.index("sh /opt/docsgpt/install-system.sh") < user
    assert text.index("pip install --no-cache-dir -r") < user


def test_dockerfile_puts_every_helper_on_path():
    text = _DOCKERFILE.read_text()
    for name, source in manifest.HELPERS.items():
        assert f"COPY {source} /usr/local/bin/{name}" in text


def test_dockerfile_ships_the_kernel_env_and_smoke_test():
    text = _DOCKERFILE.read_text()
    for name in ("kernel-env.sh", "kernel-launch.sh", "sandbox.env", "smoke_test.py", "manifest.json"):
        assert f"/opt/docsgpt/{name}" in text, name


def test_dockerfile_states_the_licenses_honestly():
    text = _DOCKERFILE.read_text()
    assert "all permissive" not in text
    for term in ("MPL-2.0", "GPL", "AGPL", "Apache-2.0", "BSD", "MIT"):
        assert term in text, term
    assert "ffmpeg" in text


# -- Compose and Kubernetes ----------------------------------------------------


def _compose_service() -> dict:
    return yaml.safe_load(_COMPOSE.read_text())["services"]["docsgpt-sandbox"]


def test_compose_gives_the_runner_room_for_office_and_chromium():
    svc = _compose_service()
    assert svc["mem_limit"] == "${SANDBOX_MEMORY:-4g}"
    assert svc["shm_size"] == "256m"
    assert svc["pids_limit"] == 1024


def test_compose_keeps_the_runner_hardened():
    svc = _compose_service()
    assert svc["read_only"] is True
    assert "/tmp" in svc["tmpfs"]
    assert not any("docker.sock" in str(v) for v in svc.get("volumes", []))


def test_settings_default_matches_the_compose_default():
    assert SandboxSettings.model_fields["SANDBOX_MEMORY"].default == "4g"


def _k8s_deployment() -> dict:
    return next(d for d in yaml.safe_load_all(_K8S.read_text()) if d and d["kind"] == "Deployment")


def test_k8s_runner_matches_the_compose_limits():
    pod = _k8s_deployment()["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert container["resources"]["limits"]["memory"] == "4Gi"
    shm = next(m for m in container["volumeMounts"] if m["mountPath"] == "/dev/shm")
    volume = next(v for v in pod["volumes"] if v["name"] == shm["name"])
    assert volume["emptyDir"] == {"medium": "Memory", "sizeLimit": "256Mi"}


def test_k8s_runner_keeps_the_security_posture():
    pod = _k8s_deployment()["spec"]["template"]["spec"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["runAsUser"] == 10001
    container = pod["containers"][0]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
