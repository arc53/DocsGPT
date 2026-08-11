"""Tests for application/api/user/sources/retrieval_test.py."""

import json
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("application.api.user.sources.retrieval_test.db_readonly", _yield):
        yield


def _grant_team_access(pg_conn, owner, member, source_id, access_level):
    from application.storage.db.repositories.team_members import (
        TeamMembersRepository,
    )
    from application.storage.db.repositories.team_resource_grants import (
        TeamResourceGrantsRepository,
    )
    from application.storage.db.repositories.teams import TeamsRepository

    team = TeamsRepository(pg_conn).create(
        "Acme", f"acme-{uuid.uuid4().hex[:8]}", owner
    )
    TeamMembersRepository(pg_conn).add_member(team["id"], member, role="team_member")
    TeamResourceGrantsRepository(pg_conn).grant(
        team["id"],
        "source",
        source_id,
        owner_id=owner,
        granted_by=owner,
        access_level=access_level,
    )


def _seed_source(pg_conn, user="u", name="src", config=None):
    from application.storage.db.repositories.sources import SourcesRepository

    repo = SourcesRepository(pg_conn)
    src = repo.create(name, user_id=user)
    if config is not None:
        repo.update(str(src["id"]), user, {"config": config})
        src = repo.get_any(str(src["id"]), user)
    return src


def _post(app, source_id, body, user="u"):
    from application.api.user.sources.retrieval_test import SourceSearch

    with app.test_request_context(
        f"/api/sources/{source_id}/search",
        method="POST",
        data=json.dumps(body),
        content_type="application/json",
    ):
        from flask import request

        request.decoded_token = {"sub": user}
        return SourceSearch().post(source_id)


class TestSourceSearchGuards:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.retrieval_test import SourceSearch

        with app.test_request_context(
            "/api/sources/abc/search",
            method="POST",
            data=json.dumps({"query": "hi"}),
            content_type="application/json",
        ):
            from flask import request

            request.decoded_token = None
            response = SourceSearch().post("abc")
        assert response.status_code == 401

    def test_returns_400_without_query(self, app, pg_conn):
        src = _seed_source(pg_conn, user="u-noq")
        with _patch_db(pg_conn):
            response = _post(app, str(src["id"]), {"query": "   "}, user="u-noq")
        assert response.status_code == 400

    def test_returns_400_for_overlong_query(self, app, pg_conn):
        from application.api.user.sources.retrieval_test import MAX_QUERY_LENGTH

        src = _seed_source(pg_conn, user="u-long")
        with _patch_db(pg_conn):
            response = _post(
                app,
                str(src["id"]),
                {"query": "x" * (MAX_QUERY_LENGTH + 1)},
                user="u-long",
            )
        assert response.status_code == 400

    def test_returns_404_when_source_missing(self, app, pg_conn):
        with _patch_db(pg_conn):
            response = _post(
                app,
                "00000000-0000-0000-0000-000000000000",
                {"query": "hi"},
                user="u",
            )
        assert response.status_code == 404

    def test_returns_400_for_invalid_retrieval_config(self, app, pg_conn):
        src = _seed_source(pg_conn, user="u-bad")
        with _patch_db(pg_conn):
            response = _post(
                app,
                str(src["id"]),
                # chunks must be >= 1 (RetrievalConfig._bounded_chunks)
                {"query": "hi", "retrieval": {"chunks": 0}},
                user="u-bad",
            )
        assert response.status_code == 400

    def test_rejects_unknown_retrieval_field(self, app, pg_conn):
        src = _seed_source(pg_conn, user="u-extra")
        with _patch_db(pg_conn):
            response = _post(
                app,
                str(src["id"]),
                # RetrievalConfig forbids extras — a typo must not silently no-op
                {"query": "hi", "retrieval": {"chunkz": 5}},
                user="u-extra",
            )
        assert response.status_code == 400


class TestSourceSearchAccess:
    """Read access = owner or any team grant, matching the wiki/graph reads."""

    def test_stranger_gets_404(self, app, pg_conn):
        src = _seed_source(pg_conn, user="u-owner-x")

        fake = MagicMock()
        fake.search.return_value = [{"text": "secret", "filename": "f.md"}]

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.Dispatcher",
            return_value=fake,
        ) as dispatcher:
            response = _post(
                app, str(src["id"]), {"query": "q"}, user="u-stranger-x"
            )

        assert response.status_code == 404
        # Never even touch the vector store for a source we can't read.
        dispatcher.assert_not_called()

    def test_team_viewer_can_run_a_test(self, app, pg_conn):
        owner = "alice-retrieval"
        viewer = "bob-retrieval-viewer"
        src = _seed_source(pg_conn, user=owner)
        _grant_team_access(pg_conn, owner, viewer, str(src["id"]), "viewer")

        fake = MagicMock()
        fake.search.return_value = [{"text": "shared chunk", "filename": "f.md"}]

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.Dispatcher",
            return_value=fake,
        ):
            response = _post(app, str(src["id"]), {"query": "q"}, user=viewer)

        assert response.status_code == 200
        assert response.json["total"] == 1


