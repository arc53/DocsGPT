"""The admin's default retrieval settings for new sources: storage, routes and seeding on every creation path."""

from __future__ import annotations

import dataclasses
import json
from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.storage.db import source_defaults
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.source_config import RELEVANCE_OR_PRESCREEN, RetrievalConfig

STRICT = {"chunks": 4, "reranker": {"type": "decision", "min_relevance": 0.5, "candidate_k": None}}


@contextmanager
def _yielding(conn):
    yield conn


def _store(conn, **retrieval):
    return source_defaults.save(conn, RetrievalConfig(**retrieval))


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def db(pg_conn):
    with ExitStack() as stack:
        for target in (
            "docsgpt.api.admin.defaults.db_readonly",
            "docsgpt.api.admin.defaults.db_session",
            "docsgpt.api.user.sources.routes.db_readonly",
            "docsgpt.api.user.sources.routes.db_session",
            "docsgpt.storage.db.source_defaults.db_readonly",
            "docsgpt.api.internal.routes.db_session",
        ):
            stack.enter_context(patch(target, lambda: _yielding(pg_conn)))
        yield pg_conn


@contextmanager
def _as(sub, *roles):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=list(roles) or ["user"]
    ):
        yield


def _admin():
    return _as("admin1", "admin", "user")


@pytest.mark.unit
class TestStorage:
    def test_without_a_row_new_sources_get_the_built_in_defaults(self, pg_conn):
        assert source_defaults.stored(pg_conn) is None
        assert source_defaults.load(pg_conn) == RetrievalConfig().model_dump()
        assert source_defaults.seed(pg_conn, None) is None
        config = {"chunking": {"max_tokens": 900}}
        assert source_defaults.seed(pg_conn, config) is config

    def test_the_request_wins_field_by_field(self, pg_conn):
        _store(pg_conn, **STRICT)
        seeded = source_defaults.seed(pg_conn, {"chunking": {"max_tokens": 900}, "retrieval": {"chunks": 9}})
        assert seeded["chunking"] == {"max_tokens": 900}
        assert seeded["retrieval"]["chunks"] == 9
        assert seeded["retrieval"]["reranker"]["min_relevance"] == 0.5
        assert source_defaults.seed(pg_conn, None)["retrieval"]["chunks"] == 4

    def test_a_request_choosing_llm_screening_drops_the_default_relevance(self, pg_conn):
        _store(pg_conn, **STRICT)
        seeded = source_defaults.seed(pg_conn, {"retrieval": {"prescreen": {"candidate_k": 40}}})
        assert seeded["retrieval"]["reranker"] is None and seeded["retrieval"]["prescreen"] == {"candidate_k": 40}
        RetrievalConfig.model_validate(seeded["retrieval"])
        _store(pg_conn, prescreen={"candidate_k": 30})
        seeded = source_defaults.seed(pg_conn, {"retrieval": {"reranker": {}}})
        assert seeded["retrieval"]["prescreen"] is None and seeded["retrieval"]["reranker"] == {}

    def test_a_request_turning_relevance_off_keeps_it_off(self, pg_conn):
        _store(pg_conn, **STRICT)
        assert source_defaults.seed(pg_conn, {"retrieval": {"reranker": None}})["retrieval"]["reranker"] is None

    def test_a_malformed_request_is_left_to_validation(self, pg_conn):
        _store(pg_conn, **STRICT)
        config = {"retrieval": "nope"}
        assert source_defaults.seed(pg_conn, config) is config

    def test_an_unreadable_row_is_no_row(self, pg_conn):
        from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository

        AppMetadataRepository(pg_conn).set(source_defaults.KEY, json.dumps({"bogus": 1}))
        assert source_defaults.stored(pg_conn) is None
        assert source_defaults.load(pg_conn) == RetrievalConfig().model_dump()


