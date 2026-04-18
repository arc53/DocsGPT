"""Tests for Confluence auth get_token_info_from_session using pg_conn."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.storage.db.session.db_readonly", _yield
    ):
        yield


class TestGetTokenInfoFromSession:
    def test_invalid_session_token_raises(self, pg_conn):
        from application.parser.connectors.confluence.auth import (
            ConfluenceAuth,
        )

        auth = ConfluenceAuth.__new__(ConfluenceAuth)
        with _patch_db(pg_conn), pytest.raises(ValueError):
            auth.get_token_info_from_session("no-such-token")

    def test_missing_token_info_raises(self, pg_conn):
        from application.parser.connectors.confluence.auth import (
            ConfluenceAuth,
        )
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        repo = ConnectorSessionsRepository(pg_conn)
        repo.upsert("u", "confluence", status="authorized")
        # Set session_token but no token_info
        session = repo.get_by_user_provider("u", "confluence")
        repo.update(str(session["id"]), {"session_token": "tok-no-info"})

        auth = ConfluenceAuth.__new__(ConfluenceAuth)
        with _patch_db(pg_conn), pytest.raises(ValueError):
            auth.get_token_info_from_session("tok-no-info")

    def test_missing_required_fields_raises(self, pg_conn):
        from application.parser.connectors.confluence.auth import (
            ConfluenceAuth,
        )
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        repo = ConnectorSessionsRepository(pg_conn)
        repo.upsert("u", "confluence", status="authorized")
        session = repo.get_by_user_provider("u", "confluence")
        repo.update(
            str(session["id"]),
            {
                "session_token": "tok-partial",
                "token_info": {"access_token": "at"},  # missing refresh + cloud_id
            },
        )

        auth = ConfluenceAuth.__new__(ConfluenceAuth)
        with _patch_db(pg_conn), pytest.raises(ValueError):
            auth.get_token_info_from_session("tok-partial")

    def test_complete_token_info_returned(self, pg_conn):
        from application.parser.connectors.confluence.auth import (
            ConfluenceAuth,
        )
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        repo = ConnectorSessionsRepository(pg_conn)
        repo.upsert("u", "confluence", status="authorized")
        session = repo.get_by_user_provider("u", "confluence")
        repo.update(
            str(session["id"]),
            {
                "session_token": "tok-good",
                "token_info": {
                    "access_token": "at",
                    "refresh_token": "rt",
                    "cloud_id": "cid-1",
                },
            },
        )

        auth = ConfluenceAuth.__new__(ConfluenceAuth)
        with _patch_db(pg_conn):
            got = auth.get_token_info_from_session("tok-good")
        assert got["access_token"] == "at"
        assert got["cloud_id"] == "cid-1"
