"""Real-PG tests for internal_search directory-structure loading."""

from contextlib import contextmanager
from unittest.mock import patch



@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.storage.db.session.db_readonly", _yield
    ):
        yield


class TestGetDirectoryStructureFromDb:
    def test_returns_none_for_empty_active_docs(self):
        from application.agents.tools.internal_search import InternalSearchTool

        tool = InternalSearchTool({"source": {}})
        assert tool._get_directory_structure() is None

    def test_loads_single_source_structure(self, pg_conn):
        from application.agents.tools.internal_search import InternalSearchTool
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        user = "u-ds"
        src = SourcesRepository(pg_conn).create(
            "hello",
            user_id=user,
            directory_structure={"file.txt": {"type": "file", "size_bytes": 10}},
        )
        tool = InternalSearchTool({
            "source": {"active_docs": str(src["id"])},
            "decoded_token": {"sub": user},
        })

        with _patch_db(pg_conn):
            got = tool._get_directory_structure()
        assert got is not None
        assert "file.txt" in got

    def test_loads_multiple_sources_merges(self, pg_conn):
        from application.agents.tools.internal_search import InternalSearchTool
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        user = "u-ds-multi"
        repo = SourcesRepository(pg_conn)
        src1 = repo.create(
            "src1", user_id=user,
            directory_structure={"a.txt": {"type": "file", "size_bytes": 5}},
        )
        src2 = repo.create(
            "src2", user_id=user,
            directory_structure={"b.txt": {"type": "file", "size_bytes": 5}},
        )
        tool = InternalSearchTool({
            "source": {"active_docs": [str(src1["id"]), str(src2["id"])]},
            "decoded_token": {"sub": user},
        })

        with _patch_db(pg_conn):
            got = tool._get_directory_structure()
        assert got is not None
        # Multi-source merging uses source name as key
        assert "src1" in got or "a.txt" in got

    def test_skips_missing_source(self, pg_conn):
        from application.agents.tools.internal_search import InternalSearchTool

        tool = InternalSearchTool({
            "source": {"active_docs": "00000000-0000-0000-0000-000000000000"},
            "decoded_token": {"sub": "u"},
        })
        with _patch_db(pg_conn):
            got = tool._get_directory_structure()
        assert got is None


class TestSourcesHaveDirectoryStructureDb:
    def test_false_no_active_docs(self):
        from application.agents.tools.internal_search import (
            sources_have_directory_structure,
        )
        assert sources_have_directory_structure({}) is False

    def test_true_when_source_has_structure(self, pg_conn):
        from application.agents.tools.internal_search import (
            sources_have_directory_structure,
        )
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        src = SourcesRepository(pg_conn).create(
            "s", user_id="u",
            directory_structure={"a.txt": {"type": "file", "size_bytes": 5}},
        )
        with _patch_db(pg_conn):
            got = sources_have_directory_structure(
                {"active_docs": str(src["id"])}
            )
        assert got is True

    def test_false_when_source_has_no_structure(self, pg_conn):
        from application.agents.tools.internal_search import (
            sources_have_directory_structure,
        )
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        src = SourcesRepository(pg_conn).create("s", user_id="u")
        with _patch_db(pg_conn):
            got = sources_have_directory_structure(
                {"active_docs": str(src["id"])}
            )
        assert got is False

    def test_legacy_id_lookup(self, pg_conn):
        from application.agents.tools.internal_search import (
            sources_have_directory_structure,
        )
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        SourcesRepository(pg_conn).create(
            "s", user_id="u",
            legacy_mongo_id="507f1f77bcf86cd799439011",
            directory_structure={"x.txt": {"type": "file", "size_bytes": 5}},
        )
        with _patch_db(pg_conn):
            got = sources_have_directory_structure(
                {"active_docs": "507f1f77bcf86cd799439011"}
            )
        assert got is True
