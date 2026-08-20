"""Schema ownership and connection pooling for ``PGVectorStore``.

Constructing a store used to run six DDL statements plus a fresh unpooled
connect, on every instantiation — and the retriever builds one store per source
per request. Schema is now owned at boot (``ensure_vector_schema``); the query
path is pure reads over a pooled connection, and the write path keeps a
one-shot safety net for processes that never ran the boot hook.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from application.vectorstore import pgvector as pgvector_module

CONNECTION_STRING = "postgresql://user:pass@localhost/db"


def _make_store(source_id="test-source", connection_string=CONNECTION_STRING):
    """Build a store with every external dependency mocked, no DDL patching."""
    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings"
    ) as mock_get_emb, patch(
        "application.vectorstore.pgvector.settings"
    ) as mock_settings, patch.dict(
        "sys.modules",
        {
            "psycopg": MagicMock(),
            "pgvector": MagicMock(),
            "pgvector.psycopg": MagicMock(),
        },
    ):
        mock_emb = Mock()
        mock_emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3])
        mock_emb.embed_documents = Mock(return_value=[[0.1, 0.2, 0.3]])
        mock_emb.dimension = 768
        mock_get_emb.return_value = mock_emb
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.PGVECTOR_CONNECTION_STRING = connection_string

        from application.vectorstore.pgvector import PGVectorStore

        store = PGVectorStore(
            source_id=source_id,
            embeddings_key="key",
            connection_string=connection_string,
        )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.closed = False
    store._connection = mock_conn
    store._pooled = False
    store._ensure_table_exists = Mock()
    return store, mock_conn, mock_cursor, mock_emb


@pytest.mark.unit
class TestConstructionTouchesNothing:
    def test_init_opens_no_connection_and_runs_no_ddl(self):
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings"
        ) as mock_get_emb, patch(
            "application.vectorstore.pgvector.settings"
        ) as mock_settings, patch.dict(
            "sys.modules",
            {
                "psycopg": MagicMock(),
                "pgvector": MagicMock(),
                "pgvector.psycopg": MagicMock(),
            },
        ):
            mock_get_emb.return_value = Mock(dimension=768)
            mock_settings.EMBEDDINGS_NAME = "test_model"
            mock_settings.PGVECTOR_CONNECTION_STRING = CONNECTION_STRING

            from application.vectorstore.pgvector import PGVectorStore

            with patch.object(
                PGVectorStore, "_get_connection"
            ) as mock_get_conn, patch.object(
                PGVectorStore, "_ensure_table_exists"
            ) as mock_ensure:
                store = PGVectorStore(
                    source_id="s1", connection_string=CONNECTION_STRING
                )

            mock_get_conn.assert_not_called()
            mock_ensure.assert_not_called()
            assert store._schema_ensured is False

    def test_pool_size_falls_back_when_setting_is_not_an_int(self):
        # The unit suite patches ``settings`` with a MagicMock; a MagicMock
        # attribute must not become the pool size.
        store, _, _, _ = _make_store()
        assert store._pool_max_size == 8


@pytest.mark.unit
class TestPoolSizingHasOneHome:
    """``pgconn`` owns the pool defaults; both stores bind to it, not copies.

    ``pool_for`` keys its registry by DSN and honours ``max_size`` only when it
    first builds the pool, so if the vector store and the graph store carried
    their own defaults the effective size would depend on which one touched
    the DSN first.
    """

    def test_both_stores_share_one_implementation(self):
        from application.graphrag import store as store_module
        from application.vectorstore import pgconn

        assert pgvector_module.DEFAULT_POOL_MAX_SIZE is pgconn.DEFAULT_POOL_MAX_SIZE
        assert store_module.DEFAULT_POOL_MAX_SIZE is pgconn.DEFAULT_POOL_MAX_SIZE
        assert store_module._resolve_pool_max_size is pgconn.resolve_pool_max_size
        assert (
            pgvector_module.PGVectorStore._resolve_pool_max_size
            is pgconn.resolve_pool_max_size
        )

    @pytest.mark.parametrize(
        "value,expected",
        [(0, 0), (2, 2), (None, 8), ("4", 8), (True, 8), (-1, 8)],
    )
    def test_pool_size_is_resolved_defensively(self, monkeypatch, value, expected):
        from application.core import settings as settings_module
        from application.vectorstore import pgconn

        monkeypatch.setattr(
            settings_module.settings, "PGVECTOR_POOL_MAX_SIZE", value, raising=False
        )

        assert pgconn.resolve_pool_max_size() == expected


@pytest.mark.unit
class TestWritePathEnsuresSchemaOnce:
    def test_add_texts_ensures_once_across_two_calls(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.fetchone.return_value = (1,)

        store.add_texts(["a"])
        store.add_texts(["b"])

        assert store._ensure_table_exists.call_count == 1

    def test_add_chunk_ensures_once_across_two_calls(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.fetchone.return_value = (1,)

        store.add_chunk("a")
        store.add_chunk("b")

        assert store._ensure_table_exists.call_count == 1

    def test_reads_and_deletes_never_ensure_schema(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (0,)
        mock_cursor.rowcount = 0

        store.search("q")
        store.keyword_search("q")
        store.get_chunks()
        store.delete_index()
        store.delete_chunk("1")

        store._ensure_table_exists.assert_not_called()


@pytest.mark.unit
class TestCreateSchema:
    def test_emits_the_ddl_and_leaves_the_commit_to_the_caller(self):
        from application.vectorstore.pgvector import PGVectorStore

        conn, cursor = MagicMock(), MagicMock()
        conn.cursor.return_value = cursor

        PGVectorStore.create_schema(conn, dimension=8)

        statements = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "CREATE EXTENSION IF NOT EXISTS vector" in statements
        assert "CREATE TABLE IF NOT EXISTS documents" in statements
        assert "vector(8)" in statements
        assert "documents_source_id_idx" in statements
        assert "documents_text_fts_idx" in statements
        assert cursor.execute.call_count == 4
        conn.commit.assert_not_called()

    def test_ensure_table_exists_locks_then_commits(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        del store._ensure_table_exists  # exercise the real method

        store._ensure_table_exists()

        statements = " ".join(str(c) for c in mock_cursor.execute.call_args_list)
        assert "pg_advisory_xact_lock" in statements
        assert "CREATE TABLE IF NOT EXISTS documents" in statements
        mock_conn.commit.assert_called_once()


@pytest.mark.unit
class TestTableDimension:
    def _conn(self, rows):
        conn, cursor = MagicMock(), MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.side_effect = rows
        return conn

    def test_parses_the_declared_vector_width(self):
        from application.vectorstore.pgvector import PGVectorStore

        conn = self._conn([("documents",), ("vector(768)",)])
        assert PGVectorStore.table_dimension(conn) == 768

    def test_returns_none_when_the_table_is_absent(self):
        from application.vectorstore.pgvector import PGVectorStore

        conn = self._conn([(None,)])
        assert PGVectorStore.table_dimension(conn) is None

    def test_returns_none_when_the_column_type_is_not_a_vector(self):
        from application.vectorstore.pgvector import PGVectorStore

        conn = self._conn([("documents",), ("text",)])
        assert PGVectorStore.table_dimension(conn) is None


@pytest.mark.unit
class TestReadPathsCloseTheirTransaction:
    """A read that never commits leaves the connection idle-in-transaction.

    On a persistent (now pooled) connection that holds a snapshot open for the
    life of the process and makes psycopg_pool roll back every returned
    connection.
    """

    def test_search_commits(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        mock_cursor.fetchall.return_value = [("hello", {}, 0.1), ("bye", {}, 0.2)]

        store.search_with_scores("q", k=2)

        mock_conn.commit.assert_called_once()

    def test_keyword_search_commits(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        mock_cursor.fetchall.return_value = []

        store.keyword_search("q")

        mock_conn.commit.assert_called_once()

    def test_get_chunks_commits(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        mock_cursor.fetchall.return_value = []

        store.get_chunks()

        mock_conn.commit.assert_called_once()


@pytest.mark.unit
class TestConnectionPooling:
    def _pooled_store(self, monkeypatch):
        store, _, _, _ = _make_store()
        store._connection = None
        store._pool_max_size = 4
        pooled_conn = MagicMock()
        pooled_conn.closed = False
        fake_pool = MagicMock()
        fake_pool.getconn.return_value = pooled_conn
        monkeypatch.setattr(
            pgvector_module, "_pool_for", lambda dsn, size: fake_pool
        )
        return store, fake_pool, pooled_conn

    def test_get_connection_checks_out_of_the_pool(self, monkeypatch):
        store, fake_pool, pooled_conn = self._pooled_store(monkeypatch)

        conn = store._get_connection()

        assert conn is pooled_conn
        assert store._pooled is True
        fake_pool.getconn.assert_called_once()
        store._psycopg.connect.assert_not_called()

    def test_probes_are_applied_once_per_physical_connection(self, monkeypatch):
        store, _, pooled_conn = self._pooled_store(monkeypatch)
        applied = Mock()
        monkeypatch.setattr(store, "_apply_ivfflat_probes", applied)

        store._get_connection()
        store._connection = None  # simulate a second checkout of the same conn
        store._get_connection()

        assert applied.call_count == 1

    def test_close_rolls_back_and_returns_the_connection(self, monkeypatch):
        store, fake_pool, pooled_conn = self._pooled_store(monkeypatch)
        store._get_connection()
        pooled_conn.info.transaction_status.name = "INTRANS"
        monkeypatch.setitem(
            pgvector_module._POOLS, store._connection_string, fake_pool
        )

        store.close()

        pooled_conn.rollback.assert_called_once()
        fake_pool.putconn.assert_called_once_with(pooled_conn)
        pooled_conn.close.assert_not_called()
        assert store._connection is None

    def test_close_does_not_roll_back_an_idle_connection(self, monkeypatch):
        store, fake_pool, pooled_conn = self._pooled_store(monkeypatch)
        store._get_connection()
        pooled_conn.info.transaction_status.name = "IDLE"
        monkeypatch.setitem(
            pgvector_module._POOLS, store._connection_string, fake_pool
        )

        store.close()

        pooled_conn.rollback.assert_not_called()
        fake_pool.putconn.assert_called_once_with(pooled_conn)

    def test_a_dead_pooled_connection_is_returned_before_being_replaced(
        self, monkeypatch
    ):
        # psycopg_pool never reclaims a checkout that is not handed back, so
        # replacing a connection that died in our hands would burn a pool slot
        # permanently: after PGVECTOR_POOL_MAX_SIZE such events every checkout
        # blocks for the pool timeout and then fails.
        store, fake_pool, pooled_conn = self._pooled_store(monkeypatch)
        monkeypatch.setitem(
            pgvector_module._POOLS, store._connection_string, fake_pool
        )
        store._get_connection()
        replacement = MagicMock()
        replacement.closed = False
        fake_pool.getconn.return_value = replacement

        pooled_conn.closed = True  # server terminated the backend mid-idle
        conn = store._get_connection()

        assert conn is replacement
        fake_pool.putconn.assert_called_once_with(pooled_conn)
        assert fake_pool.getconn.call_count == 2

    def test_legacy_path_connects_directly_and_closes(self):
        store, mock_conn, _, _ = _make_store()
        store._pool_max_size = 0
        mock_conn.closed = True
        new_conn = MagicMock()
        new_conn.closed = False
        store._psycopg.connect.return_value = new_conn

        conn = store._get_connection()
        assert conn is new_conn
        assert store._pooled is False

        store.close()
        new_conn.close.assert_called_once()

    def test_del_never_raises(self):
        store, mock_conn, _, _ = _make_store()
        mock_conn.close.side_effect = RuntimeError("already gone")

        store.__del__()  # must not propagate
