"""Extra tests for ConnectorSessionsRepository covering remaining branches."""

import pytest


class TestGetByUserAndProvider:
    def test_not_found_returns_none(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        assert (
            ConnectorSessionsRepository(pg_conn).get_by_user_provider(
                "u", "gdrive",
            )
            is None
        )

    def test_with_server_url_filter(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        row = repo.upsert(
            "u1", "gdrive", server_url="https://drive/api",
            status="authorized",
        )
        got = repo.get_by_user_provider(
            "u1", "gdrive", server_url="https://drive/api",
        )
        assert got is not None
        assert str(got["id"]) == str(row["id"])

    def test_with_mismatched_server_url(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        repo.upsert(
            "u2", "gdrive", server_url="https://a",
            status="authorized",
        )
        got = repo.get_by_user_provider(
            "u2", "gdrive", server_url="https://b",
        )
        assert got is None


class TestGetByUserAndServerUrl:
    def test_returns_row(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        row = repo.upsert(
            "u", "mcp", server_url="https://mcp-server/",
            status="authorized",
        )
        got = repo.get_by_user_and_server_url("u", "https://mcp-server/")
        assert got is not None
        assert str(got["id"]) == str(row["id"])

    def test_not_found(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        got = ConnectorSessionsRepository(pg_conn).get_by_user_and_server_url(
            "u", "https://nope",
        )
        assert got is None


class TestGetByLegacyId:
    def test_not_found(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        got = ConnectorSessionsRepository(pg_conn).get_by_legacy_id("x")
        assert got is None

    def test_with_user_scope(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        repo.upsert(
            "u-legacy", "gdrive", status="authorized",
            legacy_mongo_id="legacy-s-1",
        )
        assert repo.get_by_legacy_id("legacy-s-1", user_id="u-legacy") is not None
        assert repo.get_by_legacy_id("legacy-s-1", user_id="other") is None


class TestConnectorSessionsUpdate:
    def test_no_filtered_fields_returns_false(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        session = repo.upsert("u", "gdrive", status="pending")
        got = repo.update(str(session["id"]), {"bogus": "x"})
        assert got is False

    def test_updates_status_and_token(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        session = repo.upsert("u", "gdrive", status="pending")
        got = repo.update(
            str(session["id"]),
            {"session_token": "st-new", "status": "authorized"},
        )
        assert got is True

    def test_updates_token_info_jsonb(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        session = repo.upsert("u", "gdrive", status="pending")
        got = repo.update(
            str(session["id"]),
            {"token_info": {"access_token": "at", "expires_in": 3600}},
        )
        assert got is True

    def test_update_by_legacy_no_fields(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        got = ConnectorSessionsRepository(pg_conn).update_by_legacy_id(
            "x", {"bogus": "v"},
        )
        assert got is False

    def test_update_by_legacy_no_match(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        got = ConnectorSessionsRepository(pg_conn).update_by_legacy_id(
            "no-match",
            {"session_token": "new"},
        )
        assert got is False

    def test_update_by_legacy_updates_match(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        repo.upsert(
            "u", "gdrive", status="pending",
            legacy_mongo_id="leg-abc",
        )

        got = repo.update_by_legacy_id(
            "leg-abc", {"session_token": "new"},
        )
        assert got is True
