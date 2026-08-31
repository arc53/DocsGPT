"""Live pgvector run of the re-embed script.

Uses the ephemeral pytest-postgresql cluster with a stub embeddings model, so
a real ``UPDATE ... ::vector`` round trip is exercised without downloading a
model. Skips when the cluster has no pgvector build.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from application.scripts import reembed
from application.vectorstore import pgvector as pgvector_module
from application.vectorstore.pgvector import PGVectorStore

pytestmark = pytest.mark.integration

DIM = 8


class _Embeddings:
    """Returns a distinct constant per generation, so a rewrite is visible."""

    dimension = DIM

    def __init__(self, seed: float):
        self.seed = seed
        self.calls = 0

    def embed_documents(self, texts):
        self.calls += 1
        return [[self.seed] + [0.0] * (DIM - 1) for _ in texts]

    def embed_query(self, query):
        return [self.seed] + [0.0] * (DIM - 1)


def _dsn(info) -> str:
    password = f":{info.password}" if info.password else ""
    return f"postgresql://{info.user}{password}@{info.host}:{info.port}/{info.dbname}"


@pytest.fixture(autouse=True)
def _close_pools():
    """Never leak a pool into another test; the DSN dies with the test DB."""
    yield
    for dsn, pool in list(pgvector_module._POOLS.items()):
        try:
            pool.close()
        except Exception:
            # Teardown only: the ephemeral cluster may already be gone, and a
            # failure to close a pool for a dead DSN must not fail the test
            # that just passed. Dropping the entry below is what matters.
            pass
        pgvector_module._POOLS.pop(dsn, None)


@pytest.fixture
def live_dsn(postgresql, monkeypatch):
    try:
        with postgresql.cursor() as cursor:
            cursor.execute("CREATE EXTENSION vector;")
        postgresql.rollback()
    except Exception as exc:
        postgresql.rollback()
        pytest.skip(f"pgvector extension unavailable: {exc}")

    dsn = _dsn(postgresql.info)
    from application.core import settings as settings_module

    settings = settings_module.settings
    monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector", raising=False)
    monkeypatch.setattr(settings, "PGVECTOR_CONNECTION_STRING", dsn, raising=False)
    monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "PGVECTOR_IVFFLAT_PROBES", None, raising=False)
    monkeypatch.setattr(settings, "PGVECTOR_POOL_MAX_SIZE", 4, raising=False)
    monkeypatch.setattr(settings, "EMBEDDINGS_NAME", "granite-311m", raising=False)
    return dsn


def _seed(dsn, source_id, texts, embeddings):
    """Create the schema and insert ``texts`` embedded by ``embeddings``."""
    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings",
        return_value=embeddings,
    ):
        store = PGVectorStore(source_id=source_id, connection_string=dsn)
        conn = store._get_connection()
        PGVectorStore.create_schema(conn, dimension=DIM)
        conn.commit()
        store.add_texts(list(texts), metadatas=[{"i": i} for i in range(len(texts))])
        store.close()


def _as_list(vector):
    """Normalise a stored vector to a list of floats.

    Depending on whether pgvector's adapter is registered on the reading
    connection, the value comes back as a ``Vector`` or as its text form
    ``'[1,0,...]'``. Both are valid; the assertions should not care.
    """
    if vector is None:
        return []
    if hasattr(vector, "to_list"):
        return list(vector.to_list())
    if isinstance(vector, str):
        return [float(part) for part in vector.strip("[]").split(",") if part]
    return list(vector)


def _vectors(dsn, source_id):
    store = PGVectorStore(source_id=source_id, connection_string=dsn)
    conn = store._get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT text, embedding FROM documents WHERE source_id = %s ORDER BY id",
            (source_id,),
        )
        # pgvector hands back a ``Vector``; normalise to a plain list so the
        # assertions read the same whichever adapter is registered.
        return [(text, _as_list(vector)) for text, vector in cursor.fetchall()]
    finally:
        cursor.close()
        store.close()


TEXTS = ["alpha document", "beta document", "gamma document"]


class TestReembedPgvectorLive:
    def test_rewrites_vectors_and_preserves_text(self, live_dsn):
        _seed(live_dsn, "src-a", TEXTS, _Embeddings(1.0))
        before = _vectors(live_dsn, "src-a")
        assert [row[0] for row in before] == TEXTS
        assert all(row[1][0] == pytest.approx(1.0) for row in before)

        new_model = _Embeddings(9.0)
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings",
            return_value=new_model,
        ):
            seen, written = reembed.reembed_pgvector("src-a", batch_size=2, dry_run=False)

        assert (seen, written) == (3, 3)
        after = _vectors(live_dsn, "src-a")
        # Text is untouched; only the vectors moved.
        assert [row[0] for row in after] == TEXTS
        assert all(row[1][0] == pytest.approx(9.0) for row in after)

    def test_dry_run_counts_without_writing(self, live_dsn):
        _seed(live_dsn, "src-b", TEXTS, _Embeddings(1.0))
        new_model = _Embeddings(9.0)
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings",
            return_value=new_model,
        ):
            seen, written = reembed.reembed_pgvector("src-b", batch_size=2, dry_run=True)

        assert (seen, written) == (3, 0)
        assert new_model.calls == 0, "dry run must not embed"
        assert all(row[1][0] == pytest.approx(1.0) for row in _vectors(live_dsn, "src-b"))

    def test_batches_are_respected(self, live_dsn):
        _seed(live_dsn, "src-c", TEXTS, _Embeddings(1.0))
        new_model = _Embeddings(9.0)
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings",
            return_value=new_model,
        ):
            reembed.reembed_pgvector("src-c", batch_size=2, dry_run=False)
        assert new_model.calls == 2, "3 chunks at batch 2 is two embed calls"

    def test_only_the_named_source_is_touched(self, live_dsn):
        _seed(live_dsn, "src-d", TEXTS, _Embeddings(1.0))
        _seed(live_dsn, "src-e", TEXTS, _Embeddings(1.0))
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings",
            return_value=_Embeddings(9.0),
        ):
            reembed.reembed_pgvector("src-d", batch_size=64, dry_run=False)

        assert all(row[1][0] == pytest.approx(9.0) for row in _vectors(live_dsn, "src-d"))
        assert all(row[1][0] == pytest.approx(1.0) for row in _vectors(live_dsn, "src-e"))

    def test_source_discovery_lists_every_source(self, live_dsn):
        _seed(live_dsn, "src-f", TEXTS, _Embeddings(1.0))
        _seed(live_dsn, "src-g", TEXTS, _Embeddings(1.0))
        assert reembed.list_source_ids("pgvector") == ["src-f", "src-g"]


GRAPH_SOURCE = "11111111-2222-3333-4444-555555555555"


def _seed_graph_node(dsn, source_id, name, seed):
    """Insert one graph node carrying a name embedding at ``seed``."""
    from application.graphrag.store import GraphStore

    store = PGVectorStore(source_id=source_id, connection_string=dsn)
    conn = store._get_connection()
    GraphStore.create_schema(conn, dimension=DIM)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO graph_nodes (id, source_id, name, normalized_name, type, "
            "description, degree, doc_freq, name_embedding) "
            "VALUES (gen_random_uuid(), %s, %s, %s, 'ENTITY', '', 0, 0, %s::vector)",
            (source_id, name, name.lower(), str([seed] + [0.0] * (DIM - 1))),
        )
        conn.commit()
    finally:
        cursor.close()
        store.close()


def _node_vectors(dsn, source_id):
    store = PGVectorStore(source_id=source_id, connection_string=dsn)
    conn = store._get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT name, name_embedding FROM graph_nodes "
            "WHERE source_id = %s ORDER BY name",
            (source_id,),
        )
        return [(name, _as_list(vector)) for name, vector in cursor.fetchall()]
    finally:
        cursor.close()
        store.close()


class TestGraphNodeReembedLive:
    """``graph_nodes.name_embedding`` seeds every graph traversal.

    Rewriting only the chunk table leaves it in the previous model's space,
    and because mpnet and granite-311m share a width the column accepts the
    mismatch silently -- exactly the failure the script exists to prevent.
    """

    def test_node_names_are_re_embedded(self, live_dsn, monkeypatch):
        from application.core import settings as settings_module

        monkeypatch.setattr(
            settings_module.settings, "GRAPHRAG_ENABLED", True, raising=False
        )
        _seed(live_dsn, GRAPH_SOURCE, TEXTS, _Embeddings(1.0))
        _seed_graph_node(live_dsn, GRAPH_SOURCE, "Alpha", 1.0)

        assert all(v[0] == pytest.approx(1.0) for _, v in _node_vectors(live_dsn, GRAPH_SOURCE))

        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings",
            return_value=_Embeddings(9.0),
        ):
            reembed.reembed_pgvector(GRAPH_SOURCE, batch_size=64, dry_run=False)

        after = _node_vectors(live_dsn, GRAPH_SOURCE)
        assert [name for name, _ in after] == ["Alpha"]
        assert all(v[0] == pytest.approx(9.0) for _, v in after), (
            "graph node names must move with the chunk vectors"
        )

    def test_graph_is_left_alone_when_graphrag_is_off(self, live_dsn, monkeypatch):
        from application.core import settings as settings_module

        monkeypatch.setattr(
            settings_module.settings, "GRAPHRAG_ENABLED", False, raising=False
        )
        _seed(live_dsn, GRAPH_SOURCE, TEXTS, _Embeddings(1.0))
        _seed_graph_node(live_dsn, GRAPH_SOURCE, "Alpha", 1.0)

        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings",
            return_value=_Embeddings(9.0),
        ):
            reembed.reembed_pgvector(GRAPH_SOURCE, batch_size=64, dry_run=False)

        assert all(v[0] == pytest.approx(1.0) for _, v in _node_vectors(live_dsn, GRAPH_SOURCE))

    def test_dry_run_leaves_node_vectors_untouched(self, live_dsn, monkeypatch):
        from application.core import settings as settings_module

        monkeypatch.setattr(
            settings_module.settings, "GRAPHRAG_ENABLED", True, raising=False
        )
        _seed(live_dsn, GRAPH_SOURCE, TEXTS, _Embeddings(1.0))
        _seed_graph_node(live_dsn, GRAPH_SOURCE, "Alpha", 1.0)

        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings",
            return_value=_Embeddings(9.0),
        ):
            reembed.reembed_pgvector(GRAPH_SOURCE, batch_size=64, dry_run=True)

        assert all(v[0] == pytest.approx(1.0) for _, v in _node_vectors(live_dsn, GRAPH_SOURCE))
