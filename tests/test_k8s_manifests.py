"""Static checks on the Kubernetes manifests under ``deployment/k8s``.

No cluster is needed: these read the YAML the way ``kubectl apply -k`` would
and pin the properties the guide relies on, so a manifest edit that makes the
stack public, unmigrated or unable to share uploads fails here first.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from docsgpt.version import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
K8S = REPO_ROOT / "deployment" / "k8s"


def _documents(path: Path) -> list[dict[str, Any]]:
    """Every non-empty YAML document in ``path``.

    Args:
        path: A manifest file.

    Returns:
        The parsed documents, skipping empty ones.
    """
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


def _kustomization() -> dict[str, Any]:
    """The default kustomization."""
    return yaml.safe_load((K8S / "kustomization.yaml").read_text())


def _default_resources() -> list[dict[str, Any]]:
    """Every object ``kubectl apply -k deployment/k8s/`` creates."""
    docs: list[dict[str, Any]] = []
    for resource in _kustomization()["resources"]:
        docs.extend(_documents(K8S / resource))
    return docs


def _by_kind(kind: str) -> list[dict[str, Any]]:
    """The default resources of one kind."""
    return [doc for doc in _default_resources() if doc["kind"] == kind]


def _named(kind: str, name: str) -> dict[str, Any]:
    """The default resource of ``kind`` called ``name``."""
    matches = [doc for doc in _by_kind(kind) if doc["metadata"]["name"] == name]
    assert matches, f"no {kind} named {name} in the default kustomization"
    return matches[0]


def _pod_spec(obj: dict[str, Any]) -> dict[str, Any]:
    """The pod spec of a Deployment or Job."""
    return obj["spec"]["template"]["spec"]


def _containers(obj: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every container and init container of a Deployment or Job."""
    spec = _pod_spec(obj)
    yield from spec.get("initContainers", [])
    yield from spec["containers"]


def _secret_data() -> dict[str, str]:
    """The default ``docsgpt-secrets`` values as plain strings."""
    secret = _named("Secret", "docsgpt-secrets")
    assert "data" not in secret, "use stringData so operators edit plain values, not base64"
    return secret["stringData"]


def _main_container(name: str) -> dict[str, Any]:
    """The container named like its Deployment."""
    deployment = _named("Deployment", name)
    return next(c for c in _pod_spec(deployment)["containers"] if c["name"] == name)


def test_kustomization_resources_exist() -> None:
    for resource in _kustomization()["resources"]:
        assert (K8S / resource).is_file(), resource


def test_nothing_is_published_outside_the_cluster() -> None:
    for service in _by_kind("Service"):
        assert service["spec"].get("type", "ClusterIP") == "ClusterIP", service["metadata"]["name"]


def test_api_serves_the_ui_so_there_is_no_frontend_deployment() -> None:
    names = {doc["metadata"]["name"] for doc in _default_resources()}
    assert "docsgpt-frontend" not in names
    assert "docsgpt-frontend-service" not in names


def test_opt_in_manifests_stay_out_of_the_default_stack() -> None:
    resources = " ".join(_kustomization()["resources"])
    assert "sandbox" not in resources
    assert "qdrant" not in resources
    assert "ingress" not in resources


