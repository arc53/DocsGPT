"""End-to-end CodeExecutorTool: live Jupyter gateway + ephemeral Postgres + local storage.

Launches a real ``jupyter kernelgateway`` (no Docker — the credential helper
hangs on dev machines), wires the tool to the ephemeral pytest-postgresql DB
and a temp-dir ``LocalStorage``, and drives ``run_code`` through the full path:
code writes a file -> artifact row + bytes persisted with server-side size/
sha256/mime -> compact payload + ``get_artifact_id``. Also covers an input
artifact round-trip and the timeout error path (no hang).

Skips gracefully when the gateway binary or websocket-client is unavailable.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import socket
import subprocess
import time
import uuid

import pytest
from sqlalchemy import text

requests = pytest.importorskip("requests")
pytest.importorskip("websocket")  # websocket-client

from application.agents.tools.code_executor import CodeExecutorTool  # noqa: E402
from application.sandbox.jupyter_gateway import JupyterKernelGatewaySandbox  # noqa: E402
from application.sandbox.manager import SandboxManager  # noqa: E402
from application.sandbox.sandbox_creator import SandboxCreator  # noqa: E402
from application.storage.db.repositories.artifacts import ArtifactsRepository  # noqa: E402
from application.storage.local import LocalStorage  # noqa: E402
from application.storage.storage_creator import StorageCreator  # noqa: E402

_GATEWAY_BIN = shutil.which("jupyter-kernelgateway") or shutil.which("jupyter")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        _GATEWAY_BIN is None,
        reason="jupyter kernel gateway not installed (pip install jupyter-kernel-gateway)",
    ),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _gateway_cmd(port: int) -> list:
    if _GATEWAY_BIN.endswith("jupyter-kernelgateway"):
        base = [_GATEWAY_BIN]
    else:
        base = [_GATEWAY_BIN, "kernelgateway"]
    return base + [
        "--KernelGatewayApp.ip=127.0.0.1",
        f"--KernelGatewayApp.port={port}",
        "--ZMQChannelsWebsocketConnection.limit_rate=False",
    ]


@pytest.fixture(scope="module")
def gateway_url():
    port = _free_port()
    proc = subprocess.Popen(_gateway_cmd(port), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    ready = False
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                pytest.skip("jupyter kernelgateway process exited during startup")
            try:
                if requests.get(f"{url}/api", timeout=1).status_code == 200:
                    ready = True
                    break
            except requests.RequestException:
                time.sleep(0.3)
        if not ready:
            pytest.skip("jupyter kernelgateway did not become ready in time")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture()
def wired_tool(gateway_url, pg_engine, tmp_path, monkeypatch):
    """A CodeExecutorTool wired to the live gateway, ephemeral PG, and a temp local store."""
    # Sandbox: a fresh manager over the live gateway, installed as the singleton.
    backend = JupyterKernelGatewaySandbox(gateway_url=gateway_url, default_timeout=30.0)
    SandboxCreator._instance = SandboxManager(backend=backend, max_ttl=1200.0)

    # Storage: temp-dir local storage as the singleton.
    storage = LocalStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(StorageCreator, "_instance", storage, raising=False)

    # DB: route db_session()/db_readonly() at the ephemeral PG engine.
    monkeypatch.setattr("application.storage.db.session.get_engine", lambda: pg_engine)

    conversation_id = str(uuid.uuid4())
    tool = CodeExecutorTool(
        tool_config={"conversation_id": conversation_id, "tool_id": str(uuid.uuid4())},
        user_id="user-e2e",
    )
    try:
        yield tool, conversation_id, pg_engine, storage
    finally:
        SandboxCreator.reset()


def test_run_code_persists_produced_artifact(wired_tool):
    tool, conversation_id, pg_engine, storage = wired_tool

    code = (
        "with open('report.txt', 'w') as f:\n"
        "    f.write('hello artifact')\n"
        "print('wrote report')\n"
    )
    payload = tool.execute_action("run_code", code=code, ttl=120)

    assert payload["status"] == "ok", payload
    assert "wrote report" in payload["stdout_tail"]
    assert len(payload["artifacts"]) == 1
    art = payload["artifacts"][0]
    assert art["filename"] == "report.txt"
    assert art["mime_type"] == "text/plain"
    assert art["size"] == len(b"hello artifact")
    assert art["version"] == 1

    # get_artifact_id points at the produced artifact (UI rail).
    assert tool.get_artifact_id("run_code") == art["artifact_id"]

    # DB row exists, parent-scoped, with server-computed size + sha256.
    with pg_engine.connect() as conn:
        repo = ArtifactsRepository(conn)
        artifact = repo.get_artifact_in_parent(art["artifact_id"], conversation_id=conversation_id)
        assert artifact is not None
        version = repo.get_version(art["artifact_id"], 1)
    assert version["size"] == len(b"hello artifact")
    assert version["sha256"] == hashlib.sha256(b"hello artifact").hexdigest()
    assert version["mime_type"] == "text/plain"
    produced = version["produced_by"]
    assert produced["tool"] == "code_executor" and produced["action"] == "run_code"

    # Bytes are actually in storage at the server-derived key, and match.
    storage_path = version["storage_path"]
    assert storage_path.startswith("inputs/user-e2e/artifacts/")
    assert art["artifact_id"] in storage_path
    assert storage.get_file(storage_path).read() == b"hello artifact"


def test_run_code_input_artifact_roundtrip(wired_tool):
    tool, conversation_id, pg_engine, storage = wired_tool

    # Seed an input artifact (row + bytes) scoped to this conversation.
    seed_bytes = b"seed-value-123"
    artifact_id = _seed_artifact(pg_engine, storage, conversation_id, "seed.txt", seed_bytes)

    code = (
        "data = open('inputs/seed.txt', 'rb').read()\n"
        "open('echo.txt', 'wb').write(data + b'-processed')\n"
        "print('read', len(data), 'bytes')\n"
    )
    payload = tool.execute_action("run_code", code=code, inputs=[artifact_id], ttl=120)

    assert payload["status"] == "ok", payload
    assert "read 14 bytes" in payload["stdout_tail"]
    assert payload["inputs_loaded"] == ["inputs/seed.txt"]
    assert len(payload["artifacts"]) == 1
    out = payload["artifacts"][0]
    assert out["filename"] == "echo.txt"
    assert out["size"] == len(seed_bytes + b"-processed")

    with pg_engine.connect() as conn:
        version = ArtifactsRepository(conn).get_version(out["artifact_id"], 1)
    assert storage.get_file(version["storage_path"]).read() == seed_bytes + b"-processed"


def test_run_code_input_artifact_cross_tenant_blocked(wired_tool):
    tool, conversation_id, pg_engine, storage = wired_tool

    # An artifact that belongs to a DIFFERENT conversation must not be reachable.
    other_conversation = str(uuid.uuid4())
    foreign_id = _seed_artifact(pg_engine, storage, other_conversation, "secret.txt", b"top-secret")

    payload = tool.execute_action(
        "run_code", code="open('x.txt','w').write('x')", inputs=[foreign_id], ttl=60
    )
    assert payload["status"] == "error"
    assert "not found in this conversation/run" in payload["error"]


def test_run_code_captures_overwritten_file(wired_tool):
    tool, conversation_id, pg_engine, storage = wired_tool

    first = tool.execute_action(
        "run_code", code="open('out.txt','w').write('first-content')", ttl=120
    )
    assert first["status"] == "ok", first
    assert len(first["artifacts"]) == 1
    first_id = first["artifacts"][0]["artifact_id"]

    # The same persisted session overwrites out.txt with new content; the diff
    # is content-aware, so the new bytes must be captured as a fresh artifact
    # rather than dropped as an "already-seen path".
    second = tool.execute_action(
        "run_code", code="open('out.txt','w').write('second-content-longer')", ttl=120
    )
    assert second["status"] == "ok", second
    assert len(second["artifacts"]) == 1
    second_art = second["artifacts"][0]
    assert second_art["artifact_id"] != first_id
    assert second_art["filename"] == "out.txt"
    assert second_art["size"] == len(b"second-content-longer")

    with pg_engine.connect() as conn:
        version = ArtifactsRepository(conn).get_version(second_art["artifact_id"], 1)
    assert storage.get_file(version["storage_path"]).read() == b"second-content-longer"


def test_run_code_skips_unchanged_file_on_rerun(wired_tool):
    tool, _conversation_id, _pg_engine, _storage = wired_tool

    first = tool.execute_action(
        "run_code", code="open('keep.txt','w').write('same')", ttl=120
    )
    assert len(first["artifacts"]) == 1

    # A re-run that leaves keep.txt untouched must not re-persist it.
    second = tool.execute_action("run_code", code="print('noop')", ttl=120)
    assert second["status"] == "ok", second
    assert second["artifacts"] == []


def test_run_code_timeout_returns_clean_error(wired_tool):
    tool, _conversation_id, _pg_engine, _storage = wired_tool

    payload = tool.execute_action("run_code", code="import time; time.sleep(10)", timeout=1)
    assert payload["status"] == "error"
    # A clean structured error, not a hang: the sandbox interrupted the kernel.
    assert "TimeoutError" in payload["error"]
    assert payload["artifacts"] == []


def _seed_artifact(pg_engine, storage, conversation_id, filename, data) -> str:
    """Create an artifact row + version + stored bytes, returning its id."""
    sha256 = hashlib.sha256(data).hexdigest()
    with pg_engine.begin() as conn:
        repo = ArtifactsRepository(conn)
        artifact = repo.create_artifact(
            "user-e2e",
            "file",
            conversation_id=conversation_id,
            title=filename,
            mime_type="text/plain",
            filename=filename,
            storage_path=None,
            size=len(data),
            sha256=sha256,
        )
        artifact_id = str(artifact["id"])
        storage_path = f"inputs/user-e2e/artifacts/{artifact_id}/v1/{filename}"
        storage.save_file(io.BytesIO(data), storage_path)
        conn.execute(
            text(
                "UPDATE artifact_versions SET storage_path = :p "
                "WHERE artifact_id = CAST(:aid AS uuid) AND version = 1"
            ),
            {"p": storage_path, "aid": artifact_id},
        )
    return artifact_id
