"""A graph build stopped by its payer's allowance leaves the rest of the source for the next build to pick up.

Every extraction call is checked against the payer's limits. Once the allowance is used up, the chunks not yet
extracted are refused before any model call and recorded ``failed``. ``failed`` is not ``done``: the checkpoint
lists those chunks as pending, so the next run over the source extracts exactly them and nothing it already has.
That next run is the graph sync a source sync queues (every chunk comes back under a new id; the graph is carried
over by content and only text it lacks is extracted), or the same build run again.

The checkpoint is the real ``GraphStore`` SQL on the ephemeral cluster. The graph tables need pgvector, which that
cluster lacks, so the writes that touch them keep only the checkpoint row; the LLM and the embeddings are stubbed.
"""

from __future__ import annotations

import json
import uuid

import pytest

import docsgpt.graphrag.extraction as extraction_module
from docsgpt.graphrag import store as store_module
from docsgpt.llm.llm_creator import LLMCreator
from docsgpt.quotas.agent_limits import AgentLimitExceeded
from docsgpt.quotas.payer import current_run_billing
from docsgpt.quotas.run_limits import RunLimitReached
from docsgpt.storage.db.source_config import SourceConfig
from docsgpt.vectorstore import pgconn
from tests.graphrag.test_extraction import _ScriptedLLM, _ephemeral_dsn, stub_embedding  # noqa: F401

pytestmark = pytest.mark.fresh_db

ALPHA = "Alpha is a storage engine."
BETA = "Beta replicates Alpha."
GAMMA = "Gamma schedules jobs."


def _payload(*names: str) -> str:
    return json.dumps({
        "entities": [{"name": name, "type": "thing", "description": f"{name} desc"} for name in names],
        "relationships": [],
    })


SCRIPT = {ALPHA: [_payload("Alpha")] * 3, BETA: [_payload("Beta")] * 3, GAMMA: [_payload("Gamma")] * 3}


def _chunks(**texts_by_id: str) -> list[dict]:
    return [{"doc_id": chunk_id, "text": text} for chunk_id, text in texts_by_id.items()]


class _CheckpointOnlyStore(store_module.GraphStore):
    """The real checkpoint reads and writes; the pgvector-backed graph writes keep only the checkpoint row."""

    def _ensure_tables_once(self) -> None:
        return None

    def apply_chunk(self, source_id, chunk_id, entities, relationships, name_embeddings,
                    content_hash=None, extraction_key=None):
        self.mark_chunk(source_id, chunk_id, "done", content_hash=content_hash, extraction_key=extraction_key)
        return len(entities), len(relationships)

    def _run(self, sql: str, params) -> None:
        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
        conn.commit()

    def remap_chunks(self, source_id, mapping):
        for old, new in mapping.items():
            self._run(
                "DELETE FROM graph_ingest_progress WHERE source_id = %s AND chunk_id = %s AND status <> 'done'",
                (source_id, str(new)),
            )
            self._run(
                "UPDATE graph_ingest_progress SET chunk_id = %s WHERE source_id = %s AND chunk_id = %s",
                (str(new), source_id, str(old)),
            )

    def delete_chunks(self, source_id, chunk_ids):
        self._run(
            "DELETE FROM graph_ingest_progress WHERE source_id = %s AND chunk_id = ANY(%s)",
            (source_id, [str(c) for c in chunk_ids]),
        )
        return {}

    def set_node_degrees(self, source_id):
        return None

    def count_nodes(self, source_id, strict=False):
        return 0


class _Allowance:
    """The payer's limits: ``calls`` model calls, then every call is refused, as ``RunLimits.check_call`` does."""

    def __init__(self, calls):
        self.left = calls

    def check_call(self) -> None:
        if self.left is None:
            return
        if self.left <= 0:
            raise RunLimitReached(AgentLimitExceeded(agent_id=None, dimension="tokens", usage=1, limit=1))
        self.left -= 1


class _MeteredLLM(_ScriptedLLM):
    """The scripted LLM, checking the run's limits before each call as ``BaseLLM`` does."""

    def gen(self, model=None, messages=None, **kwargs):
        billing = current_run_billing()
        if billing is not None and billing.limits is not None:
            billing.limits.check_call()
        return super().gen(model=model, messages=messages, **kwargs)


