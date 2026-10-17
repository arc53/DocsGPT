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

import docsgpt.graphrag.extraction as extraction_module
from docsgpt.graphrag.store import GraphStore
from docsgpt.storage.db.source_config import SourceConfig
from docsgpt.vectorstore import pgconn

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
    from docsgpt.core import settings as settings_module

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


class _ScriptedLLM:
    """Stub LLM answering per chunk, so results do not depend on call order.

    The extraction pool runs calls concurrently, so a stub that hands out
    responses in call order gives each chunk whichever response its thread
    happened to grab first. ``script`` maps a chunk's text to the responses
    for that chunk, consumed one per call.
    """

    def __init__(self, script):
        self._script = {text: list(responses) for text, responses in script.items()}
        self.model_id = "stub-model"
        self.calls = []
        self._token_usage_source = None
        self._request_id = None

    def gen(self, model=None, messages=None, **kwargs):
        text = messages[-1]["content"].removeprefix("<chunk>\n").removesuffix("\n</chunk>")
        self.calls.append(text)
        responses = self._script.get(text)
        if not responses:
            raise AssertionError(f"unexpected extraction call for {text!r}")
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def calls_for(self, text):
        return self.calls.count(text)


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
    from docsgpt.core.settings import settings

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


class TestFactText:
    """A relationship rendered as the sentence it asserts.

    This is what fact seeding matches a question against, so it has to read as
    a claim rather than as three fields concatenated.
    """

    def test_renders_the_relationship_as_a_sentence(self):
        text = extraction_module._fact_text(
            {
                "source": "Alder",
                "target": "Quill",
                "type": "streams_to",
                "description": "Alder streams audit events to Quill.",
            }
        )

        assert text == "Alder streams_to Quill: Alder streams audit events to Quill."

    def test_omits_an_absent_description(self):
        text = extraction_module._fact_text(
            {"source": "Alder", "target": "Quill", "type": "streams_to"}
        )

        assert text == "Alder streams_to Quill"

    def test_defaults_a_missing_relation(self):
        text = extraction_module._fact_text({"source": "Alder", "target": "Quill"})

        assert text == "Alder related to Quill"

    @pytest.mark.parametrize(
        "rel",
        [
            {"source": "Alder", "target": ""},
            {"source": "", "target": "Quill"},
            {},
        ],
    )
    def test_an_edge_without_both_endpoints_has_no_fact(self, rel):
        assert extraction_module._fact_text(rel) == ""


class TestEmbedFacts:
    """Fact embeddings are always recorded, so a source can switch to
    relationship seeding at query time without being rebuilt."""

    def _relationships(self):
        return [{"source": "Alder", "target": "Quill", "type": "streams_to"}]

    def test_attaches_one_embedding_per_fact_in_a_single_call(self):
        relationships = self._relationships() + [{"source": "", "target": "Nowhere"}]
        calls = []

        class _Embedding:
            def embed_documents(self, texts):
                calls.append(texts)
                return [[0.5] * 4 for _ in texts]

        extraction_module._embed_facts(_Embedding(), relationships)

        # One batched call, and the endpoint-less relationship is skipped
        # rather than embedded as an empty string.
        assert calls == [["Alder streams_to Quill"]]
        assert relationships[0]["fact_embedding"] == [0.5] * 4
        assert "fact_embedding" not in relationships[1]

    def test_survives_an_embedding_failure(self):
        """The graph is still correct without fact embeddings — only
        relationship seeding degrades, and it falls back to entities — so a
        failure here must not fail the chunk."""
        relationships = self._relationships()

        class _Embedding:
            def embed_documents(self, texts):
                raise RuntimeError("embeddings down")

        extraction_module._embed_facts(_Embedding(), relationships)

        assert "fact_embedding" not in relationships[0]