@pytest.mark.unit
class TestAdminRoutes:
    @pytest.mark.parametrize("method", ["get", "put"])
    def test_unauthenticated(self, client, method):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert getattr(client, method)("/api/admin/defaults/sources", json={}).status_code == 401

    @pytest.mark.parametrize("method", ["get", "put"])
    def test_non_admin_forbidden(self, client, db, method):
        with _as("member"):
            resp = getattr(client, method)("/api/admin/defaults/sources", json={"retrieval": STRICT})
        assert resp.status_code == 403
        assert source_defaults.stored(db) is None

    def test_get_without_a_row_and_without_measuring(self, client, db, monkeypatch):
        from docsgpt import decisions
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "DECISION_MODE", None)
        monkeypatch.setattr(settings, "DECISION_MODEL", None)

        def refuse(*args, **kwargs):
            raise AssertionError("the Defaults panel must not load or time the model")

        monkeypatch.setattr(decisions, "warm", refuse)
        monkeypatch.setattr(decisions, "auto_on", refuse)
        with _admin():
            resp = client.get("/api/admin/defaults/sources")
        assert resp.status_code == 200
        assert resp.json == {
            "success": True,
            "retrieval": RetrievalConfig().model_dump(),
            "relevance_model": {
                "enabled": False, "predicted_s": None, "timeout_s": 2.0, "candidate_k": 20, "runtime": "onnx-int8",
            },
        }
        assert decisions.get_decider()._backend is None

    @pytest.mark.parametrize("runtime, tokens", [("onnx-int8", 320), ("vllm", 1220)])
    def test_predicted_s_is_one_call_over_the_default_pool_in_the_stage_shape(
        self, client, db, monkeypatch, runtime, tokens
    ):
        from docsgpt.core.settings import settings
        from docsgpt.decisions.latency import RELEVANCE, SpeedProfile
        from docsgpt.decisions.testing import FakeDecider, installed

        profile = SpeedProfile(c=0.01, a=0.0001, b=0.0, overhead=50, threads=4, measured_at=0.0)
        fake = FakeDecider(profile=profile)
        fake.info = dataclasses.replace(fake.info, runtime=runtime)
        monkeypatch.setattr(settings, "DECISION_RELEVANCE_ENABLED", True)
        shapes = []
        real = SpeedProfile.predict_s
        monkeypatch.setattr(SpeedProfile, "predict_s", lambda self, shape: shapes.append(shape) or real(self, shape))
        with installed(fake), _admin():
            model = client.get("/api/admin/defaults/sources").json["relevance_model"]
        relevance = {(s.states, s.state_tokens, s.question_tokens) for s in shapes if s.states > 1}
        assert relevance == {(20, tokens, RELEVANCE.question_tokens)}
        shape = next(s for s in shapes if s.states > 1)
        assert model["predicted_s"] == round(real(profile, shape), 3) and model["runtime"] == runtime
        assert model["enabled"] is True and fake.calls == [] and fake.warmed == 0

    def test_put_stores_returns_the_get_body_and_audits_once(self, client, db):
        with _admin():
            resp = client.put("/api/admin/defaults/sources", json={"retrieval": STRICT})
            again = client.put("/api/admin/defaults/sources", json={"retrieval": STRICT})
            got = client.get("/api/admin/defaults/sources")
        assert resp.status_code == 200 and again.status_code == 200
        assert resp.json["retrieval"] == RetrievalConfig(**STRICT).model_dump() == got.json["retrieval"]
        assert set(resp.json["relevance_model"]) == {"enabled", "predicted_s", "timeout_s", "candidate_k", "runtime"}
        rows = db.execute(
            text("SELECT actor_id, metadata FROM auth_events WHERE event = 'source_defaults_set'")
        ).fetchall()
        assert len(rows) == 1, "an unchanged save records nothing"
        actor, metadata = rows[0]
        assert actor == "admin1" and set(metadata["changes"]) == {"chunks", "reranker"}

    @pytest.mark.parametrize(
        "body, message",
        [
            ({}, "retrieval must be an object"),
            ({"retrieval": []}, "retrieval must be an object"),
            ({"retrieval": {"chunks": 0}}, "Invalid retrieval config: one or more fields failed validation."),
            ({"retrieval": {"reranker": {"type": "off"}}},
             "Invalid retrieval config: one or more fields failed validation."),
            ({"retrieval": {"reranker": {}, "prescreen": {"candidate_k": 40}}}, RELEVANCE_OR_PRESCREEN),
            ({"retrieval": {"retriever": "nope"}}, "Unknown retriever 'nope'."),
        ],
    )
    def test_put_validates(self, client, db, body, message):
        with _admin():
            resp = client.put("/api/admin/defaults/sources", json=body)
        assert resp.status_code == 400 and resp.json == {"success": False, "message": message}
        assert source_defaults.stored(db) is None

    def test_saving_defaults_never_touches_an_existing_source(self, client, db):
        repo = SourcesRepository(db)
        before = repo.create("old", user_id="u", config={"retrieval": {"chunks": 3}})
        with _admin():
            assert client.put("/api/admin/defaults/sources", json={"retrieval": STRICT}).status_code == 200
        assert repo.get_any(str(before["id"]), "u")["config"] == before["config"]


@pytest.mark.unit
class TestMemberRead:
    def test_unauthenticated(self, client):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.get("/api/sources/defaults").status_code == 401

    def test_any_user_reads_the_retrieval_only(self, client, db):
        with _as("member"):
            empty = client.get("/api/sources/defaults")
        _store(db, **STRICT)
        with _as("member"):
            stored = client.get("/api/sources/defaults")
        assert empty.status_code == 200 and empty.json == {"success": True, "retrieval": RetrievalConfig().model_dump()}
        assert stored.json == {"success": True, "retrieval": RetrievalConfig(**STRICT).model_dump()}

    def test_a_token_may_read_it(self):
        from docsgpt.api.pat.rules import RULES, is_denied

        rule = RULES[("/api/sources/defaults", "GET")]
        assert rule.scopes == ("sources:read",) and rule.open
        assert is_denied("/api/admin/defaults/sources", "GET") and is_denied("/api/admin/defaults/sources", "PUT")


