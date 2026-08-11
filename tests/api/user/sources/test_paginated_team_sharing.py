"""GET /api/sources/paginated surfaces team-shared sources (with ownership/access).

Regression test: the paginated settings list must include sources shared with the
caller's teams — matching the /api/sources dropdown — not just owned sources.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def client():
    from application.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@contextmanager
def _cm(value):
    yield value


def _source_row(sid, *, user_id):
    return {
        "id": sid,
        "name": f"src-{sid[:4]}",
        "user_id": user_id,
        "date": "",
        "tokens": "",
        "retriever": "classic",
        "sync_frequency": "",
        "remote_data": None,
        "directory_structure": None,
        "type": "file",
        "ingest_status": None,
    }


def _run(sub, repo, team_shared, client):
    patches = [
        patch("application.app.handle_auth", return_value={"sub": sub}),
        patch("application.app.resolve_roles", return_value=["user"]),
        patch("application.api.user.sources.routes.db_readonly", lambda: _cm(Mock())),
        patch("application.api.user.sources.routes.SourcesRepository", return_value=repo),
        patch(
            "application.api.user.sources.routes.visible_with_access",
            return_value=team_shared,
        ),
    ]
    for p in patches:
        p.start()
    try:
        return client.get("/api/sources/paginated")
    finally:
        for p in reversed(patches):
            p.stop()


@pytest.mark.unit
class TestPaginatedSourcesTeamSharing:
    def test_team_shared_source_appears_with_access(self, client):
        owned, shared = str(uuid.uuid4()), str(uuid.uuid4())
        repo = Mock()
        repo.count_for_user.return_value = 2
        repo.list_for_user.return_value = [
            _source_row(owned, user_id="bob"),
            _source_row(shared, user_id="alice"),  # not the caller → team-shared
        ]
        resp = _run("bob", repo, {shared: "editor"}, client)
        assert resp.status_code == 200
        by_id = {d["id"]: d for d in json.loads(resp.data)["paginated"]}
        assert by_id[owned]["ownership"] == "user"
        assert by_id[owned]["team_access"] is None
        assert by_id[shared]["ownership"] == "team"
        assert by_id[shared]["team_access"] == "editor"
        # The shared ids are unioned into the owner-scoped queries by id.
        assert repo.list_for_user.call_args.kwargs["extra_ids"] == [shared]
        assert repo.count_for_user.call_args.kwargs["extra_ids"] == [shared]

    def test_no_shares_returns_only_owned(self, client):
        owned = str(uuid.uuid4())
        repo = Mock()
        repo.count_for_user.return_value = 1
        repo.list_for_user.return_value = [_source_row(owned, user_id="bob")]
        resp = _run("bob", repo, {}, client)
        assert resp.status_code == 200
        docs = json.loads(resp.data)["paginated"]
        assert len(docs) == 1
        assert docs[0]["ownership"] == "user"
        assert repo.list_for_user.call_args.kwargs["extra_ids"] == []
