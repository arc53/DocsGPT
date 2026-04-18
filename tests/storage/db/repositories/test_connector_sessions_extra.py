"""Extra tests for ConnectorSessionsRepository covering remaining branches."""



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


class TestMergeSessionData:
    """Covers ``merge_session_data`` — regression guard for the bug
    where ``server_url`` was kept only inside the JSONB blob, leaving
    the scalar column NULL and breaking
    ``get_by_user_and_server_url`` (``NULL = 'x'`` is UNKNOWN)."""

    def test_insert_populates_scalar_server_url(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        base_url = "https://mcp.example.com"

        inserted = repo.merge_session_data(
            "u-merge", "mcp:https://mcp.example.com", base_url,
            {"tokens": {"access_token": "at"}},
        )
        assert inserted["server_url"] == base_url

        got = repo.get_by_user_and_server_url("u-merge", base_url)
        assert got is not None
        assert got["server_url"] == base_url
        assert got["session_data"] == {"tokens": {"access_token": "at"}}

    def test_strips_server_url_key_from_patch(self, pg_conn):
        """Legacy callers still embed ``server_url`` in the patch — the
        scalar column is authoritative so the key should be discarded
        rather than duplicated into the JSONB payload."""
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        base_url = "https://mcp.strip.example.com"
        inserted = repo.merge_session_data(
            "u-strip", "mcp:https://mcp.strip.example.com", base_url,
            {
                "server_url": "https://different-url-should-be-ignored",
                "tokens": {"access_token": "x"},
            },
        )
        assert inserted["server_url"] == base_url
        assert "server_url" not in (inserted["session_data"] or {})

    def test_shallow_merge_preserves_other_keys(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        base_url = "https://mcp.merge.example.com"
        provider = "mcp:https://mcp.merge.example.com"

        repo.merge_session_data(
            "u-multi", provider, base_url,
            {"tokens": {"access_token": "a"}},
        )
        repo.merge_session_data(
            "u-multi", provider, base_url,
            {"client_info": {"client_id": "c"}},
        )

        row = repo.get_by_user_and_server_url("u-multi", base_url)
        assert row["session_data"] == {
            "tokens": {"access_token": "a"},
            "client_info": {"client_id": "c"},
        }

    def test_none_valued_keys_are_dropped(self, pg_conn):
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )
        repo = ConnectorSessionsRepository(pg_conn)
        base_url = "https://mcp.drop.example.com"
        provider = "mcp:https://mcp.drop.example.com"

        repo.merge_session_data(
            "u-drop", provider, base_url,
            {
                "tokens": {"access_token": "a"},
                "client_info": {"client_id": "c"},
            },
        )
        repo.merge_session_data(
            "u-drop", provider, base_url,
            {"tokens": None, "client_info": None},
        )

        row = repo.get_by_user_and_server_url("u-drop", base_url)
        assert row is not None
        assert "tokens" not in (row["session_data"] or {})
        assert "client_info" not in (row["session_data"] or {})


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