# ── Seeding: every path that creates a source ─────────────────────────────────


_TEST_KEY = "test-internal-key"


def _upload_index(pg_conn, **form):
    """POST /api/upload_index, as every ingest (upload, remote, connector, attachments, seeder) finishes."""
    from docsgpt.api.internal.routes import internal

    app = Flask(__name__)
    app.register_blueprint(internal)
    base = {"user": "alice", "name": "Job", "tokens": "1", "retriever": "classic", "type": "file"}
    with patch("docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY), patch(
        "docsgpt.api.internal.routes.settings.VECTOR_STORE", "milvus"
    ), patch("docsgpt.api.internal.routes.StorageCreator.get_storage", return_value=MagicMock()), patch(
        "docsgpt.api.internal.routes.db_session", lambda: _yielding(pg_conn)
    ):
        with app.test_client() as c:
            resp = c.post("/api/upload_index", headers={"X-Internal-Key": _TEST_KEY}, data={**base, **form})
    assert resp.status_code == 200


@pytest.mark.unit
class TestSeeding:
    def test_an_ingest_without_a_config_starts_from_the_defaults(self, pg_conn):
        _store(pg_conn, **STRICT)
        _upload_index(pg_conn, id="legacy-seed-1")
        row = SourcesRepository(pg_conn).get_by_legacy_id("legacy-seed-1", "alice")
        assert row["config"]["retrieval"] == RetrievalConfig(**STRICT).model_dump()

    def test_an_ingest_with_a_config_keeps_its_own_fields(self, pg_conn):
        _store(pg_conn, **STRICT)
        _upload_index(pg_conn, id="legacy-seed-2", config=json.dumps({"retrieval": {"chunks": 9}}))
        retrieval = SourcesRepository(pg_conn).get_by_legacy_id("legacy-seed-2", "alice")["config"]["retrieval"]
        assert retrieval["chunks"] == 9 and retrieval["reranker"]["min_relevance"] == 0.5

    def test_without_defaults_an_ingest_stores_what_it_always_did(self, pg_conn):
        _upload_index(pg_conn, id="legacy-seed-3")
        assert SourcesRepository(pg_conn).get_by_legacy_id("legacy-seed-3", "alice")["config"] == {}

    def test_an_existing_source_is_never_reseeded(self, pg_conn):
        repo = SourcesRepository(pg_conn)
        created = repo.create("old", user_id="alice", legacy_mongo_id="legacy-seed-4",
                              config={"retrieval": {"chunks": 3}})
        _store(pg_conn, **STRICT)
        _upload_index(pg_conn, id="legacy-seed-4")
        assert repo.get_any(str(created["id"]), "alice")["config"] == created["config"]

    def test_a_new_wiki_starts_from_the_defaults(self, db):
        from docsgpt.api.user.sources.routes import CreateWikiSource

        _store(db, **STRICT)
        app = Flask(__name__)
        with patch("docsgpt.api.user.sources.routes.reembed_wiki_page.delay"), app.test_request_context(
            "/api/sources/wiki", method="POST", json={"name": "W"}
        ):
            from flask import request

            request.decoded_token = {"sub": "u-wiki"}
            response = CreateWikiSource().post()
        row = SourcesRepository(db).get_any(response.json["source_id"], "u-wiki")
        assert row["config"]["kind"] == "wiki" and row["config"]["retrieval"]["exposure"] == "agentic_tool"
        assert row["config"]["retrieval"]["reranker"]["min_relevance"] == 0.5

    def test_an_upload_or_remote_config_is_overlaid_before_validation(self, db):
        from docsgpt.api.user.sources.upload import _parse_source_config

        app = Flask(__name__)
        _store(db, **STRICT)
        with app.app_context():
            config, error = _parse_source_config(json.dumps({"retrieval": {"chunks": 2}}))
            assert error is None
            assert config["retrieval"]["chunks"] == 2 and config["retrieval"]["reranker"]["min_relevance"] == 0.5
            # A config of LLM screening replaces the default relevance instead of clashing with it.
            config, error = _parse_source_config(json.dumps({"retrieval": {"prescreen": {"candidate_k": 40}}}))
            assert error is None and config["retrieval"]["reranker"] is None
            # Without a config nothing is read here: the source is seeded when it is created.
            assert _parse_source_config(None) == (None, None)

    def test_an_upload_config_with_both_says_why(self, db):
        from docsgpt.api.user.sources.upload import _parse_source_config

        app = Flask(__name__)
        with app.app_context():
            body = {"retrieval": {"reranker": {}, "prescreen": {"candidate_k": 40}}}
            _, error = _parse_source_config(json.dumps(body))
        assert error.status_code == 400 and error.json["message"] == RELEVANCE_OR_PRESCREEN