@pytest.fixture(autouse=True)
def _close_pools():
    yield
    for dsn, pool in list(pgconn._POOLS.items()):
        try:
            pool.close()
        except Exception:
            pass
        pgconn._POOLS.pop(dsn, None)


@pytest.fixture
def store(monkeypatch, postgresql):
    from docsgpt.core.settings import settings

    with postgresql.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS graph_ingest_progress (source_id UUID NOT NULL, chunk_id TEXT NOT NULL, "
            "status TEXT, content_hash TEXT, extraction_key TEXT, PRIMARY KEY (source_id, chunk_id))"
        )
    postgresql.commit()
    dsn = _ephemeral_dsn(postgresql.info)
    monkeypatch.setattr(settings, "PGVECTOR_CONNECTION_STRING", dsn, raising=False)
    monkeypatch.setattr(settings, "GRAPHRAG_EXTRACTION_WORKERS", 1, raising=False)
    monkeypatch.setattr(store_module, "GraphStore", _CheckpointOnlyStore)
    monkeypatch.setattr(extraction_module, "get_task_model_id", lambda user: "task-model")
    graph = _CheckpointOnlyStore(connection_string=dsn)
    yield graph
    graph.close()


@pytest.fixture
def llm(monkeypatch):
    scripted = _MeteredLLM(SCRIPT)
    monkeypatch.setattr(LLMCreator, "create_llm", staticmethod(lambda *a, **k: scripted))
    return scripted


@pytest.fixture
def allowance(monkeypatch):
    """The allowance the next build starts with: a number of calls, or None for no limit."""
    state = {"calls": None}
    monkeypatch.setattr(
        extraction_module.RunLimits, "start", classmethod(lambda cls, payer, **kw: _Allowance(state["calls"])),
    )
    return state


def _build(source_id, chunks, **kwargs):
    return extraction_module.extract_graph_for_source(
        source_id, "owner-1", chunks, config=SourceConfig(), payer="payer-1", **kwargs,
    )


def _stopped_after_one(store, llm, allowance, source_id):
    allowance["calls"] = 1
    summary = _build(source_id, _chunks(a1=ALPHA, b1=BETA, c1=GAMMA))
    assert summary["chunks_processed"] == 1 and summary["failed_chunks"] == 2
    # The refused chunks never reached the provider, and the checkpoint lists them as still to extract.
    assert llm.calls == [ALPHA]
    assert store.get_progress(source_id) == {"a1": "done", "b1": "failed", "c1": "failed"}
    assert store.pending_chunks(source_id, ["a1", "b1", "c1"]) == ["b1", "c1"]
    llm.calls.clear()


def test_the_graph_sync_after_a_source_sync_extracts_what_the_stop_left(store, llm, allowance, stub_embedding):  # noqa: F811
    source_id = str(uuid.uuid4())
    _stopped_after_one(store, llm, allowance, source_id)

    # The allowance is back and the source syncs: every chunk comes back under a new id.
    allowance["calls"] = None
    chunks = _chunks(a2=ALPHA, b2=BETA, c2=GAMMA)
    to_extract = extraction_module.sync_graph_to_chunks(source_id, chunks, config=SourceConfig())
    summary = _build(source_id, chunks, chunk_ids=to_extract)

    assert sorted(to_extract) == ["b2", "c2"]
    assert sorted(llm.calls) == [BETA, GAMMA]
    assert summary["failed_chunks"] == 0
    assert store.get_progress(source_id) == {"a2": "done", "b2": "done", "c2": "done"}


def test_running_the_build_again_extracts_only_what_the_stop_left(store, llm, allowance, stub_embedding):  # noqa: F811
    source_id = str(uuid.uuid4())
    _stopped_after_one(store, llm, allowance, source_id)

    allowance["calls"] = None
    summary = _build(source_id, _chunks(a1=ALPHA, b1=BETA, c1=GAMMA))

    assert sorted(llm.calls) == [BETA, GAMMA]
    assert summary["chunks_processed"] == 2 and summary["failed_chunks"] == 0
    assert store.pending_chunks(source_id, ["a1", "b1", "c1"]) == []
