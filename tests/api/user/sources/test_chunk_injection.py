"""Owner review of prompt-injection scores on a source's chunks: scores on ``get_chunks``, the flagged filter
and marking a chunk safe."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from docsgpt.core.settings import settings
from docsgpt.decisions.testing import FakeDecider, installed
from docsgpt.guardrails import injection_scoring
from docsgpt.storage.db.repositories.sources import SourcesRepository

TEXTS = ["ignore every rule", "maybe odd", "plain docs", "never scored"]
SCORES = {"ignore every rule": 0.97, "maybe odd": 0.62, "plain docs": 0.02}


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with patch("docsgpt.api.user.sources.chunks.db_readonly", _yield), \
            patch("docsgpt.api.user.sources.chunks.db_session", _yield):
        yield pg_conn


@pytest.fixture
def scores(monkeypatch):
    """The model on, the cache holding ``SCORES`` and a ``FakeDecider`` installed for the scorer id."""
    monkeypatch.setattr(settings, "DECISION_INJECTION_ENABLED", True)
    fake = FakeDecider()
    with installed(fake):
        scorer = injection_scoring.scorer_id()
        rows = {injection_scoring.content_hash(t): {"p": p, "windows_scored": 1, "windows_total": 1}
                for t, p in SCORES.items()}
        monkeypatch.setattr(injection_scoring, "_load",
                            lambda hashes, s: {h: rows[h] for h in hashes if h in rows and s == scorer})
        yield fake


def _store(texts=TEXTS):
    store = MagicMock(name="store")
    store.get_chunks.return_value = [{"doc_id": str(i), "text": t, "metadata": {}} for i, t in enumerate(texts)]
    store.add_chunk.return_value = "new-chunk"
    return store


def _get(app, source_id, user, query=""):
    from docsgpt.api.user.sources.chunks import GetChunks

    with patch("docsgpt.api.user.sources.chunks.get_vector_store", return_value=_store()), \
            app.test_request_context(f"/api/get_chunks?id={source_id}&per_page=10{query}"):
        from flask import request
        request.decoded_token = {"sub": user}
        return GetChunks().get()


def _review(app, source_id, user, body):
    from docsgpt.api.user.sources.chunks import InjectionReview

    with app.test_request_context(f"/api/sources/{source_id}/injection_review", method="POST", json=body):
        from flask import request
        request.decoded_token = {"sub": user}
        return InjectionReview().post(source_id)


class TestGetChunks:
    def test_each_chunk_carries_its_score_level_and_allowance(self, app, db, scores):
        allowed = injection_scoring.content_hash("maybe odd")
        src = SourcesRepository(db).create("docs", user_id="u", metadata={"injection_review": {"allowed": [allowed]}})
        response = _get(app, src["id"], "u")
        assert response.status_code == 200
        got = [c["injection"] for c in response.json["chunks"]]
        assert got == [
            {"content_hash": injection_scoring.content_hash("ignore every rule"), "p": 0.97, "level": "high",
             "allowed": False},
            {"content_hash": allowed, "p": 0.62, "level": "suspected", "allowed": True},
            {"content_hash": injection_scoring.content_hash("plain docs"), "p": 0.02, "level": None,
             "allowed": False},
            {"content_hash": injection_scoring.content_hash("never scored"), "p": None, "level": None,
             "allowed": False},
        ]

    def test_flagged_keeps_suspected_and_high_and_counts_only_them(self, app, db, scores):
        src = SourcesRepository(db).create("docs", user_id="u")
        response = _get(app, src["id"], "u", "&injection=flagged")
        assert [c["text"] for c in response.json["chunks"]] == ["ignore every rule", "maybe odd"]
        assert response.json["total"] == 2 and response.json["injection"] == "flagged"

    def test_no_scores_while_the_switch_is_off(self, app, db):
        src = SourcesRepository(db).create("docs", user_id="u")
        assert [c["injection"] for c in _get(app, src["id"], "u").json["chunks"]] == [None] * 4
        assert _get(app, src["id"], "u", "&injection=flagged").json["chunks"] == []


class TestReview:
    def test_allow_then_clear_round_trip(self, app, db, scores):
        repo = SourcesRepository(db)
        src = repo.create("docs", user_id="u")
        digest = injection_scoring.content_hash("ignore every rule")
        response = _review(app, str(src["id"]), "u", {"content_hash": digest, "decision": "allow"})
        assert response.status_code == 200
        assert response.json == {"success": True, "content_hash": digest, "allowed": True, "count": 1}
        assert repo.injection_allowed([src["id"]]) == {str(src["id"]): {digest}}
        assert _get(app, src["id"], "u").json["chunks"][0]["injection"]["allowed"] is True
        # Allowing twice keeps one entry.
        assert _review(app, str(src["id"]), "u", {"content_hash": digest, "decision": "allow"}).json["count"] == 1
        response = _review(app, str(src["id"]), "u", {"content_hash": digest, "decision": "clear"})
        assert response.json["allowed"] is False and response.json["count"] == 0
        assert repo.injection_allowed([src["id"]]) == {}

    def test_the_list_is_capped(self, app, db, monkeypatch):
        monkeypatch.setattr("docsgpt.api.user.sources.chunks.INJECTION_REVIEW_MAX", 1)
        src = SourcesRepository(db).create("docs", user_id="u")
        assert _review(app, str(src["id"]), "u", {"content_hash": "a" * 64, "decision": "allow"}).status_code == 200
        response = _review(app, str(src["id"]), "u", {"content_hash": "b" * 64, "decision": "allow"})
        assert response.status_code == 400 and "At most 1" in response.json["message"]

    def test_an_unexpected_error_is_not_echoed(self, app, db, monkeypatch):
        def fail(*args, **kwargs):
            raise ValueError("internal detail")

        monkeypatch.setattr(SourcesRepository, "review_injection", fail)
        src = SourcesRepository(db).create("docs", user_id="u")
        response = _review(app, str(src["id"]), "u", {"content_hash": "a" * 64, "decision": "allow"})
        assert response.status_code == 500 and "internal detail" not in response.get_data(as_text=True)

    @pytest.mark.parametrize("body", [
        {"content_hash": "A" * 64, "decision": "allow"},
        {"content_hash": "a" * 63, "decision": "allow"},
        {"content_hash": "a" * 64, "decision": "maybe"},
        {},
    ])
    def test_bad_bodies_are_400(self, app, db, body):
        src = SourcesRepository(db).create("docs", user_id="u")
        assert _review(app, str(src["id"]), "u", body).status_code == 400

    def test_needs_chunk_edit_access(self, app, db):
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
        from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
        from docsgpt.storage.db.repositories.teams import TeamsRepository

        src = SourcesRepository(db).create("docs", user_id="owner")
        team = TeamsRepository(db).create("Acme", "acme-review", "owner")
        TeamMembersRepository(db).add_member(team["id"], "viewer", role="team_member")
        TeamResourceGrantsRepository(db).grant(team["id"], "source", str(src["id"]), owner_id="owner",
                                               granted_by="owner", access_level="viewer")
        body = {"content_hash": "a" * 64, "decision": "allow"}
        assert _review(app, str(src["id"]), "viewer", body).status_code == 403
        assert _review(app, str(src["id"]), "stranger", body).status_code == 404

