"""The decision model in the Compose files under ``deployment/``: the opt-in decider sidecar and the vLLM overlay.

They are read as YAML, the way Compose sees them before interpolation, so no Docker is needed; where the
``docker`` command exists, the standalone file (what ``docsgpt up`` runs) is also resolved by Compose itself.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from docsgpt.decisions.models import V01

DEPLOYMENT = Path(__file__).resolve().parents[2] / "deployment"
STACKS = ("docker-compose.yaml", "docker-compose-hub.yaml", "docker-compose-standalone.yaml")
OVERLAY = DEPLOYMENT / "optional" / "docker-compose.optional.decide-vllm.yaml"
EVERY_FILE = [DEPLOYMENT / name for name in (*STACKS, "docker-compose-dev.yaml")] + [OVERLAY]
CACHE = "decision_models:/app/models/decision"


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _environment(service: dict[str, Any]) -> list[str]:
    return service.get("environment") or []


@pytest.mark.unit
@pytest.mark.parametrize("name", STACKS)
class TestStacks:
    def test_the_decider_serves_on_the_cpu_and_loads_nothing_by_itself(self, name):
        decider = _load(DEPLOYMENT / name)["services"]["decider"]
        assert decider["profiles"] == ["decider"], "opt-in: the backend holds the model by default"
        assert decider["command"] == "python -m docsgpt decide-server --host 0.0.0.0 --port 7095 --device cpu"
        assert decider["mem_limit"] == "${DECISION_MEMORY:-2g}"
        assert "cpus" not in decider and "ports" not in decider
        assert "environment" not in decider, "DECISION_KEY comes from .env, through env_file"
        assert decider["env_file"]
        assert decider["volumes"] == [CACHE]

    def test_it_runs_the_backends_image(self, name):
        services = _load(DEPLOYMENT / name)["services"]
        decider, backend = services["decider"], services["backend"]
        assert decider.get("image") == backend.get("image") and decider.get("build") == backend.get("build")
        assert decider.get("user") == backend.get("user") == "root"

    @pytest.mark.parametrize("service", ["backend", "worker"])
    def test_backend_and_worker_name_no_decision_server_and_no_key(self, name, service):
        """An unset DECISION_BASE_URL is local mode; set in .env, it and DECISION_KEY arrive through env_file."""
        target = _load(DEPLOYMENT / name)["services"][service]
        env = _environment(target)
        assert not [entry for entry in env if entry.split("=")[0] in ("DECISION_BASE_URL", "DECISION_KEY")]
        assert CACHE in target["volumes"]
        assert "decider" not in (target.get("depends_on") or {}), "decisions fail open; nothing waits for them"

    def test_the_model_cache_is_a_named_volume_and_never_hides_the_image_models(self, name):
        compose = _load(DEPLOYMENT / name)
        assert "decision_models" in compose["volumes"]
        for service in compose["services"].values():
            for volume in service.get("volumes") or []:
                assert volume.split(":")[1] != "/app/models", volume


@pytest.mark.unit
@pytest.mark.parametrize("path", EVERY_FILE, ids=lambda path: path.name)
def test_internal_key_never_keys_a_decision_server(path):
    """``INTERNAL_KEY`` guards the API's internal routes; a DECISION_BASE_URL outside the stack must never get it."""
    for name, service in _load(path)["services"].items():
        for entry in _environment(service):
            assert "INTERNAL_KEY" not in entry, (name, entry)


@pytest.mark.unit
class TestDev:
    def test_the_decider_is_opt_in_and_published_on_loopback(self):
        compose = _load(DEPLOYMENT / "docker-compose-dev.yaml")
        decider = compose["services"]["decider"]
        assert decider["profiles"] == ["decider"]
        assert decider["ports"] == ["127.0.0.1:7095:7095"]
        assert decider["build"]["dockerfile"] == "docsgpt/Dockerfile"
        assert decider["volumes"] == [CACHE] and "decision_models" in compose["volumes"]

    def test_it_takes_its_key_from_the_env_file_the_host_backend_reads(self):
        decider = _load(DEPLOYMENT / "docker-compose-dev.yaml")["services"]["decider"]
        assert "environment" not in decider
        assert decider["env_file"] == [{"path": "../.env", "required": False}]


