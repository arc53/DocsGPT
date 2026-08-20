"""Tests for the GraphRAG extraction pipeline (D28).

The LLM and the embeddings model are mocked in every test so the suite makes no
real model or network calls. A live ``GraphStore`` is exercised against the
ephemeral pytest-postgresql cluster (never the operator's dev DB) with a unique
temp ``source_id``; if pgvector is unavailable there the live tests skip.
"""

from __future__ import annotations

import json
import uuid

import pytest

import application.graphrag.extraction as extraction_module
from application.graphrag.store import GraphStore
from application.storage.db.source_config import SourceConfig
from application.vectorstore import pgconn

extract_graph_for_source = extraction_module.extract_graph_for_source

TEST_EMBEDDING_DIM = 8


@pytest.fixture(autouse=True)
def _close_pools():
    """Never leak a pool into another test; an ephemeral DSN dies with its DB."""
    yield
    for dsn, pool in list(pgconn._POOLS.items()):
        try:
            pool.close()
        except Exception:
            pass
        pgconn._POOLS.pop(dsn, None)


def _ephemeral_dsn(info) -> str:
    """libpq DSN for the ephemeral pytest-postgresql database."""
    password = f":{info.password}" if info.password else ""
    return (
        f"postgresql://{info.user}{password}@{info.host}:{info.port}/{info.dbname}"
    )


def _live_store(monkeypatch, info):
    """Graph store on a fresh ephemeral database, schema created up front.

    Construction runs no DDL any more (boot owns the schema), so the tables are
    created explicitly here — what ``ensure_vector_schema`` does in production.
    """
    monkeypatch.setattr(
        GraphStore, "_embedding_dim", lambda self: TEST_EMBEDDING_DIM
    )
    dsn = _ephemeral_dsn(info)
    # The pipeline builds its own GraphStore() from settings, so point those at
    # the ephemeral cluster too — never at the operator's configured DB.
    from application.core import settings as settings_module

    monkeypatch.setattr(
        settings_module.settings, "PGVECTOR_CONNECTION_STRING", dsn, raising=False
    )
    store = GraphStore(connection_string=dsn)
    try:
        store._ensure_tables()
    except Exception as exc:
        pytest.skip(f"pgvector extension unavailable: {exc}")
    return store