class TestSeedText:
    """What a node's embedding is computed from.

    Retrieval matches a whole question against these embeddings, so what goes
    into them decides what the graph walk can start from.
    """

    def _entity(self):
        return {
            "name": "Quill",
            "normalized_name": "quill",
            "type": "store",
            "description": "A write-ahead store.",
        }

    def test_includes_type_and_description(self):
        assert (
            extraction_module._seed_text(self._entity())
            == "Quill (store): A write-ahead store."
        )

    def test_falls_back_to_the_name_when_fields_are_missing(self):
        assert extraction_module._seed_text({"name": "Quill"}) == "Quill"

    def test_embedded_text_is_keyed_by_the_normalized_name(self):
        """The richer text must reach ``embed_documents``, keyed by the same
        normalized name the store resolves nodes by — otherwise the embedding
        is computed for a node it never reaches."""
        captured = {}

        class _Embedding:
            def embed_documents(self, texts):
                captured["texts"] = texts
                return [[0.0] * 4 for _ in texts]

        result = extraction_module._embed_names(_Embedding(), [self._entity()], [])

        assert captured["texts"] == ["Quill (store): A write-ahead store."]
        assert set(result) == {"quill"}


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

    def test_parallel_workers_process_every_chunk_once(
        self, store, source_id, monkeypatch, stub_embedding
    ):
        """Running the model calls concurrently must not change what gets written.

        Extraction spends nearly all of a chunk's time waiting on the model, so
        the calls run in a pool while every graph write stays on the calling
        thread. Six chunks share one entity here: whatever order the pool
        finishes in, that entity is upserted once, each chunk is linked, and all
        six are marked processed.
        """
        from docsgpt.core.settings import settings

        try:
            payload = _extraction_json(
                entities=[{"name": "Ada", "type": "person", "description": "d"}],
                relationships=[],
            )
            llm = _StubLLM([payload] * 6)
            _install_stub_llm(monkeypatch, llm)
            monkeypatch.setattr(settings, "GRAPHRAG_EXTRACTION_WORKERS", 4)

            summary = extract_graph_for_source(
                source_id,
                user="owner-1",
                chunks=[
                    _chunk(f"c{i}", f"Ada appears here, take {i}.") for i in range(6)
                ],
                config=SourceConfig(),
                request_id="req-parallel",
            )

            assert summary["chunks_processed"] == 6
            assert summary["failed_chunks"] == 0
            assert summary["nodes"] == 1
            assert len(llm.gen_calls) == 6

            node = store.get_node_by_normalized(source_id, "ada")
            assert node is not None
            mapping = store.get_chunk_ids_for_nodes(source_id, [node["id"]])
            assert sorted(mapping[node["id"]]) == [f"c{i}" for i in range(6)]
        finally:
            store.delete_by_source(source_id)

    def test_embedding_runs_on_the_calling_thread(
        self, store, source_id, monkeypatch, stub_embedding
    ):
        """Only the LLM call may run in the extraction pool, never embedding.

        Embedding from the pool is what broke every graph build inside a
        worker: the embeddings client used to decide "embed locally" from the
        task on the *current thread's* stack, so a pool thread dispatched to
        the worker instead and Celery refused the wait. ``in_worker`` is
        process-wide now, but the pool still has no reason to touch the
        embeddings client — it exists to overlap model latency.
        """
        import threading

        from docsgpt.core.settings import settings

        caller = threading.current_thread()
        seen = []
        real_embed_names = extraction_module._embed_names

        def _recording_embed_names(*args, **kwargs):
            seen.append(threading.current_thread())
            return real_embed_names(*args, **kwargs)

        monkeypatch.setattr(extraction_module, "_embed_names", _recording_embed_names)
        try:
            payload = _extraction_json(
                entities=[{"name": "Ada", "type": "person", "description": "d"}],
                relationships=[],
            )
            _install_stub_llm(monkeypatch, _StubLLM([payload] * 4))
            monkeypatch.setattr(settings, "GRAPHRAG_EXTRACTION_WORKERS", 4)

            summary = extract_graph_for_source(
                source_id,
                user="owner-1",
                chunks=[_chunk(f"c{i}", f"Ada, take {i}.") for i in range(4)],
                config=SourceConfig(),
                request_id="req-thread",
            )

            assert summary["failed_chunks"] == 0
            assert len(seen) == 4
            assert all(thread is caller for thread in seen)
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
            # Each failing chunk fails its retry too; one that recovers on
            # retry is covered in ``TestFailedChunksAreRetried``.
            llm = _ScriptedLLM({
                "garbage": ["not json at all", "still not json"],
                "boom": [RuntimeError("model exploded"), RuntimeError("model exploded again")],
                "Ada.": [good],
            })
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

    def test_concurrent_extraction_calls_never_share_an_llm(self, monkeypatch, stub_embedding):
        """Provider usage is recorded on the LLM instance (``_last_usage``) and
        claimed by whichever call finishes next, so two calls in flight on one
        instance can bill each other's tokens. Each extraction thread needs its
        own instance."""
        import threading
        import time
        from unittest.mock import MagicMock

        from docsgpt.core.settings import settings

        payload = _extraction_json(
            entities=[{"name": "Ada", "type": "person", "description": "d"}],
            relationships=[],
        )

        class _ThreadRecordingLLM:
            model_id = "stub-model"

            def __init__(self):
                self.threads = set()

            def gen(self, model=None, messages=None, **kwargs):
                self.threads.add(threading.get_ident())
                time.sleep(0.01)  # keep calls overlapping
                return payload

        built = []

        def _create(*args, **kwargs):
            llm = _ThreadRecordingLLM()
            built.append(llm)
            return llm

        monkeypatch.setattr(extraction_module.LLMCreator, "create_llm", staticmethod(_create))
        monkeypatch.setattr(settings, "GRAPHRAG_EXTRACTION_WORKERS", 4)
        store = MagicMock(name="GraphStore")
        store.pending_chunks.return_value = [f"c{i}" for i in range(8)]
        store.apply_chunk.return_value = (1, 0)
        store.count_nodes.return_value = 1
        monkeypatch.setattr("docsgpt.graphrag.store.GraphStore", lambda *a, **k: store)

        summary = extract_graph_for_source(
            str(uuid.uuid4()),
            user="owner-1",
            chunks=[_chunk(f"c{i}", f"Ada, take {i}.") for i in range(8)],
            config=SourceConfig(),
            request_id="req-threads",
        )

        assert summary["chunks_processed"] == 8
        used = [llm for llm in built if llm.threads]
        assert len(used) > 1, "calls did not run concurrently"
        assert all(len(llm.threads) == 1 for llm in used)


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
class TestExtractionProviderResolution:
    """The extraction model decides the provider, not ``LLM_PROVIDER``.

    ``settings.LLM_PROVIDER`` is the deployment default (``docsgpt`` out of the
    box, i.e. the hosted public endpoint). Dispatching the resolved extraction
    model through it sends the call to a provider that never serves that model:
    the request is rejected, the shared fallback answers instead, and the graph
    is quietly built by a different model than the one configured.
    """

    def _capture_create_llm(self, monkeypatch, llm=None):
        captured = {}

        def _create(provider, *args, **kwargs):
            captured["provider"] = provider
            captured["args"] = args
            captured["kwargs"] = kwargs
            return llm or _StubLLM([])

        monkeypatch.setattr(
            extraction_module.LLMCreator, "create_llm", staticmethod(_create)
        )
        return captured

    def test_provider_comes_from_the_model_registry(self, monkeypatch):
        monkeypatch.setattr(extraction_module.settings, "LLM_PROVIDER", "docsgpt")
        monkeypatch.setattr(
            extraction_module, "get_provider_from_model_id", lambda *a, **k: "openai"
        )
        monkeypatch.setattr(
            extraction_module, "get_api_key_for_provider", lambda provider: "sk-openai"
        )
        captured = self._capture_create_llm(monkeypatch)

        extraction_module._build_extraction_llm("gpt-4o-mini", "owner-1", "req-1")

        assert captured["provider"] == "openai"
        assert captured["kwargs"]["api_key"] == "sk-openai"
        assert captured["kwargs"]["model_id"] == "gpt-4o-mini"

    def test_owner_scopes_the_registry_lookup(self, monkeypatch):
        """A per-user (BYOM) model only resolves when the owner is passed."""
        seen = {}

        def _resolve(model_id, user_id=None):
            seen["model_id"] = model_id
            seen["user_id"] = user_id
            return "anthropic"

        monkeypatch.setattr(
            extraction_module, "get_provider_from_model_id", _resolve
        )
        monkeypatch.setattr(
            extraction_module, "get_api_key_for_provider", lambda provider: "k"
        )
        self._capture_create_llm(monkeypatch)

        extraction_module._build_extraction_llm("byom-uuid", "owner-7", "req-1")

        assert seen == {"model_id": "byom-uuid", "user_id": "owner-7"}

    def test_unknown_model_falls_back_to_the_configured_provider(self, monkeypatch):
        monkeypatch.setattr(extraction_module.settings, "LLM_PROVIDER", "docsgpt")
        monkeypatch.setattr(
            extraction_module, "get_provider_from_model_id", lambda *a, **k: None
        )
        monkeypatch.setattr(
            extraction_module, "get_api_key_for_provider", lambda provider: "fallback-key"
        )
        captured = self._capture_create_llm(monkeypatch)

        extraction_module._build_extraction_llm("mystery-model", "owner-1", "req-1")

        assert captured["provider"] == "docsgpt"
        assert captured["kwargs"]["api_key"] == "fallback-key"

    def test_no_model_id_skips_the_lookup(self, monkeypatch):
        monkeypatch.setattr(extraction_module.settings, "LLM_PROVIDER", "openai")
        calls = []
        monkeypatch.setattr(
            extraction_module,
            "get_provider_from_model_id",
            lambda *a, **k: calls.append(a) or "anthropic",
        )
        monkeypatch.setattr(
            extraction_module, "get_api_key_for_provider", lambda provider: "k"
        )
        captured = self._capture_create_llm(monkeypatch)

        extraction_module._build_extraction_llm(None, "owner-1", "req-1")

        assert calls == []
        assert captured["provider"] == "openai"

    def test_api_key_follows_the_resolved_provider(self, monkeypatch):
        """The key must match the provider actually dispatched to."""
        monkeypatch.setattr(extraction_module.settings, "LLM_PROVIDER", "docsgpt")
        monkeypatch.setattr(extraction_module.settings, "API_KEY", "generic-key")
        monkeypatch.setattr(
            extraction_module, "get_provider_from_model_id", lambda *a, **k: "anthropic"
        )
        keyed_for = {}

        def _key(provider):
            keyed_for["provider"] = provider
            return "sk-anthropic"

        monkeypatch.setattr(extraction_module, "get_api_key_for_provider", _key)
        captured = self._capture_create_llm(monkeypatch)

        extraction_module._build_extraction_llm("claude-x", "owner-1", "req-1")

        assert keyed_for["provider"] == "anthropic"
        assert captured["kwargs"]["api_key"] == "sk-anthropic"
        assert captured["kwargs"]["api_key"] != "generic-key"