class TestSourceSearchRetrieval:
    def test_returns_ranked_chunks_with_scores(self, app, pg_conn):
        user = "u-search"
        src = _seed_source(pg_conn, user=user)

        fake = MagicMock()
        fake.search.return_value = [
            {
                "text": "chunk one",
                "title": "T1",
                "filename": "f.md",
                "source": "f.md",
                "score": 0.82,
                "score_kind": "cosine_similarity",
            },
            {
                "text": "chunk two",
                "title": "T2",
                "filename": "f.md",
                "source": "f.md",
                "score": 0.71,
                "score_kind": "cosine_similarity",
            },
        ]

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.Dispatcher",
            return_value=fake,
        ):
            response = _post(app, str(src["id"]), {"query": "what runs"}, user=user)

        assert response.status_code == 200
        data = response.json
        assert data["total"] == 2
        assert [c["rank"] for c in data["chunks"]] == [1, 2]
        assert data["chunks"][0]["score"] == 0.82
        assert data["chunks"][0]["score_kind"] == "cosine_similarity"
        assert data["chunks"][0]["tokens"] > 0
        fake.search.assert_called_once_with("what runs")

    def test_unscored_retriever_yields_null_scores(self, app, pg_conn):
        """graphrag ranks by PPR and attaches no score — it must not be faked."""
        user = "u-noscore"
        src = _seed_source(pg_conn, user=user)

        fake = MagicMock()
        fake.search.return_value = [{"text": "graph chunk", "filename": "g.md"}]

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.Dispatcher",
            return_value=fake,
        ):
            response = _post(app, str(src["id"]), {"query": "q"}, user=user)

        assert response.status_code == 200
        assert response.json["chunks"][0]["score"] is None
        assert response.json["chunks"][0]["score_kind"] is None

    def test_ad_hoc_config_is_passed_to_dispatcher_and_not_persisted(
        self, app, pg_conn
    ):
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-adhoc"
        src = _seed_source(pg_conn, user=user)

        fake = MagicMock()
        fake.search.return_value = []

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.Dispatcher",
            return_value=fake,
        ) as dispatcher:
            response = _post(
                app,
                str(src["id"]),
                {"query": "q", "retrieval": {"chunks": 7, "score_threshold": 0.5}},
                user=user,
            )

        assert response.status_code == 200
        kwargs = dispatcher.call_args.kwargs
        assert kwargs["chunks"] == 7
        assert kwargs["include_scores"] is True
        assert kwargs["usage_source"] == "retrieval_test"
        retrieval = kwargs["sources"][0]["retrieval"]
        assert retrieval.chunks == 7
        assert retrieval.score_threshold == 0.5
        # Echoed back so the UI can show what actually ran.
        assert response.json["retrieval"]["chunks"] == 7

        # The source's stored config must be untouched by a test run.
        stored = SourcesRepository(pg_conn).get_any(str(src["id"]), user)
        assert (stored.get("config") or {}).get("retrieval") is None

    def test_falls_back_to_saved_config(self, app, pg_conn):
        user = "u-saved"
        src = _seed_source(
            pg_conn,
            user=user,
            config={"retrieval": {"chunks": 9, "retriever": "classic"}},
        )

        fake = MagicMock()
        fake.search.return_value = []

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.Dispatcher",
            return_value=fake,
        ) as dispatcher:
            response = _post(app, str(src["id"]), {"query": "q"}, user=user)

        assert response.status_code == 200
        assert dispatcher.call_args.kwargs["chunks"] == 9
        assert response.json["retrieval"]["chunks"] == 9

    def test_returns_500_when_retrieval_raises(self, app, pg_conn):
        user = "u-boom"
        src = _seed_source(pg_conn, user=user)

        fake = MagicMock()
        fake.search.side_effect = RuntimeError("vector store down")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.Dispatcher",
            return_value=fake,
        ):
            response = _post(app, str(src["id"]), {"query": "q"}, user=user)

        assert response.status_code == 500


