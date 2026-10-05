"""RAG retrieval becomes retrieval / embeddings / search / rerank spans."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docsgpt import tracing
from docsgpt.core.settings import settings
from docsgpt.retriever import fanout


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "TRACES_ENABLED", True)
    monkeypatch.setattr(settings, "TRACES_CAPTURE_CONTENT", True)


@pytest.fixture()
def trace():
    t = tracing.start_trace(source="stream", capture_otel_context=False)
    with tracing.activate(t):
        yield t


class TestFanout:
    def test_embedding_span(self, trace):
        embedder = MagicMock()
        embedder.embed_query.side_effect = lambda q: [0.1, 0.2]
        store = MagicMock(_embedding=embedder)
        vectors = fanout.embed_questions(store, ["q", "q", "r"])
        assert set(vectors) == {"q", "r"}
        (span,) = trace.spans
        assert span.kind == tracing.KIND_EMBEDDING
        assert span.attributes["gen_ai.operation.name"] == "embeddings"
        assert span.attributes["docsgpt.input_count"] == 2

    def test_embedding_failure_is_recorded(self, trace):
        embedder = MagicMock()
        embedder.embed_query.side_effect = RuntimeError("model down")
        assert fanout.embed_questions(MagicMock(_embedding=embedder), ["q"]) == {}
        assert trace.spans[0].status == "error"

    def test_pool_jobs_nest_under_the_open_retrieval(self, trace, monkeypatch):
        monkeypatch.setattr(settings, "RETRIEVAL_MAX_PARALLEL_SOURCES", 4)

        def job(i):
            with tracing.span(tracing.KIND_SEARCH, f"search {i}"):
                return i

        with tracing.span(tracing.KIND_RETRIEVAL, "retrieval") as outer:
            assert fanout.run_source_jobs(job, [1, 2, 3]) == [1, 2, 3]
        searches = [s for s in trace.spans if s.kind == tracing.KIND_SEARCH]
        assert len(searches) == 3
        assert all(s.parent_id == outer.id for s in searches)


class TestClassicRAG:
    def _rag(self, stores):
        from docsgpt.retriever.classic_rag import ClassicRAG

        with patch("docsgpt.retriever.classic_rag.LLMCreator.create_llm", return_value=MagicMock()):
            rag = ClassicRAG(
                source={"question": "what is x", "active_docs": list(stores)},
                chunks=4,
                decoded_token={"sub": "u1"},
            )
        return rag

    def test_search_records_retrieval_tree(self, trace, monkeypatch):
        monkeypatch.setattr(settings, "RETRIEVAL_MAX_PARALLEL_SOURCES", 4)
        embedder = MagicMock()
        embedder.embed_query.return_value = [0.1]

        def make_store(*_args, **_kwargs):
            store = MagicMock(_embedding=embedder)
            store.search.return_value = [
                {"text": "chunk body", "metadata": {"title": "Doc", "source": "doc.md"}}
            ]
            return store

        rag = self._rag(["s1", "s2"])
        with patch(
            "docsgpt.retriever.classic_rag.VectorCreator.create_vectorstore",
            side_effect=make_store,
        ):
            docs = rag.search()
        assert len(docs) == 2
        retrieval = trace.spans[0]
        assert retrieval.kind == tracing.KIND_RETRIEVAL
        assert retrieval.attributes["docsgpt.source_ids"] == ["s1", "s2"]
        assert retrieval.attributes["docsgpt.chunk_count"] == 2
        assert retrieval.previews["query"] == "what is x"
        assert retrieval.previews["chunks"][0]["text"] == "chunk body"
        children = [s for s in trace.spans[1:]]
        assert {s.kind for s in children} == {tracing.KIND_EMBEDDING, tracing.KIND_SEARCH}
        assert all(s.parent_id == retrieval.id for s in children)
        searches = [s for s in children if s.kind == tracing.KIND_SEARCH]
        assert sorted(s.attributes["gen_ai.data_source.id"] for s in searches) == ["s1", "s2"]
        assert all(s.attributes["docsgpt.candidate_count"] == 1 for s in searches)

    def test_failed_source_search_is_an_error_span(self, trace, monkeypatch):
        monkeypatch.setattr(settings, "RETRIEVAL_MAX_PARALLEL_SOURCES", 1)
        rag = self._rag(["s1", "s2"])

        def make_store(_kind, source_id, _key):
            if source_id == "s2":
                raise RuntimeError("no store")
            store = MagicMock(_embedding=None, _embeddings=None, embeddings=None)
            store._get_embeddings.side_effect = RuntimeError("no embedder")
            store.search.return_value = []
            return store

        with patch(
            "docsgpt.retriever.classic_rag.VectorCreator.create_vectorstore",
            side_effect=make_store,
        ):
            assert rag.search() == []
        search = {s.attributes["gen_ai.data_source.id"]: s for s in trace.spans if s.kind == tracing.KIND_SEARCH}
        assert search["s1"].status == "ok"
        assert search["s2"].status == "error"
        assert trace.spans[0].status == "ok"


class TestPrescreen:
    def test_rerank_span_contains_screening_calls(self, trace):
        from docsgpt.retriever.stages.prescreen import PreScreenStage
        from docsgpt.storage.db.source_config import PreScreenConfig

        stage = PreScreenStage(
            PreScreenConfig(candidate_k=10, max_keep=2, batch_size=1),
            llm_name="openai",
            api_key=None,
            model_id="m",
        )
        llm = MagicMock()

        def fake_gen(**_kwargs):
            with tracing.span(tracing.KIND_LLM, "chat m"):
                return '{"keep": [0]}'

        llm.gen.side_effect = fake_gen
        stage._build_llm = lambda: llm
        docs = [{"text": f"d{i}"} for i in range(3)]
        kept = stage(docs, {"query": "q"})
        assert len(kept) == 2
        rerank = trace.spans[0]
        assert rerank.kind == tracing.KIND_RERANK
        assert rerank.attributes["docsgpt.kept_count"] == 2
        llm_spans = [s for s in trace.spans if s.kind == tracing.KIND_LLM]
        assert len(llm_spans) == 3
        assert all(s.parent_id == rerank.id for s in llm_spans)