@pytest.mark.unit
class TestFailedChunksAreReported:
    """Every dropped chunk has to leave a trace.

    A chunk whose extraction cannot be parsed is marked ``failed`` and skipped.
    That path logged nothing at all, so a graph could come back short with the
    summary's ``failed_chunks`` count as the only hint and no way to tell which
    chunk, or why, from the logs.
    """

    def _fake_store(self, monkeypatch, chunk_ids):
        from unittest.mock import MagicMock

        store = MagicMock(name="GraphStore")
        store.pending_chunks.return_value = list(chunk_ids)
        store.apply_chunk.return_value = (1, 0)
        store.count_nodes.return_value = 1
        monkeypatch.setattr(
            "docsgpt.graphrag.store.GraphStore", lambda *a, **k: store
        )
        return store

    def test_unparseable_output_is_logged_with_the_chunk_id(
        self, monkeypatch, caplog, stub_embedding
    ):
        import logging

        store = self._fake_store(monkeypatch, ["c1"])
        _install_stub_llm(monkeypatch, _StubLLM(["not json at all", "still not json"]))

        with caplog.at_level(logging.WARNING, logger="docsgpt.graphrag.extraction"):
            summary = extract_graph_for_source(
                str(uuid.uuid4()),
                user="owner-1",
                chunks=[_chunk("c1", "some text")],
                config=SourceConfig(),
                request_id="req-1",
            )

        assert summary["failed_chunks"] == 1
        store.mark_chunk.assert_called_once()
        assert store.mark_chunk.call_args.args[2] == "failed"
        messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("c1" in message for message in messages), messages

    def test_llm_errors_still_name_the_chunk(
        self, monkeypatch, caplog, stub_embedding
    ):
        import logging

        self._fake_store(monkeypatch, ["c7"])
        _install_stub_llm(
            monkeypatch,
            _StubLLM([RuntimeError("model exploded"), RuntimeError("model exploded again")]),
        )

        with caplog.at_level(logging.WARNING, logger="docsgpt.graphrag.extraction"):
            extract_graph_for_source(
                str(uuid.uuid4()),
                user="owner-1",
                chunks=[_chunk("c7", "some text")],
                config=SourceConfig(),
                request_id="req-1",
            )

        messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("c7" in message for message in messages), messages


