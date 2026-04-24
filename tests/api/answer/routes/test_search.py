"""Tests for /api/search route (application/api/answer/routes/search.py).

Retrieval logic lives in ``application/services/search_service.py`` and
has its own unit tests in ``tests/services/test_search_service.py``. The
tests below focus on what the route specifically owns:

* Request validation (400 for missing fields).
* Translation of the service's ``InvalidAPIKey`` / ``SearchFailed``
  exceptions to HTTP status codes (401 / 500).
* End-to-end happy path against a real ephemeral Postgres via
  ``pg_conn``, to catch regressions in the route's wiring to the
  service and repositories.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestSearchResourceValidation:
    def test_returns_400_when_question_missing(self, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            with flask_app.test_request_context(json={"api_key": "test_key"}):
                result = SearchResource().post()
                assert result.status_code == 400
                assert "question" in result.json["error"]

    def test_returns_400_when_api_key_missing(self, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            with flask_app.test_request_context(json={"question": "test query"}):
                result = SearchResource().post()
                assert result.status_code == 400
                assert "api_key" in result.json["error"]


@pytest.mark.unit
class TestSearchResourceExceptionMapping:
    """Verify the route maps service exceptions to HTTP status codes.

    The service function itself is patched; these tests do not care about
    the search logic — only that 401/500/200 are produced correctly from
    the three possible service outcomes.
    """

    def test_invalid_api_key_returns_401(self, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.services.search_service import InvalidAPIKey

        with flask_app.app_context(), flask_app.test_request_context(
            json={"question": "q", "api_key": "bad"}
        ), patch(
            "application.api.answer.routes.search.search",
            side_effect=InvalidAPIKey(),
        ):
            result = SearchResource().post()
        assert result.status_code == 401
        assert result.json == {"error": "Invalid API key"}

    def test_search_failed_returns_500(self, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.services.search_service import SearchFailed

        with flask_app.app_context(), flask_app.test_request_context(
            json={"question": "q", "api_key": "k"}
        ), patch(
            "application.api.answer.routes.search.search",
            side_effect=SearchFailed("boom"),
        ):
            result = SearchResource().post()
        assert result.status_code == 500
        assert result.json == {"error": "Search failed"}

    def test_happy_path_passes_service_result_through(self, flask_app):
        from application.api.answer.routes.search import SearchResource

        hits = [{"text": "t", "title": "T", "source": "s"}]
        with flask_app.app_context(), flask_app.test_request_context(
            json={"question": "q", "api_key": "k", "chunks": 7}
        ), patch(
            "application.api.answer.routes.search.search",
            return_value=hits,
        ) as mock_search:
            result = SearchResource().post()
        assert result.status_code == 200
        assert result.json == hits
        mock_search.assert_called_once_with("k", "q", 7)

    def test_default_chunks_is_5(self, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context(), flask_app.test_request_context(
            json={"question": "q", "api_key": "k"}  # no chunks field
        ), patch(
            "application.api.answer.routes.search.search",
            return_value=[],
        ) as mock_search:
            SearchResource().post()
        mock_search.assert_called_once_with("k", "q", 5)


# ---------------------------------------------------------------------------
# End-to-end against a real ephemeral Postgres.
#
# These exercise the full route → service → repository → DB path, patching
# only ``VectorCreator.create_vectorstore`` (so we don't need real embeddings
# or a vector index). ``db_readonly`` is redirected at the *service* module
# since that's where the import now lives.
# ---------------------------------------------------------------------------


@contextmanager
def _patch_search_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.services.search_service.db_readonly", _yield
    ):
        yield


class TestSearchResourcePgConn:
    def test_invalid_api_key_returns_401(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource

        with _patch_search_db(pg_conn), flask_app.app_context():
            with flask_app.test_request_context(
                json={"question": "q", "api_key": "does-not-exist"},
            ):
                result = SearchResource().post()
        assert result.status_code == 401

    def test_no_sources_returns_empty(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.storage.db.repositories.agents import AgentsRepository

        AgentsRepository(pg_conn).create(
            "u", "a", "published", key="no-src-key",
        )
        with _patch_search_db(pg_conn), flask_app.app_context():
            with flask_app.test_request_context(
                json={"question": "q", "api_key": "no-src-key"},
            ):
                result = SearchResource().post()
        assert result.status_code == 200
        assert result.json == []

    def test_search_returns_results(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.sources import SourcesRepository

        src = SourcesRepository(pg_conn).create("src", user_id="u")
        AgentsRepository(pg_conn).create(
            "u", "a", "published",
            key="search-key",
            source_id=str(src["id"]),
        )

        fake_vs = MagicMock()
        fake_vs.search.return_value = [
            {"text": "answer text", "metadata": {"title": "Doc"}},
        ]

        with _patch_search_db(pg_conn), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ), flask_app.app_context():
            with flask_app.test_request_context(
                json={"question": "q", "api_key": "search-key"},
            ):
                result = SearchResource().post()
        assert result.status_code == 200
        assert len(result.json) == 1

    def test_search_uses_extra_source_ids(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.sources import SourcesRepository

        src1 = SourcesRepository(pg_conn).create("s1", user_id="u")
        src2 = SourcesRepository(pg_conn).create("s2", user_id="u")
        AgentsRepository(pg_conn).create(
            "u", "a", "published",
            key="extra-key",
            extra_source_ids=[str(src1["id"]), str(src2["id"])],
        )

        fake_vs = MagicMock()
        fake_vs.search.return_value = [
            {"text": "one", "metadata": {"title": "A"}},
        ]
        with _patch_search_db(pg_conn), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ), flask_app.app_context():
            with flask_app.test_request_context(
                json={"question": "q", "api_key": "extra-key", "chunks": 4},
            ):
                result = SearchResource().post()
        assert result.status_code == 200
