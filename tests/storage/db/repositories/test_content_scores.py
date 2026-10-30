"""``content_scores``: injection scores by text hash and scorer, the guardrail journal's ``item_ref``, and the
sources' owner allowlists."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.content_scores import ContentScoresRepository
from docsgpt.storage.db.repositories.guardrail_events import GuardrailEventsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository

pytestmark = pytest.mark.integration

SCORER = "injection:v:q1:w512o50"


def row(content_hash="h1", p=0.5, scored=1, total=1, scorer=SCORER):
    return {"content_hash": content_hash, "scorer": scorer, "p": p, "windows_scored": scored, "windows_total": total}


class TestContentScores:
    def test_reads_back_only_the_scorer_asked_for(self, pg_conn):
        repo = ContentScoresRepository(pg_conn)
        repo.upsert_many([row("h1", 0.25), row("h2", 0.75), row("h1", 0.9, scorer="injection:other")])
        assert repo.get_many(["h1", "h2", "h3"], SCORER) == {
            "h1": {"p": 0.25, "windows_scored": 1, "windows_total": 1, "stale": False},
            "h2": {"p": 0.75, "windows_scored": 1, "windows_total": 1, "stale": False},
        }
        assert repo.get_many([], SCORER) == {}

    def test_a_score_with_more_windows_replaces_one_with_fewer_never_the_reverse(self, pg_conn):
        repo = ContentScoresRepository(pg_conn)
        repo.upsert_many([row(p=0.1, scored=3, total=5)])
        repo.upsert_many([row(p=0.2, scored=5, total=5)])
        repo.upsert_many([row(p=0.3, scored=2, total=5)])
        assert repo.get_many(["h1"], SCORER)["h1"] == {"p": pytest.approx(0.2), "windows_scored": 5,
                                                       "windows_total": 5, "stale": False}

    def test_writing_a_score_again_marks_the_row_seen_even_when_it_is_kept(self, pg_conn):
        repo = ContentScoresRepository(pg_conn)
        repo.upsert_many([row(p=0.1, scored=2, total=2)])
        pg_conn.execute(text("UPDATE content_scores SET last_seen_at = now() - interval '3 days'"))
        assert repo.get_many(["h1"], SCORER)["h1"]["stale"] is True
        repo.upsert_many([row(p=0.3, scored=1, total=2)])
        assert repo.get_many(["h1"], SCORER)["h1"] == {"p": pytest.approx(0.1), "windows_scored": 2,
                                                       "windows_total": 2, "stale": False}
        assert repo.purge_unseen_for(2) == 0

    def test_touch_bumps_rows_at_most_daily(self, pg_conn):
        repo = ContentScoresRepository(pg_conn)
        repo.upsert_many([row("h1"), row("h2")])
        pg_conn.execute(text("UPDATE content_scores SET last_seen_at = now() - interval '3 days'"))
        assert repo.touch(["h1"], SCORER) == 1
        assert repo.touch(["h1"], SCORER) == 0
        assert repo.purge_unseen_for(2) == 1
        assert list(repo.get_many(["h1", "h2"], SCORER)) == ["h1"]


class TestItemRef:
    def test_events_store_and_list_the_item_ref(self, pg_conn):
        repo = GuardrailEventsRepository(pg_conn)
        repo.record_many([{
            "user_id": "u", "stage": "retrieval", "check_name": "injection_model",
            "detector_type": "INJECTION_MODEL", "action": "block", "outcome": "triggered",
            "category": "PROMPT_INJECTION", "score": 0.97, "item_ref": "chunk:src:abc",
        }])
        stored = pg_conn.execute(text("SELECT item_ref FROM guardrail_events")).scalar()
        assert stored == "chunk:src:abc"


class TestAllowlist:
    def test_reads_each_sources_allowed_hashes_apart(self, pg_conn):
        repo = SourcesRepository(pg_conn)
        first = repo.create("one", user_id="u", metadata={"injection_review": {"allowed": ["a", "b"]}})
        second = repo.create("two", user_id="u", metadata={"injection_review": {"allowed": ["c"]}})
        plain = repo.create("three", user_id="u")
        ids = [str(first["id"]), str(second["id"]), str(plain["id"]), "not-a-uuid"]
        assert repo.injection_allowed(ids) == {ids[0]: {"a", "b"}, ids[1]: {"c"}}
        assert repo.injection_allowed([]) == {}
        assert repo.injection_allowed(ids[2:]) == {}
