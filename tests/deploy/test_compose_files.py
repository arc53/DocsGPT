"""The decider sidecar and the vLLM overlay in the Compose files under ``deployment/``.

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
KEY = "DECISION_KEY=${DECISION_KEY:-${INTERNAL_KEY:-}}"
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
        assert decider["command"] == "python -m docsgpt decide-server --host 0.0.0.0 --port 7095 --device cpu"
        assert decider["mem_limit"] == "${DECISION_MEMORY:-2g}"
        assert "cpus" not in decider and "ports" not in decider
        assert KEY in _environment(decider)
        assert decider["volumes"] == [CACHE]

    def test_it_runs_the_backends_image(self, name):
        services = _load(DEPLOYMENT / name)["services"]
        decider, backend = services["decider"], services["backend"]
        assert decider.get("image") == backend.get("image") and decider.get("build") == backend.get("build")
        assert decider.get("user") == backend.get("user") == "root"

    @pytest.mark.parametrize("service", ["backend", "worker"])
    def test_backend_and_worker_call_it_with_the_stack_key(self, name, service):
        target = _load(DEPLOYMENT / name)["services"][service]
        env = _environment(target)
        assert "DECISION_BASE_URL=${DECISION_BASE_URL:-http://decider:7095}" in env
        assert KEY in env
        assert CACHE in target["volumes"]
        assert "decider" not in (target.get("depends_on") or {}), "decisions fail open; nothing waits for them"

    def test_the_model_cache_is_a_named_volume_and_never_hides_the_image_models(self, name):
        compose = _load(DEPLOYMENT / name)
        assert "decision_models" in compose["volumes"]
        for service in compose["services"].values():
            for volume in service.get("volumes") or []:
                assert volume.split(":")[1] != "/app/models", volume


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

    @pytest.mark.parametrize("service", ["backend", "worker"])
    def test_backend_and_worker_point_at_it(self, service):
        env = _environment(_load(OVERLAY)["services"][service])
        assert "DECISION_BASE_URL=http://decider-vllm:8000" in env and "DECISION_PROTOCOL=vllm" in env


def _resolved(where: Path, *files: Path, **environ: str) -> dict[str, Any]:
    """``docker compose config`` on copies of ``files`` in ``where``, so no ``.env`` of this machine is read."""
    for f in files:
        shutil.copy(f, where / f.name)
    result = subprocess.run(
        ["docker", "compose", *[arg for f in files for arg in ("-f", f.name)], "config", "--format", "json"],
        cwd=where, capture_output=True, text=True, timeout=60,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(where), **environ},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("docker") is None, reason="needs the docker command (no daemon)")
class TestResolved:
    def test_the_stack_key_reaches_all_three(self, tmp_path):
        services = _resolved(tmp_path, DEPLOYMENT / "docker-compose-standalone.yaml", INTERNAL_KEY="stack-secret")["services"]
        for name in ("backend", "worker", "decider"):
            assert services[name]["environment"]["DECISION_KEY"] == "stack-secret", name
        assert services["backend"]["environment"]["DECISION_BASE_URL"] == "http://decider:7095"

    def test_an_explicit_key_and_url_win(self, tmp_path):
        services = _resolved(tmp_path, DEPLOYMENT / "docker-compose-standalone.yaml", INTERNAL_KEY="stack-secret",
                             DECISION_KEY="own", DECISION_BASE_URL="http://host.docker.internal:7095")["services"]
        assert services["decider"]["environment"]["DECISION_KEY"] == "own"
        assert services["worker"]["environment"]["DECISION_BASE_URL"] == "http://host.docker.internal:7095"

    def test_the_overlay_layers_on_the_standalone_file(self, tmp_path):
        services = _resolved(tmp_path, DEPLOYMENT / "docker-compose-standalone.yaml", OVERLAY, INTERNAL_KEY="k")["services"]
        assert services["backend"]["environment"]["DECISION_PROTOCOL"] == "vllm"
        assert services["decider-vllm"]["environment"]["VLLM_API_KEY"] == "k"
        assert "decider" in services, "the idle CPU decider stays"