@pytest.mark.unit
class TestFailedChunksAreRetried:
    """A chunk that fails once gets one more attempt before the build ends.

    Failures are recorded as ``failed`` and the checkpoint treats them as
    pending, but nothing ever ran the build again, so a single transient error
    — a provider hiccup, one response that did not parse — left a permanent
    hole in the graph until someone rebuilt the whole source. Retries run
    after the rest of the build, which gives a burst of rate limiting time to
    pass, and are bounded at one per chunk so a chunk that can never be
    extracted costs at most two calls.
    """

    GOOD = _extraction_json(
        entities=[{"name": "Ada", "type": "person", "description": "d"}],
        relationships=[],
    )

    def _fake_store(self, monkeypatch, chunk_ids):
        from unittest.mock import MagicMock

        store = MagicMock(name="GraphStore")
        store.pending_chunks.return_value = list(chunk_ids)
        store.apply_chunk.return_value = (1, 0)
        store.count_nodes.return_value = 1
        monkeypatch.setattr(
            "docsgpt.graphrag.store.GraphStore", lambda *a, **k: store
        )
        return store

    def _run(self, chunks, progress=None):
        return extract_graph_for_source(
            str(uuid.uuid4()),
            user="owner-1",
            chunks=chunks,
            config=SourceConfig(),
            request_id="req-retry",
            progress_cb=progress,
        )

    @staticmethod
    def _marked_failed(store):
        return [c.args[1] for c in store.mark_chunk.call_args_list if c.args[2] == "failed"]

    def test_a_transient_failure_is_retried_and_written(self, monkeypatch, stub_embedding):
        store = self._fake_store(monkeypatch, ["c1"])
        llm = _ScriptedLLM({"flaky": [RuntimeError("rate limited"), self.GOOD]})
        _install_stub_llm(monkeypatch, llm)

        summary = self._run([_chunk("c1", "flaky")])

        assert summary["failed_chunks"] == 0
        assert summary["chunks_processed"] == 1
        assert store.apply_chunk.call_args.args[1] == "c1"
        assert self._marked_failed(store) == []

    def test_an_unparseable_response_is_retried(self, monkeypatch, stub_embedding):
        store = self._fake_store(monkeypatch, ["c1"])
        _install_stub_llm(monkeypatch, _ScriptedLLM({"odd": ["not json", self.GOOD]}))

        summary = self._run([_chunk("c1", "odd")])

        assert summary["failed_chunks"] == 0
        assert self._marked_failed(store) == []

    def test_a_chunk_that_fails_again_is_marked_failed_once(self, monkeypatch, stub_embedding):
        store = self._fake_store(monkeypatch, ["c1"])
        llm = _ScriptedLLM({"broken": ["not json", "still not json"]})
        _install_stub_llm(monkeypatch, llm)

        summary = self._run([_chunk("c1", "broken")])

        assert summary["failed_chunks"] == 1
        assert summary["chunks_processed"] == 0
        assert llm.calls_for("broken") == 2
        assert self._marked_failed(store) == ["c1"]

    def test_only_failed_chunks_are_retried(self, monkeypatch, stub_embedding):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GRAPHRAG_EXTRACTION_WORKERS", 4)
        self._fake_store(monkeypatch, ["c1", "c2", "c3"])
        llm = _ScriptedLLM({
            "one": [self.GOOD],
            "two": [RuntimeError("timeout"), self.GOOD],
            "three": [self.GOOD],
        })
        _install_stub_llm(monkeypatch, llm)

        summary = self._run([_chunk("c1", "one"), _chunk("c2", "two"), _chunk("c3", "three")])

        assert summary["chunks_processed"] == 3
        assert summary["failed_chunks"] == 0
        assert (llm.calls_for("one"), llm.calls_for("two"), llm.calls_for("three")) == (1, 2, 1)

    def test_a_failed_write_is_retried(self, monkeypatch, stub_embedding):
        store = self._fake_store(monkeypatch, ["c1"])
        store.apply_chunk.side_effect = [RuntimeError("write failed"), (1, 0)]
        _install_stub_llm(monkeypatch, _ScriptedLLM({"text": [self.GOOD, self.GOOD]}))

        summary = self._run([_chunk("c1", "text")])

        assert summary["failed_chunks"] == 0
        assert summary["chunks_processed"] == 1
        assert self._marked_failed(store) == []

    def test_progress_ends_at_the_total(self, monkeypatch, stub_embedding):
        self._fake_store(monkeypatch, ["c1", "c2"])
        _install_stub_llm(monkeypatch, _ScriptedLLM({
            "fine": [self.GOOD],
            "broken": ["not json", "still not json"],
        }))
        events = []

        self._run([_chunk("c1", "fine"), _chunk("c2", "broken")], progress=events.append)

        assert all(e["current"] <= e["total"] for e in events)
        assert events[-1]["current"] == events[-1]["total"] == 2


