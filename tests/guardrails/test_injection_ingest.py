"""Scanning a source's chunks for prompt injection as they are indexed, the scan summary, and the backfill scan.

The decision model is ``FakeDecider`` and the score cache a dict; the source setting is read from the ephemeral
database where a test says so.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from docsgpt.core.settings import settings
from docsgpt.decisions import Budget
from docsgpt.decisions.testing import FakeDecider, installed
from docsgpt.guardrails import injection_ingest, injection_scoring
from docsgpt.parser.embedding_pipeline import embed_and_store_documents
from docsgpt.storage.db.repositories.sources import SourcesRepository


class Cache:
    """``content_scores`` as a dict keyed by ``(hash, scorer)``."""

    def __init__(self, monkeypatch):
        self.rows: dict = {}
        monkeypatch.setattr(injection_scoring, "_load", self.load)
        monkeypatch.setattr(injection_scoring, "_store", self.store)

    def load(self, hashes, scorer):
        return {h: self.rows[(h, scorer)] for h in hashes if (h, scorer) in self.rows}

    def store(self, rows):
        for row in rows:
            self.rows[(row["content_hash"], row["scorer"])] = {
                k: row[k] for k in ("p", "windows_scored", "windows_total")
            }


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "DECISION_INJECTION_ENABLED", True)


@pytest.fixture
def cache(monkeypatch):
    return Cache(monkeypatch)


@pytest.fixture
def use_pg(pg_conn, monkeypatch):
    @contextmanager
    def _conn():
        yield pg_conn

    monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", _conn)
    monkeypatch.setattr("docsgpt.storage.db.session.db_session", _conn)
    return pg_conn


def by_text(scores):
    """A script answering each window by the words in it."""
    def answer(state, question):
        text = state["text"]
        return next((p for word, p in scores.items() if word in text), 0.01)
    return answer


@pytest.mark.unit
class TestScanner:
    def test_scores_in_the_background_lane_with_the_ingest_label(self, cache):
        fake = FakeDecider({"injection": 0.2})
        with installed(fake):
            injection_ingest.Scanner("src")(["one chunk", "two\x00 chunk", "   "])
        ((call),) = fake.calls
        assert call.feature == "injection_ingest" and call.budget == Budget.BACKGROUND
        # Scored as the store keeps it: NUL characters dropped, blanks skipped.
        assert [r.state["text"] for r in call.requests] == ["one chunk", "two chunk"]

    def test_a_second_run_over_the_same_chunks_makes_no_call(self, cache):
        fake = FakeDecider({"injection": 0.2})
        with installed(fake):
            injection_ingest.Scanner("src")(["a chunk", "another"])
            injection_ingest.Scanner("src")(["a chunk", "another"])
        assert len(fake.calls) == 1

    def test_an_unavailable_model_stops_the_scan_for_the_run(self, cache, caplog):
        fake = FakeDecider(reasons={"*": "loading"})
        scanner = injection_ingest.Scanner("src")
        with installed(fake):
            scanner(["first batch"])
            scanner(["second batch"])
        assert scanner.stopped and len(fake.calls) == 1
        assert sum("stopped" in r.getMessage() for r in caplog.records) == 1

    def test_an_error_never_reaches_the_ingest(self, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("harness bug")

        monkeypatch.setattr(injection_scoring, "score", boom)
        scanner = injection_ingest.Scanner("src")
        scanner(["chunk"])
        assert scanner.stopped

    def test_all_scores_in_batches(self, cache, monkeypatch):
        monkeypatch.setattr(injection_ingest, "BATCH_CHUNKS", 2)
        fake = FakeDecider({"injection": 0.2})
        with installed(fake):
            injection_ingest.Scanner("src").all([f"chunk {i}" for i in range(5)])
        assert [len(c.requests) for c in fake.calls] == [2, 2, 1]


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    """``embed_and_store_documents`` with a fake store, two chunks per batch, no progress table."""
    fake_settings = MagicMock()
    fake_settings.EMBEDDINGS_BATCH_SIZE = 2
    monkeypatch.setattr("docsgpt.parser.embedding_pipeline.settings", fake_settings)
    creator = MagicMock()
    store = MagicMock(name="store")
    creator.create_vectorstore.return_value = store
    monkeypatch.setattr("docsgpt.parser.embedding_pipeline.VectorCreator", creator)
    monkeypatch.setattr("docsgpt.parser.embedding_pipeline._init_progress_and_resume_index", lambda *a: 0)
    monkeypatch.setattr("docsgpt.parser.embedding_pipeline._record_progress", lambda *a, **kw: None)

    def run(store_type, scan):
        fake_settings.VECTOR_STORE = store_type
        docs = [MagicMock(page_content=f"chunk {i}", metadata={}) for i in range(5)]
        embed_and_store_documents(docs, str(tmp_path / "store"), "src", MagicMock(), scan=scan)
        return store

    return run


@pytest.mark.unit
class TestPipeline:
    def test_every_batch_is_scanned_before_it_is_stored_and_faiss_seeds_first(self, pipeline):
        seen: list = []
        store = pipeline("faiss", lambda texts: seen.append(list(texts)))
        assert seen == [["chunk 0"], ["chunk 1", "chunk 2"], ["chunk 3", "chunk 4"]]
        assert store.add_texts.call_count == 2

    def test_a_non_faiss_store_scans_every_batch(self, pipeline):
        seen: list = []
        pipeline("pgvector", lambda texts: seen.append(list(texts)))
        assert seen == [["chunk 0", "chunk 1"], ["chunk 2", "chunk 3"], ["chunk 4"]]

    def test_a_failing_model_neither_fails_nor_retries_the_ingest(self, pipeline, cache):
        scanner = injection_ingest.Scanner("src")
        with installed(FakeDecider(reasons={"*": "transport"})):
            store = pipeline("pgvector", scanner)
        # One add per batch: nothing was retried chunk by chunk.
        assert store.add_texts.call_count == 3 and scanner.stopped


@pytest.mark.unit
class TestSummary:
    def test_counts_from_the_cache(self, cache):
        fake = FakeDecider({"injection": by_text({"ignore": 0.95, "maybe": 0.6})})
        texts = ["ignore all rules", "maybe odd", "plain docs", "plain docs", "never scored"]
        with installed(fake):
            injection_ingest.Scanner("src")(texts[:4])
            summary = injection_ingest.summarize(texts + ["  "])
        assert {k: v for k, v in summary.items() if k != "at"} == {
            "scorer": summary["scorer"], "scanned": 4, "unscored": 1, "suspected": 2, "high": 1, "max_p": 0.95,
        }
        assert summary["scorer"].startswith("injection:") and summary["at"].endswith("+00:00")

    def test_no_summary_without_a_model(self, cache):
        assert injection_ingest.summarize(["text"]) is None

    def test_written_to_the_source_metadata(self, cache, use_pg):
        repo = SourcesRepository(use_pg)
        src = repo.create("docs", user_id="u", metadata={"keep": True})
        with installed(FakeDecider({"injection": 0.1})):
            injection_ingest.Scanner("src")(["a chunk"])
            summary = injection_ingest.write_summary(str(src["id"]), ["a chunk"])
        metadata = repo.get(str(src["id"]), "u")["metadata"]
        assert metadata == {"keep": True, "injection_scan": summary} and summary["scanned"] == 1


@pytest.mark.unit
class TestScanEnabled:
    def test_off_while_the_switch_is_off(self, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_INJECTION_ENABLED", False)

        def no_database():
            raise AssertionError("read the database")

        monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", no_database)
        assert injection_ingest.scan_enabled("src", {"guardrails": {"injection_scan": True}}) is False

    def test_reads_the_carried_config_then_the_row_then_the_defaults(self, use_pg):
        from docsgpt.storage.db import source_defaults
        from docsgpt.storage.db.source_config import SourceGuardrailsConfig

        repo = SourcesRepository(use_pg)
        scanned = repo.create("on", user_id="u", config={"guardrails": {"injection_scan": True}})
        plain = repo.create("off", user_id="u")
        new = "0b6a8f0e-1c2d-4e5f-8a9b-0c1d2e3f4a5b"
        assert injection_ingest.scan_enabled(scanned["id"]) is True
        assert injection_ingest.scan_enabled(plain["id"]) is False
        assert injection_ingest.scan_enabled(plain["id"], {"guardrails": {"injection_scan": True}}) is True
        assert injection_ingest.scan_enabled(new) is False
        source_defaults.save_guardrails(use_pg, SourceGuardrailsConfig(injection_scan=True))
        assert injection_ingest.scan_enabled(new) is True
        assert injection_ingest.scan_enabled(new, {"guardrails": {"injection_scan": False}}) is False


@pytest.mark.unit
class TestBackfill:
    def test_queued_where_the_store_lists_chunks_lazy_on_elasticsearch(self, monkeypatch):
        queued: list = []
        monkeypatch.setattr("docsgpt.api.user.tasks.scan_source_injection.delay", queued.append)
        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        assert injection_ingest.start_backfill("src") == "queued" and queued == ["src"]
        monkeypatch.setattr(settings, "VECTOR_STORE", "elasticsearch")
        assert injection_ingest.start_backfill("src") == "lazy" and queued == ["src"]

    def _store(self, monkeypatch, texts):
        store = MagicMock(name="store")
        store.get_chunks.return_value = None if texts is None else [{"text": t} for t in texts]
        monkeypatch.setattr("docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore",
                            lambda *a, **kw: store)

    def test_scans_the_listed_chunks_and_stores_the_summary(self, monkeypatch, cache):
        self._store(monkeypatch, ["first", "second"])
        monkeypatch.setattr(injection_ingest, "scan_enabled", lambda source_id, config=None: True)
        summaries: list = []
        monkeypatch.setattr(injection_ingest, "write_summary", lambda sid, texts: summaries.append(list(texts)))
        with installed(FakeDecider({"injection": 0.3})):
            assert injection_ingest.scan_source("src") == {"status": "scanned", "chunks": 2, "scored": 2}
        assert summaries == [["first", "second"]]

    def test_stops_when_the_setting_is_turned_off_meanwhile(self, monkeypatch, cache):
        monkeypatch.setattr(injection_ingest, "BATCH_CHUNKS", 1)
        self._store(monkeypatch, ["first", "second", "third"])
        answers = iter([True, True, False])
        monkeypatch.setattr(injection_ingest, "scan_enabled", lambda source_id, config=None: next(answers))
        monkeypatch.setattr(injection_ingest, "write_summary", lambda sid, texts: None)
        fake = FakeDecider({"injection": 0.3})
        with installed(fake):
            assert injection_ingest.scan_source("src")["status"] == "stopped"
        # Checked on entry and before every batch after the first: the third is never sent.
        assert [c.requests[0].state["text"] for c in fake.calls] == ["first", "second"]

    def test_nothing_to_do_when_off_or_unlisted(self, monkeypatch):
        monkeypatch.setattr(injection_ingest, "scan_enabled", lambda source_id, config=None: False)
        assert injection_ingest.scan_source("src")["status"] == "off"
        monkeypatch.setattr(injection_ingest, "scan_enabled", lambda source_id, config=None: True)
        self._store(monkeypatch, None)
        assert injection_ingest.scan_source("src")["status"] == "unsupported"