class _StubLLM:
    """Stub LLM whose ``.gen`` returns crafted responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.model_id = "stub-model"
        self.gen_calls = []
        self._token_usage_source = None
        self._request_id = None

    def gen(self, model=None, messages=None, **kwargs):
        self.gen_calls.append({"model": model, "messages": messages})
        if not self._responses:
            raise AssertionError("gen called more times than crafted responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _StubEmbedding:
    """Stub embeddings model producing deterministic fixed-dim vectors."""

    def __init__(self):
        self.dimension = TEST_EMBEDDING_DIM

    def embed_documents(self, documents):
        return [
            [float(len(d) % 7)] + [0.0] * (TEST_EMBEDDING_DIM - 1)
            for d in documents
        ]


@pytest.fixture
def stub_embedding(monkeypatch):
    from application.core.settings import settings

    # The resolver short-circuits to the remote API when this is configured,
    # which would bypass the stub on a dev machine that sets it.
    monkeypatch.setattr(settings, "EMBEDDINGS_BASE_URL", None)
    embedding = _StubEmbedding()
    monkeypatch.setattr(
        extraction_module.EmbeddingsSingleton,
        "get_instance",
        staticmethod(lambda *a, **k: embedding),
    )
    return embedding


def _install_stub_llm(monkeypatch, llm):
    captured = {}

    def _create(*args, **kwargs):
        captured["model_id"] = kwargs.get("model_id")
        return llm

    monkeypatch.setattr(
        extraction_module.LLMCreator, "create_llm", staticmethod(_create)
    )
    return captured


def _chunk(doc_id, text):
    return {"doc_id": doc_id, "text": text}


def _extraction_json(entities, relationships):
    return json.dumps({"entities": entities, "relationships": relationships})


@pytest.mark.integration
class TestExtractionLive:
    @pytest.fixture
    def store(self, monkeypatch, postgresql):
        store = _live_store(monkeypatch, postgresql.info)
        yield store
        store.close()

    @pytest.fixture
    def source_id(self):
        return str(uuid.uuid4())

    def test_entities_and_relationships_written(
        self, store, source_id, monkeypatch, stub_embedding
    ):
        try:
            payload = _extraction_json(
                entities=[
                    {"name": "Ada Lovelace", "type": "person", "description": "A mathematician."},
                    {"name": "Analytical Engine", "type": "machine", "description": "Early computer."},
                ],
                relationships=[
                    {
                        "source": "Ada Lovelace",
                        "target": "Analytical Engine",
                        "type": "worked_on",
                        "description": "wrote algorithms for it",
                        "weight": 3.0,
                    }
                ],
            )
            llm = _StubLLM([payload])
            _install_stub_llm(monkeypatch, llm)

            summary = extract_graph_for_source(
                source_id,
                user="owner-1",
                chunks=[_chunk("c1", "Ada Lovelace worked on the Analytical Engine.")],
                config=SourceConfig(),
                request_id="req-1",
            )

            assert summary["nodes"] == 2
            assert summary["edges"] == 1
            assert summary["chunks_processed"] == 1
            assert summary["failed_chunks"] == 0
            assert store.count_nodes(source_id) == 2

            node = store.get_node_by_normalized(source_id, "ada lovelace")
            assert node is not None
            mapping = store.get_chunk_ids_for_nodes(source_id, [node["id"]])
            assert mapping[node["id"]] == ["c1"]
        finally:
            store.delete_by_source(source_id)

    def test_same_entity_across_chunks_merges(
        self, store, source_id, monkeypatch, stub_embedding
    ):
        try:
            payload_a = _extraction_json(
                entities=[{"name": "Ada", "type": "person", "description": "first"}],
                relationships=[],
            )
            payload_b = _extraction_json(
                entities=[{"name": "Ada", "type": "person", "description": "second"}],
                relationships=[],
            )
            llm = _StubLLM([payload_a, payload_b])
            _install_stub_llm(monkeypatch, llm)

            summary = extract_graph_for_source(
                source_id,
                user="owner-1",
                chunks=[_chunk("c1", "Ada one."), _chunk("c2", "Ada two.")],
                config=SourceConfig(),
                request_id="req-1",
            )

            assert summary["chunks_processed"] == 2
            assert store.count_nodes(source_id) == 1
            node = store.get_node_by_normalized(source_id, "ada")
            assert node["doc_freq"] == 2
            assert "first" in node["description"]
            assert "second" in node["description"]
        finally:
            store.delete_by_source(source_id)

    def test_checkpoint_skips_done_chunks(
        self, store, source_id, monkeypatch, stub_embedding
    ):
        try:
            payload = _extraction_json(
                entities=[{"name": "Ada", "type": "person", "description": "d"}],
                relationships=[],
            )
            first_llm = _StubLLM([payload])
            _install_stub_llm(monkeypatch, first_llm)
            extract_graph_for_source(
                source_id,
                user="owner-1",
                chunks=[_chunk("c1", "Ada.")],
                config=SourceConfig(),
                request_id="req-1",
            )
            assert len(first_llm.gen_calls) == 1

            second_llm = _StubLLM([])
            _install_stub_llm(monkeypatch, second_llm)
            summary = extract_graph_for_source(
                source_id,
                user="owner-1",
                chunks=[_chunk("c1", "Ada.")],
                config=SourceConfig(),
                request_id="req-2",
            )
            assert len(second_llm.gen_calls) == 0
            assert summary["chunks_processed"] == 0
        finally:
            store.delete_by_source(source_id)

    def test_cap_limits_processing(
        self, store, source_id, monkeypatch, stub_embedding
    ):
        try:
            payload = _extraction_json(
                entities=[{"name": "X", "type": "t", "description": "d"}],
                relationships=[],
            )
            llm = _StubLLM([payload, payload])
            _install_stub_llm(monkeypatch, llm)

            config = SourceConfig.model_validate({"graph": {"max_chunks": 2}})
            summary = extract_graph_for_source(
                source_id,
                user="owner-1",
                chunks=[_chunk(f"c{i}", f"text {i}") for i in range(5)],
                config=config,
                request_id="req-1",
            )

            assert len(llm.gen_calls) == 2
            assert summary["chunks_processed"] == 2
            assert summary["skipped_over_cap"] == 3
        finally:
            store.delete_by_source(source_id)

    def test_malformed_and_error_chunks_are_skipped(
        self, store, source_id, monkeypatch, stub_embedding
    ):
        try:
            good = _extraction_json(
                entities=[{"name": "Ada", "type": "person", "description": "d"}],
                relationships=[],
            )
            llm = _StubLLM([
                "not json at all",
                RuntimeError("model exploded"),
                good,
            ])
            _install_stub_llm(monkeypatch, llm)

            summary = extract_graph_for_source(
                source_id,
                user="owner-1",
                chunks=[
                    _chunk("c1", "garbage"),
                    _chunk("c2", "boom"),
                    _chunk("c3", "Ada."),
                ],
                config=SourceConfig(),
                request_id="req-1",
            )

            assert summary["failed_chunks"] == 2
            assert summary["chunks_processed"] == 1
            assert store.count_nodes(source_id) == 1
            progress = store.get_progress(source_id)
            assert progress["c1"] == "failed"
            assert progress["c2"] == "failed"
            assert progress["c3"] == "done"
        finally:
            store.delete_by_source(source_id)

    def test_exactly_one_gen_per_chunk(
        self, store, source_id, monkeypatch, stub_embedding
    ):
        try:
            payload = _extraction_json(
                entities=[{"name": "A", "type": "t", "description": "d"}],
                relationships=[],
            )
            llm = _StubLLM([payload, payload, payload])
            _install_stub_llm(monkeypatch, llm)

            extract_graph_for_source(
                source_id,
                user="owner-1",
                chunks=[_chunk(f"c{i}", f"text {i}") for i in range(3)],
                config=SourceConfig(),
                request_id="req-1",
            )
            assert len(llm.gen_calls) == 3
        finally:
            store.delete_by_source(source_id)


@pytest.mark.unit
class TestExtractionTokenUsage:
    def test_llm_tagged_for_token_usage(self, monkeypatch):
        llm = _StubLLM([])
        captured = _install_stub_llm(monkeypatch, llm)

        built = extraction_module._build_extraction_llm(
            "stub-model", user="owner-1", request_id="req-99"
        )

        assert built is llm
        assert built._token_usage_source == "graph_extraction"
        assert built._request_id == "req-99"
        assert captured["model_id"] == "stub-model"


@pytest.mark.unit
class TestModelResolution:
    def test_per_source_override_wins(self, monkeypatch):
        monkeypatch.setattr(
            extraction_module.settings, "GRAPHRAG_EXTRACTION_MODEL", "setting-model"
        )
        monkeypatch.setattr(extraction_module.settings, "LLM_NAME", "instance-model")
        config = SourceConfig.model_validate(
            {"graph": {"extraction_model": "override-model"}}
        )
        assert (
            extraction_module._resolve_extraction_model(config) == "override-model"
        )

    def test_setting_then_instance_default(self, monkeypatch):
        monkeypatch.setattr(
            extraction_module.settings, "GRAPHRAG_EXTRACTION_MODEL", "setting-model"
        )
        monkeypatch.setattr(extraction_module.settings, "LLM_NAME", "instance-model")
        assert (
            extraction_module._resolve_extraction_model(SourceConfig())
            == "setting-model"
        )

        monkeypatch.setattr(
            extraction_module.settings, "GRAPHRAG_EXTRACTION_MODEL", None
        )
        assert (
            extraction_module._resolve_extraction_model(SourceConfig())
            == "instance-model"
        )

    def test_max_chunks_resolution(self, monkeypatch):
        monkeypatch.setattr(
            extraction_module.settings,
            "GRAPHRAG_MAX_CHUNKS_FOR_EXTRACTION",
            2000,
        )
        assert extraction_module._resolve_max_chunks(SourceConfig()) == 2000
        config = SourceConfig.model_validate({"graph": {"max_chunks": 5}})
        assert extraction_module._resolve_max_chunks(config) == 5


@pytest.mark.unit
class TestParsing:
    def test_parses_embedded_json(self):
        raw = 'sure!\n{"entities": [{"name": "A"}], "relationships": []}\nthanks'
        parsed = extraction_module._parse_extraction(raw)
        assert parsed["entities"] == [{"name": "A"}]
        assert parsed["relationships"] == []

    def test_garbage_returns_none(self):
        assert extraction_module._parse_extraction("no json here") is None
        assert extraction_module._parse_extraction("{bad json}") is None
        assert extraction_module._parse_extraction(None) is None

    def test_missing_keys_default_empty(self):
        parsed = extraction_module._parse_extraction('{"foo": 1}')
        assert parsed == {"entities": [], "relationships": []}

    def test_chunk_id_prefers_doc_id(self):
        assert extraction_module._chunk_id({"doc_id": "7"}) == "7"
        assert extraction_module._chunk_id({"chunk_id": "abc"}) == "abc"
        assert extraction_module._chunk_id({"id": 9}) == "9"
        assert extraction_module._chunk_id({"text": "no id"}) is None


@pytest.mark.unit
class TestEmbeddingsResolution:
    def test_extraction_uses_shared_resolver(self, monkeypatch):
        """Extraction must resolve embeddings through ``get_embeddings``."""
        from unittest.mock import MagicMock

        fake_store = MagicMock()
        fake_store.pending_chunks.return_value = []
        monkeypatch.setattr(
            "application.graphrag.store.GraphStore", lambda *a, **k: fake_store
        )
        _install_stub_llm(monkeypatch, _StubLLM([]))

        calls = []
        fake_embedding = MagicMock()

        def _resolver(*args, **kwargs):
            calls.append((args, kwargs))
            return fake_embedding

        monkeypatch.setattr(extraction_module, "get_embeddings", _resolver)

        summary = extract_graph_for_source(
            str(uuid.uuid4()),
            user="owner-1",
            chunks=[],
            config=SourceConfig(),
            request_id="req-1",
        )

        assert calls == [((), {})]
        assert summary["chunks_processed"] == 0