@pytest.mark.integration
class TestSummaryNodeCount:
    """``nodes`` must describe the graph, not the number of upserts."""

    @pytest.fixture
    def store(self, monkeypatch, postgresql):
        store = _live_store(monkeypatch, postgresql.info)
        yield store
        store.close()

    def test_repeated_entity_counts_once(
        self, store, monkeypatch, stub_embedding
    ):
        source_id = str(uuid.uuid4())
        try:
            payload = _extraction_json(
                entities=[{"name": "Ada", "type": "person", "description": "d"}],
                relationships=[],
            )
            _install_stub_llm(monkeypatch, _StubLLM([payload, payload]))

            summary = extract_graph_for_source(
                source_id,
                user="owner-1",
                chunks=[_chunk("c1", "Ada one."), _chunk("c2", "Ada two.")],
                config=SourceConfig(),
                request_id="req-1",
            )

            # Two chunks upserted the same entity: one node in the graph.
            assert store.count_nodes(source_id) == 1
            assert summary["nodes"] == 1
            assert summary["chunks_processed"] == 2
        finally:
            store.delete_by_source(source_id)


@pytest.mark.unit
class TestSummaryCountFailure:
    """A broken count query must not be reported as an empty graph."""

    def test_a_failed_count_reports_the_write_count(
        self, monkeypatch, stub_embedding
    ):
        from unittest.mock import MagicMock

        store = MagicMock(name="GraphStore")
        store.pending_chunks.return_value = ["c1"]
        store.apply_chunk.return_value = (2, 1)
        store.count_nodes.side_effect = RuntimeError("count query failed")
        monkeypatch.setattr(
            "docsgpt.graphrag.store.GraphStore", lambda *a, **k: store
        )
        _install_stub_llm(
            monkeypatch,
            _StubLLM([_extraction_json([{"name": "Ada"}], [])]),
        )

        summary = extract_graph_for_source(
            str(uuid.uuid4()),
            user="owner-1",
            chunks=[_chunk("c1", "Ada.")],
            config=SourceConfig(),
            request_id="req-1",
        )

        # Falls back to what was actually written, not to zero.
        assert summary["nodes"] == 2
        # And it asked for a count that raises rather than one that returns 0,
        # or the fallback above could never run.
        assert store.count_nodes.call_args.kwargs.get("strict") is True


@pytest.mark.unit
class TestEntityNormalization:
    """An entity whose name normalizes to nothing is not an entity.

    ``canonical_name`` answers "" for a punctuation-only name, and nodes are
    merged on that key, so keeping them collapses every such entity onto one
    shared node. ``_resolve_endpoint`` already drops them on the relationship
    side.
    """

    @pytest.mark.parametrize("name", ["!!!", "--", "?", "  ***  "])
    def test_a_name_that_normalizes_to_nothing_is_dropped(self, name):
        assert extraction_module._build_entities([{"name": name}]) == []

    def test_real_names_survive(self):
        built = extraction_module._build_entities(
            [{"name": "Quill Store"}, {"name": "!!!"}, {"name": "Alder"}]
        )
        assert [e["normalized_name"] for e in built] == ["quill store", "alder"]


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
            "docsgpt.graphrag.store.GraphStore", lambda *a, **k: fake_store
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
