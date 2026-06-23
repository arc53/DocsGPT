"""Tests for the GraphRAG enable route in application/api/user/sources/routes.py.

``graphrag_available`` and ``extract_graph.delay`` are mocked so no live
vector store, LLM, or model calls run; the ``sources`` row is real so the
authz lookup and config write read back.
"""

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask

from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.source_config import SourceConfig


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.sources.routes.db_session", _yield
    ), patch(
        "application.api.user.sources.routes.db_readonly", _yield
    ):
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
    TeamMembersRepository(pg_conn).add_member(
        team["id"], member, role="team_member"
    )
    TeamResourceGrantsRepository(pg_conn).grant(
        team["id"], "source", source_id, owner_id=owner, granted_by=owner,
        access_level=access_level,
    )


@pytest.mark.unit
class TestEnableSourceGraphRAG:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import EnableSourceGraphRAG

        with app.test_request_context(
            "/api/sources/x/graphrag/enable", method="POST"
        ):
            from flask import request
            request.decoded_token = None
            response = EnableSourceGraphRAG().post("x")
        assert response.status_code == 401

    def test_unavailable_returns_400(self, app, pg_conn):
        from application.api.user.sources.routes import EnableSourceGraphRAG

        user = "u-graph-unavail"
        src = SourcesRepository(pg_conn).create(
            "files", user_id=user, type="file",
            directory_structure={"a.md": {"type": "text/markdown"}},
        )
        sid = str(src["id"])

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.graphrag_available",
            return_value=False,
        ), patch(
            "application.api.user.sources.routes.extract_graph.delay"
        ) as mock_extract, app.test_request_context(
            f"/api/sources/{sid}/graphrag/enable", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = EnableSourceGraphRAG().post(sid)

        assert response.status_code == 400
        mock_extract.assert_not_called()
        got = SourcesRepository(pg_conn).get_any(sid, user)
        assert SourceConfig.parse(got.get("config")).kind == "classic"

    def test_owner_sets_config_and_enqueues(self, app, pg_conn):
        from application.api.user.sources.routes import EnableSourceGraphRAG

        user = "u-graph-owner"
        src = SourcesRepository(pg_conn).create(
            "files", user_id=user, type="file",
            directory_structure={"a.md": {"type": "text/markdown"}},
        )
        sid = str(src["id"])

        fake_task = type("T", (), {"id": "task-g"})()
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.graphrag_available",
            return_value=True,
        ), patch(
            "application.api.user.sources.routes.extract_graph.delay",
            return_value=fake_task,
        ) as mock_extract, app.test_request_context(
            f"/api/sources/{sid}/graphrag/enable", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = EnableSourceGraphRAG().post(sid)

        assert response.status_code == 200
        assert response.json["success"] is True
        assert response.json["task_id"] == "task-g"

        got = SourcesRepository(pg_conn).get_any(sid, user)
        cfg = SourceConfig.parse(got.get("config"))
        assert cfg.kind == "graphrag"
        assert cfg.retrieval.retriever == "graphrag"

        mock_extract.assert_called_once()
        assert mock_extract.call_args.args[0] == sid
        assert mock_extract.call_args.args[1] == user
        # The key varies with the fresh ``updated_at`` the config write bumped,
        # so each enable produces a new key that re-runs the worker.
        key = mock_extract.call_args.kwargs["idempotency_key"]
        assert key.startswith(f"extract-graph:{sid}:")
        assert key != f"extract-graph:{sid}:"

    def test_viewer_rejected_403(self, app, pg_conn):
        from application.api.user.sources.routes import EnableSourceGraphRAG

        owner = "alice-graph"
        viewer = "bob-graph-viewer"
        src = SourcesRepository(pg_conn).create(
            "files", user_id=owner, type="file",
            directory_structure={"a.md": {"type": "text/markdown"}},
        )
        sid = str(src["id"])
        _grant_team_access(pg_conn, owner, viewer, sid, "viewer")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.graphrag_available",
            return_value=True,
        ), patch(
            "application.api.user.sources.routes.extract_graph.delay"
        ) as mock_extract, app.test_request_context(
            f"/api/sources/{sid}/graphrag/enable", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": viewer}
            response = EnableSourceGraphRAG().post(sid)

        assert response.status_code == 403
        mock_extract.assert_not_called()
        got = SourcesRepository(pg_conn).get_any(sid, owner)
        assert SourceConfig.parse(got.get("config")).kind == "classic"


@pytest.mark.unit
class TestConfigPatchCannotSetGraphrag:
    """The config PATCH endpoint must not flip kind to graphrag (D28)."""

    def test_patch_kind_graphrag_rejected_400(self, app, pg_conn):
        from application.api.user.sources.routes import SourceConfigResource

        user = "u-patch-graph"
        src = SourcesRepository(pg_conn).create(
            "files", user_id=user, type="file",
            directory_structure={"a.md": {"type": "text/markdown"}},
        )
        sid = str(src["id"])

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/config",
            method="PATCH",
            json={"kind": "graphrag"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceConfigResource().patch(sid)

        assert response.status_code == 400
        got = SourcesRepository(pg_conn).get_any(sid, user)
        assert SourceConfig.parse(got.get("config")).kind == "classic"