class TestPrescreenCostCeiling:
    """One request must not be able to fan out into hundreds of LLM calls."""

    def test_rejects_a_prescreen_config_that_needs_too_many_llm_calls(
        self, app, pg_conn
    ):
        src = _seed_source(pg_conn, user="u-costly")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.Dispatcher"
        ) as dispatcher:
            response = _post(
                app,
                str(src["id"]),
                {
                    "query": "q",
                    # 500 candidates screened one at a time = 500 provider calls.
                    "retrieval": {
                        "chunks": 1,
                        "prescreen": {
                            "candidate_k": 500,
                            "batch_size": 1,
                            "max_keep": 1,
                        },
                    },
                },
                user="u-costly",
            )

        assert response.status_code == 400
        dispatcher.assert_not_called()

    def test_allows_a_prescreen_config_within_the_ceiling(self, app, pg_conn):
        src = _seed_source(pg_conn, user="u-ok")

        fake = MagicMock()
        fake.search.return_value = []

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.Dispatcher",
            return_value=fake,
        ) as dispatcher:
            response = _post(
                app,
                str(src["id"]),
                {
                    "query": "q",
                    # 40 candidates / batches of 10 = 4 calls.
                    "retrieval": {
                        "chunks": 2,
                        "prescreen": {
                            "candidate_k": 40,
                            "batch_size": 10,
                            "max_keep": 8,
                        },
                    },
                },
                user="u-ok",
            )

        assert response.status_code == 200
        dispatcher.assert_called_once()

    def test_saved_config_is_testable_even_above_the_ceiling(self, app, pg_conn):
        """The client echoes the on-screen config back, so an untouched saved
        config arrives in the body. It must still be judged 'saved', or a source
        configured beyond the ceiling could never be tested — which is the whole
        point of the endpoint."""
        expensive = {
            "chunks": 2,
            "prescreen": {"candidate_k": 300, "batch_size": 10, "max_keep": 8},
        }
        src = _seed_source(
            pg_conn, user="u-saved-costly", config={"retrieval": expensive}
        )

        fake = MagicMock()
        fake.search.return_value = []

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.Dispatcher",
            return_value=fake,
        ) as dispatcher:
            response = _post(
                app,
                str(src["id"]),
                # 30 batches — over the ad-hoc ceiling, but it IS the saved config.
                {"query": "q", "retrieval": expensive},
                user="u-saved-costly",
            )

        assert response.status_code == 200
        dispatcher.assert_called_once()

    def test_editing_the_saved_config_upward_is_still_capped(self, app, pg_conn):
        saved = {
            "chunks": 2,
            "prescreen": {"candidate_k": 300, "batch_size": 10, "max_keep": 8},
        }
        src = _seed_source(pg_conn, user="u-edit-costly", config={"retrieval": saved})

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.Dispatcher"
        ) as dispatcher:
            response = _post(
                app,
                str(src["id"]),
                {
                    "query": "q",
                    # Same source, but the caller cranked batch_size down to 1
                    # → 300 LLM calls. That is ad-hoc, and capped.
                    "retrieval": {
                        "chunks": 2,
                        "prescreen": {
                            "candidate_k": 300,
                            "batch_size": 1,
                            "max_keep": 8,
                        },
                    },
                },
                user="u-edit-costly",
            )

        assert response.status_code == 400
        dispatcher.assert_not_called()


class TestModelResolution:
    def test_passes_the_instance_default_model(self, app, pg_conn):
        """Without a real model id the prescreen stage calls the provider with a
        placeholder, fails, and silently keeps every candidate."""
        src = _seed_source(pg_conn, user="u-model")

        fake = MagicMock()
        fake.search.return_value = []

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.get_default_model_id",
            return_value="gpt-4o",
        ), patch(
            "application.api.user.sources.retrieval_test.Dispatcher",
            return_value=fake,
        ) as dispatcher:
            response = _post(app, str(src["id"]), {"query": "q"}, user="u-model")

        assert response.status_code == 200
        assert dispatcher.call_args.kwargs["model_id"] == "gpt-4o"

    def test_no_configured_models_leaves_the_retriever_default(self, app, pg_conn):
        """get_default_model_id() is None on an instance with no models; passing
        that through would override the retriever's own default with None."""
        src = _seed_source(pg_conn, user="u-nomodel")

        fake = MagicMock()
        fake.search.return_value = []

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.retrieval_test.get_default_model_id",
            return_value=None,
        ), patch(
            "application.api.user.sources.retrieval_test.Dispatcher",
            return_value=fake,
        ) as dispatcher:
            response = _post(app, str(src["id"]), {"query": "q"}, user="u-nomodel")

        assert response.status_code == 200
        assert "model_id" not in dispatcher.call_args.kwargs
