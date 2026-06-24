"""End-to-end workflow ``code`` node: live Jupyter gateway + live Postgres + local storage.

Launches a real ``jupyter kernelgateway``, wires the sandbox manager + a temp-dir
``LocalStorage`` + the integration Postgres engine, and drives a ``WorkflowEngine``
through a ``code`` node: the node writes a file -> an artifact REFERENCE lands in
``state`` (artifact row persisted, run-scoped; the ref is ``{artifact_id,...}`` with
NO bytes); the ref survives the ``workflow_runs`` state-snapshot serialization; a
downstream node re-reads it by reference; the ``artifacts.*`` namespace and CEL both
resolve its metadata.

Skips gracefully when the gateway binary / websocket-client / POSTGRES_URI is absent.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
import uuid
from types import SimpleNamespace

import pytest

requests = pytest.importorskip("requests")
pytest.importorskip("websocket")  # websocket-client

from application.agents.workflow_agent import WorkflowAgent  # noqa: E402
from application.agents.workflows.cel_evaluator import evaluate_cel  # noqa: E402
from application.agents.workflows.schemas import (  # noqa: E402
    NodeType,
    Workflow,
    WorkflowGraph,
    WorkflowNode,
)
from application.agents.workflows.workflow_engine import WorkflowEngine  # noqa: E402
from application.sandbox.jupyter_gateway import JupyterKernelGatewaySandbox  # noqa: E402
from application.sandbox.manager import SandboxManager  # noqa: E402
from application.sandbox.sandbox_creator import SandboxCreator  # noqa: E402
from application.storage.db.repositories.artifacts import ArtifactsRepository  # noqa: E402
from application.storage.local import LocalStorage  # noqa: E402
from application.storage.storage_creator import StorageCreator  # noqa: E402
from application.templates.namespaces import NamespaceManager  # noqa: E402

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
def wired(gateway_url, pg_engine, tmp_path, monkeypatch):
    """Sandbox manager + temp local storage + integration PG, with a fresh run id."""
    backend = JupyterKernelGatewaySandbox(gateway_url=gateway_url, default_timeout=30.0)
    SandboxCreator._instance = SandboxManager(backend=backend, max_ttl=1200.0)

    storage = LocalStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(StorageCreator, "_instance", storage, raising=False)
    monkeypatch.setattr("application.storage.db.session.get_engine", lambda: pg_engine)

    run_id = str(uuid.uuid4())
    try:
        yield run_id, pg_engine, storage
    finally:
        SandboxCreator.reset()


def _engine(run_id: str) -> WorkflowEngine:
    graph = WorkflowGraph(workflow=Workflow(name="Code Node E2E"), nodes=[], edges=[])
    agent = SimpleNamespace(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="k",
        chat_history=[],
        user="user-wf-e2e",
        decoded_token={"sub": "user-wf-e2e"},
        request_id="req-1",
        retrieved_docs=None,
    )
    return WorkflowEngine(graph, agent, workflow_run_id=run_id)


def _code_node(node_id, code, **config):
    cfg = {"code": code}
    cfg.update(config)
    return WorkflowNode(
        id=node_id, workflow_id="wf-e2e", type=NodeType.CODE, title="Code",
        position={"x": 0, "y": 0}, config=cfg,
    )


def test_code_node_persists_artifact_reference_in_state(wired):
    run_id, pg_engine, storage = wired
    engine = _engine(run_id)

    node = _code_node(
        "code_1",
        "with open('report.txt', 'w') as f:\n    f.write('compliance ok')\n",
        output_variable="report",
    )
    list(engine._execute_code_node(node))

    ref = engine.state["report"]
    # The state holds an artifact REFERENCE (JSON primitives), never bytes. The
    # short handle ``ref`` (A1) lets a later node address the artifact by position.
    assert set(ref) == {"artifact_id", "version", "filename", "mime_type", "size", "ref"}
    assert ref["filename"] == "report.txt"
    assert ref["mime_type"] == "text/plain"
    assert ref["size"] == len(b"compliance ok")
    assert ref["ref"] == "A1"
    assert all(not isinstance(v, (bytes, bytearray)) for v in ref.values())
    assert engine.state["node_code_1_output"] == ref

    # The artifact row is persisted, parent-scoped to THIS run (not cross-tenant).
    with pg_engine.connect() as conn:
        repo = ArtifactsRepository(conn)
        artifact = repo.get_artifact_in_parent(ref["artifact_id"], workflow_run_id=run_id)
        assert artifact is not None
        assert repo.get_artifact_in_parent(ref["artifact_id"], workflow_run_id=str(uuid.uuid4())) is None
        version = repo.get_version(ref["artifact_id"], 1)
    assert version["size"] == len(b"compliance ok")
    assert version["produced_by"]["node_id"] == "code_1"
    # The bytes live in storage, never in state.
    assert storage.get_file(version["storage_path"]).read() == b"compliance ok"


def test_reference_survives_serialization_and_cel_branches(wired):
    run_id, _pg_engine, _storage = wired
    engine = _engine(run_id)

    node = _code_node(
        "code_meta",
        "open('out.json', 'w').write('{\"k\": 1}')\n",
        output_variable="report",
    )
    list(engine._execute_code_node(node))
    ref = engine.state["report"]

    # Survives the workflow_runs state-snapshot serialization unchanged.
    agent = WorkflowAgent.__new__(WorkflowAgent)
    serialized = agent._serialize_state(engine.state)
    assert serialized["report"] == ref
    assert isinstance(serialized["report"], dict)

    # CEL branches on the reference's metadata (nested-dict indexing).
    assert evaluate_cel("report.size > 0", engine.state) is True
    assert evaluate_cel('report.mime_type == "application/json"', engine.state) is True
    assert evaluate_cel('report.mime_type == "application/pdf"', engine.state) is False


def test_condition_node_branches_on_artifact_metadata(wired):
    run_id, _pg_engine, _storage = wired
    engine = _engine(run_id)

    list(engine._execute_code_node(
        _code_node("code_c", "open('r.json','w').write('{}')", output_variable="report")
    ))

    cond = WorkflowNode(
        id="cond_1", workflow_id="wf-e2e", type=NodeType.CONDITION, title="Branch",
        position={"x": 0, "y": 0},
        config={
            "mode": "simple",
            "cases": [
                {"name": "has json", "expression": 'report.mime_type == "application/json"',
                 "sourceHandle": "json_case"},
            ],
        },
    )
    list(engine._execute_condition_node(cond))
    assert engine._condition_result == "json_case"


def test_downstream_node_reads_reference_via_inputs(wired):
    run_id, _pg_engine, _storage = wired
    engine = _engine(run_id)

    list(engine._execute_code_node(
        _code_node("producer", "open('seed.txt','w').write('seed-bytes')", output_variable="seed")
    ))

    # A downstream code node references the upstream ref by its state-var name;
    # the engine re-fetches the bytes by id and stages them into the workspace.
    consumer = _code_node(
        "consumer",
        "data = open('inputs/seed.txt', 'rb').read()\n"
        "open('combined.txt', 'wb').write(data + b'-processed')\n",
        inputs=["seed"],
        output_variable="combined",
    )
    list(engine._execute_code_node(consumer))

    out = engine.state["combined"]
    assert out["filename"] == "combined.txt"
    assert out["size"] == len(b"seed-bytes-processed")
    assert out["artifact_id"] != engine.state["seed"]["artifact_id"]


def test_artifacts_namespace_resolves_reference(wired):
    run_id, _pg_engine, _storage = wired
    engine = _engine(run_id)

    list(engine._execute_code_node(
        _code_node("ns_node", "open('deck.txt','w').write('hello')", output_variable="report")
    ))
    ref = engine.state["report"]

    # The artifacts.* namespace (shared with the prompt renderer) exposes the
    # reference's metadata by output-variable name, and artifact(id) resolves
    # parent-scoped metadata — never bytes.
    ctx = NamespaceManager().build_context(
        artifacts_data={"report": ref},
        artifact_parent={"workflow_run_id": run_id},
    )
    assert ctx["artifacts"]["report"]["id"] == ref["artifact_id"]
    assert ctx["artifacts"]["report"]["mime_type"] == "text/plain"
    assert ctx["artifacts"]["report"]["filename"] == "deck.txt"

    looked_up = ctx["artifacts"]["artifact"](ref["artifact_id"])
    assert looked_up["id"] == ref["artifact_id"]
    assert looked_up["filename"] == "deck.txt"
    assert all(not isinstance(v, (bytes, bytearray)) for v in looked_up.values())

    # A foreign run id never resolves this artifact (no cross-tenant leak).
    foreign = NamespaceManager().build_context(
        artifact_parent={"workflow_run_id": str(uuid.uuid4())},
    )
    assert foreign["artifacts"]["artifact"](ref["artifact_id"]) == {}