def test_secret_ships_no_usable_credentials() -> None:
    data = _secret_data()
    for key in ("INTERNAL_KEY", "JWT_SECRET_KEY", "ENCRYPTION_SECRET_KEY", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        assert data.get(key, "").startswith("REPLACE_ME"), key


def test_secret_points_every_redis_client_at_the_redis_service() -> None:
    data = _secret_data()
    for key in ("CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "CACHE_REDIS_URL"):
        assert data[key].startswith("redis://redis-service:6379/"), key
    assert "QDRANT_URL" not in data
    assert "QDRANT_PORT" not in data


def test_uploads_and_vectors_are_shared_between_pods() -> None:
    data = _secret_data()
    assert data["STORAGE_TYPE"] == "s3"
    assert data["VECTOR_STORE"] == "pgvector"


def test_postgres_image_has_pgvector() -> None:
    image = _main_container("postgres")["image"]
    assert image.startswith("pgvector/pgvector:"), image


def test_postgres_never_runs_two_servers_on_one_volume() -> None:
    assert _named("Deployment", "postgres")["spec"]["strategy"] == {"type": "Recreate"}


def test_placeholder_secrets_stop_the_pods() -> None:
    for kind, name in (("Job", "postgres-init"), ("Deployment", "docsgpt-api"), ("Deployment", "docsgpt-worker")):
        init = {c["name"]: c for c in _pod_spec(_named(kind, name)).get("initContainers", [])}
        assert "check-secrets" in init, name
        script = " ".join(init["check-secrets"]["command"])
        assert "REPLACE_ME" in script and "exit 1" in script, name


def test_migration_job_runs_the_packaged_migrate_command() -> None:
    job = _named("Job", "postgres-init")
    container = next(c for c in _pod_spec(job)["containers"] if c["name"] == "postgres-init")
    # docsgpt.cli, not the package: the 0.21.0 image predates docsgpt/__main__.py.
    assert container["command"] == ["python", "-m", "docsgpt.cli", "migrate", "--no-create"]


@pytest.mark.parametrize("name", ["docsgpt-api", "docsgpt-worker"])
def test_app_pods_wait_for_the_schema_their_image_needs(name: str) -> None:
    init = {c["name"]: c for c in _pod_spec(_named("Deployment", name))["initContainers"]}
    waiter = init["wait-for-migrations"]
    assert waiter["image"] == _main_container(name)["image"]
    script = " ".join(waiter["command"])
    assert "get_current_head" in script and "get_current_revision" in script


def test_worker_runs_the_beat_scheduler() -> None:
    command = _main_container("docsgpt-worker")["command"]
    assert "-B" in command
    assert "embeddings" in command[command.index("-Q") + 1]


def test_worker_reaches_the_api_inside_the_cluster() -> None:
    env = {e["name"]: e.get("value") for e in _main_container("docsgpt-worker")["env"]}
    assert env["API_URL"] == "http://docsgpt-api-service"


def test_images_are_pinned() -> None:
    for obj in _by_kind("Deployment") + _by_kind("Job"):
        for container in _containers(obj):
            image = container["image"]
            assert re.search(r":[^/]+$", image), f"{image} has no tag"
            assert not image.endswith(":latest"), image


def test_docsgpt_image_matches_the_release_version() -> None:
    for obj in _by_kind("Deployment") + _by_kind("Job"):
        for container in _containers(obj):
            if container["image"].startswith("arc53/docsgpt:"):
                assert container["image"] == f"arc53/docsgpt:{__version__}", container["name"]


def test_sandbox_image_matches_the_release_version() -> None:
    sandbox = next(d for d in _documents(K8S / "deployments" / "sandbox-deploy.yaml") if d["kind"] == "Deployment")
    assert _pod_spec(sandbox)["containers"][0]["image"] == f"arc53/docsgpt-sandbox:{__version__}"


@pytest.mark.parametrize(
    "path",
    [
        "deployments/sandbox-deploy.yaml",
        "deployments/qdrant-deploy.yaml",
        "optional-mongo/deployments/mongo-deploy.yaml",
    ],
)
def test_opt_in_images_are_pinned(path: str) -> None:
    for obj in _documents(K8S / path):
        if obj["kind"] != "Deployment":
            continue
        for container in _containers(obj):
            assert not container["image"].endswith(":latest"), container["image"]
            assert re.search(r":[^/]+$", container["image"]), container["image"]


def test_sandbox_header_does_not_claim_the_kernel_is_preset() -> None:
    assert "already set in docsgpt-deploy.yaml" not in (K8S / "deployments" / "sandbox-deploy.yaml").read_text()


def test_ingress_example_targets_the_api_service() -> None:
    docs = _documents(K8S / "ingress-example.yaml")
    ingress = next(doc for doc in docs if doc["kind"] == "Ingress")
    backend = ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
    assert backend["name"] == "docsgpt-api-service"
    assert ingress["spec"]["tls"], "the example must terminate TLS"
