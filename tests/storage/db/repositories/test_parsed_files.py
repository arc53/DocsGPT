"""``ParsedFilesRepository`` against a real Postgres schema."""

from __future__ import annotations

from sqlalchemy import text

from docsgpt.storage.db.repositories.parsed_files import ParsedFilesRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.principal import principal_id


def _age(conn, days: int, user: str = "alice") -> None:
    conn.execute(
        text("UPDATE parsed_files SET last_used_at = now() - make_interval(days => :d) WHERE user_id = :u"),
        {"d": days, "u": user},
    )


class TestParsedFilesRepository:
    def test_store_then_find_round_trips_a_string_and_a_list(self, pg_conn):
        repo = ParsedFilesRepository(pg_conn)
        repo.store("alice", "sha-a", "key", content="text", parser_metadata={"pdf_pages": 3}, page_count=3)
        repo.store("alice", "sha-b", "key", content=["page 1", "page 2"], billed_pages=2)

        one = repo.find("alice", "sha-a", "key")
        assert one["content"] == "text"
        assert one["parser_metadata"] == {"pdf_pages": 3}
        assert one["page_count"] == 3
        two = repo.find("alice", "sha-b", "key")
        assert two["content"] == ["page 1", "page 2"]
        assert two["billed_pages"] == 2

    def test_find_misses_another_user_and_another_parser_key(self, pg_conn):
        repo = ParsedFilesRepository(pg_conn)
        repo.store("alice", "sha", "key", content="text")
        assert repo.find("bob", "sha", "key") is None
        assert repo.find("alice", "sha", "other-key") is None

    def test_store_replaces_the_row_with_the_same_key(self, pg_conn):
        repo = ParsedFilesRepository(pg_conn)
        repo.store("alice", "sha", "key", content="old")
        repo.store("alice", "sha", "key", content=None, storage_path="parse_cache/x.json")
        row = repo.find("alice", "sha", "key")
        assert row["content"] is None
        assert row["storage_path"] == "parse_cache/x.json"
        assert pg_conn.execute(text("SELECT count(*) FROM parsed_files")).scalar() == 1

    def test_find_marks_an_old_row_used(self, pg_conn):
        repo = ParsedFilesRepository(pg_conn)
        repo.store("alice", "sha", "key", content="text")
        _age(pg_conn, 30)
        repo.find("alice", "sha", "key")
        fresh = pg_conn.execute(
            text("SELECT last_used_at > now() - interval '1 hour' FROM parsed_files")
        ).scalar()
        assert fresh is True

    def test_delete_stale_returns_the_storage_paths(self, pg_conn):
        repo = ParsedFilesRepository(pg_conn)
        repo.store("alice", "old-inline", "key", content="text")
        repo.store("alice", "old-stored", "key", storage_path="parse_cache/old.json")
        _age(pg_conn, 100)
        repo.store("alice", "recent", "key", content="text")

        assert sorted(repo.delete_stale(90), key=str) == sorted([None, "parse_cache/old.json"], key=str)
        assert pg_conn.execute(text("SELECT content_sha256 FROM parsed_files")).scalars().all() == ["recent"]

    def test_delete_for_user_and_list_for_user(self, pg_conn):
        repo = ParsedFilesRepository(pg_conn)
        repo.store("alice", "a1", "key", content="text")
        repo.store("alice", "a2", "key", storage_path="parse_cache/a2.json")
        repo.store("bob", "b1", "key", content="text")

        assert [row["content_sha256"] for row in repo.list_for_user("alice")] == ["a1", "a2"]
        assert sorted(repo.delete_for_user("alice"), key=str) == sorted([None, "parse_cache/a2.json"], key=str)
        assert repo.list_for_user("alice") == []
        assert [row["content_sha256"] for row in repo.list_for_user("bob")] == ["b1"]

    def test_storing_for_a_new_user_creates_their_users_row(self, pg_conn):
        # The ensure_user_exists trigger creates the users row the FK needs.
        ParsedFilesRepository(pg_conn).store("brand-new-user", "sha", "key", content="text")
        assert pg_conn.execute(
            text("SELECT 1 FROM users WHERE user_id = 'brand-new-user'")
        ).scalar() == 1


class TestTeamDeletion:
    def test_stored_parses_do_not_block_a_team_delete_and_go_with_it(self, pg_conn):
        teams = TeamsRepository(pg_conn)
        team = teams.create(name="Acme", slug="acme-parses", owner_id="alice")
        principal = principal_id(team["id"])
        repo = ParsedFilesRepository(pg_conn)
        repo.store(principal, "sha", "key", storage_path="parse_cache/team.json")
        repo.store(principal, "sha2", "key", content="inline")

        assert "parsed_files" not in teams.principal_holdings(team["id"])
        paths: list = []
        assert teams.delete(team["id"], artifact_paths=paths) is True
        assert paths == ["parse_cache/team.json"]
        assert repo.list_for_user(principal) == []