@pytest.mark.unit
class TestVllmOverlay:
    def test_stock_vllm_serves_v01_at_its_pin(self):
        service = _load(OVERLAY)["services"]["decider-vllm"]
        image = service["image"]
        assert image.startswith("vllm/vllm-openai:v") and not image.endswith(":latest")
        args = service["command"]
        assert args[0] == V01.id
        assert args[args.index("--revision") + 1] == V01.revision
        assert args[args.index("--logprobs-mode") + 1] == "processed_logprobs"
        assert args[args.index("--max-logprobs") + 1] == "16"
        assert args[args.index("--gpu-memory-utilization") + 1] == "${DECISION_VLLM_GPU_SHARE:-0.2}"
        assert "--enable-log-requests" not in args
        assert service["deploy"]["resources"]["reservations"]["devices"] == [{"capabilities": ["gpu"]}]

    def test_vllm_requires_the_decision_key(self):
        """``:?`` stops Compose with a message rather than run vLLM with no key."""
        (key,) = [entry for entry in _environment(_load(OVERLAY)["services"]["decider-vllm"])
                  if entry.startswith("VLLM_API_KEY=")]
        assert key.startswith("VLLM_API_KEY=${DECISION_KEY:?set DECISION_KEY in .env")

    @pytest.mark.parametrize("service", ["backend", "worker"])
    def test_backend_and_worker_point_at_it(self, service):
        env = _environment(_load(OVERLAY)["services"][service])
        assert "DECISION_BASE_URL=http://decider-vllm:8000" in env and "DECISION_PROTOCOL=vllm" in env


def _config(where: Path, *files: Path, dotenv: str = "", **environ: str) -> subprocess.CompletedProcess:
    """``docker compose config`` on copies of ``files`` in ``where``, with ``dotenv`` as the stack's ``.env``, so no
    ``.env`` of this machine is read."""
    (where / ".env").write_text(dotenv, encoding="utf-8")
    for f in files:
        shutil.copy(f, where / f.name)
    return subprocess.run(
        ["docker", "compose", *[arg for f in files for arg in ("-f", f.name)], "config", "--format", "json"],
        cwd=where, capture_output=True, text=True, timeout=60,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(where), **environ},
    )


def _resolved(where: Path, *files: Path, dotenv: str = "", **environ: str) -> dict[str, Any]:
    result = _config(where, *files, dotenv=dotenv, **environ)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("docker") is None, reason="needs the docker command (no daemon)")
class TestResolved:
    def test_by_default_there_is_no_decider_and_no_decision_server(self, tmp_path):
        services = _resolved(tmp_path, DEPLOYMENT / "docker-compose-standalone.yaml", INTERNAL_KEY="k")["services"]
        assert "decider" not in services
        for name in ("backend", "worker"):
            assert "DECISION_BASE_URL" not in services[name]["environment"], name
            assert "DECISION_KEY" not in services[name]["environment"], name

    def test_three_env_lines_start_the_decider_and_point_both_at_it(self, tmp_path):
        dotenv = ("INTERNAL_KEY=stack-secret\nCOMPOSE_PROFILES=decider\nDECISION_BASE_URL=http://decider:7095\n"
                  "DECISION_KEY=decider-secret\n")
        services = _resolved(tmp_path, DEPLOYMENT / "docker-compose-standalone.yaml", dotenv=dotenv)["services"]
        for name in ("backend", "worker", "decider"):
            assert services[name]["environment"]["DECISION_KEY"] == "decider-secret", name
        for name in ("backend", "worker"):
            assert services[name]["environment"]["DECISION_BASE_URL"] == "http://decider:7095", name

    def test_a_server_outside_the_stack_never_gets_internal_key(self, tmp_path):
        dotenv = "INTERNAL_KEY=stack-secret\nCOMPOSE_PROFILES=decider\nDECISION_BASE_URL=http://gpu.example.com:7095\n"
        services = _resolved(tmp_path, DEPLOYMENT / "docker-compose-standalone.yaml", dotenv=dotenv,
                             INTERNAL_KEY="stack-secret")["services"]
        for name in ("backend", "worker", "decider"):
            assert "DECISION_KEY" not in services[name]["environment"], name

    def test_the_overlay_layers_on_the_standalone_file(self, tmp_path):
        services = _resolved(tmp_path, DEPLOYMENT / "docker-compose-standalone.yaml", OVERLAY,
                             dotenv="INTERNAL_KEY=i\nDECISION_KEY=k\n")["services"]
        assert services["backend"]["environment"]["DECISION_PROTOCOL"] == "vllm"
        assert services["decider-vllm"]["environment"]["VLLM_API_KEY"] == "k"
        assert services["worker"]["environment"]["DECISION_BASE_URL"] == "http://decider-vllm:8000"
        assert "decider" not in services

    def test_the_overlay_stops_without_a_key(self, tmp_path):
        result = _config(tmp_path, DEPLOYMENT / "docker-compose-standalone.yaml", OVERLAY,
                         dotenv="INTERNAL_KEY=i\n", INTERNAL_KEY="i")
        assert result.returncode != 0 and "set DECISION_KEY in .env" in result.stderr
        alone = _config(tmp_path, DEPLOYMENT / "docker-compose-standalone.yaml", dotenv="INTERNAL_KEY=i\n")
        assert alone.returncode == 0, "the stack alone needs no key"
