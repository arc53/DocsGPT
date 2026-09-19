"""Per-source knowledge-graph store co-located with the pgvector ``documents`` table.

GraphRAG is pgvector-only: the graph tables live in the same DB as the pgvector
store and are created at boot by ``ensure_vector_schema`` (``CREATE TABLE IF NOT
EXISTS`` + ``CREATE EXTENSION IF NOT EXISTS vector``), mirroring
``PGVectorStore.create_schema`` rather than going through app-DB Alembic.
Constructing a store runs no DDL and opens no connection; the write methods
re-check the schema once per instance as a safety net for a process that never
ran the boot hook. That DB may be a separate cluster (e.g. Neon) from the app DB
where ``sources`` lives, so ``source_id`` is a plain indexed UUID column with no
cross-DB FK and all ids are generated in Python.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from docsgpt.core.settings import settings
from docsgpt.vectorstore import pgconn

DEFAULT_NAME_EMBEDDING_DIM = 768

# Bound here (same objects, not copies) from the shared pool module, which both
# stores already import. Reaching through ``pgvector`` instead would drag the
# embeddings stack in at import time; ``pgconn`` imports nothing heavier than
# ``logging`` and ``threading``. 0 disables pooling.
DEFAULT_POOL_MAX_SIZE = pgconn.DEFAULT_POOL_MAX_SIZE
_resolve_pool_max_size = pgconn.resolve_pool_max_size

MAX_SUBGRAPH_NODES = 500
MAX_SUBGRAPH_EDGES = 2000

GRAPH_OVERVIEW_DEFAULT_LIMIT = 100
GRAPH_OVERVIEW_MAX_LIMIT = 250

PGVECTOR_SOURCE_COLUMN = "source_id"


def _safe_identifier(name: str) -> str:
    """Return ``name`` if it is a bare SQL identifier, else raise.

    Guards the interpolated table/column names against injection; pgvector uses
    plain identifiers, so anything outside ``[A-Za-z_][A-Za-z0-9_]*`` is rejected.
    """
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


def _identifier(name: str) -> sql.Identifier:
    """``name`` as a quoted identifier, folded the way Postgres folds it unquoted.

    Composing identifiers through psycopg keeps every query a fixed statement
    with bound values: nothing is formatted into the SQL string. The fold
    matters because ``PGVectorStore`` writes these names unquoted, which
    Postgres lower-cases, while a quoted identifier keeps its case; folding
    first keeps both stores addressing the same table.
    """
    return sql.Identifier(_safe_identifier(name).lower())


def _pgvector_identifiers() -> tuple[str, str, str, str]:
    """Resolve ``(table, text_col, metadata_col, source_col)`` from ``PGVectorStore``.

    Reads the table and column defaults from ``PGVectorStore.__init__`` so the
    graph store queries the same names a customized deployment configured.
    """
    import inspect

    from docsgpt.vectorstore.pgvector import PGVectorStore

    params = inspect.signature(PGVectorStore.__init__).parameters
    table = params["table_name"].default
    text_col = params["text_column"].default
    metadata_col = params["metadata_column"].default
    return (
        _safe_identifier(table),
        _safe_identifier(text_col),
        _safe_identifier(metadata_col),
        _safe_identifier(PGVECTOR_SOURCE_COLUMN),
    )


def _pgvector_vector_column() -> str:
    """Resolve the embedding column name from the same ``PGVectorStore`` defaults."""
    import inspect

    from docsgpt.vectorstore.pgvector import PGVectorStore

    params = inspect.signature(PGVectorStore.__init__).parameters
    return _safe_identifier(params["vector_column"].default)


def _is_connection_lost(exc: BaseException) -> bool:
    """True when ``exc`` says the server connection went away, not that the SQL was bad.

    psycopg raises ``OperationalError`` ("the connection is lost") when the
    socket dies under a statement and ``InterfaceError`` when the connection
    object is already closed. Everything else — a bad statement, a constraint
    violation — is a real failure that a retry would only repeat.
    """
    return isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))


def _safe_rollback(conn) -> None:
    """Roll back, tolerating a connection too broken to roll back."""
    try:
        conn.rollback()
    except Exception as exc:
        logging.debug("Rollback on a broken connection failed: %s", exc)


class GraphStore:
    """Stores and queries a per-source knowledge graph in the pgvector DB."""

    def __init__(self, connection_string: Optional[str] = None):
        self._connection_string = connection_string or settings.PGVECTOR_CONNECTION_STRING

        if not self._connection_string and settings.POSTGRES_URI:
            from docsgpt.core.db_uri import normalize_pgvector_connection_string

            self._connection_string = normalize_pgvector_connection_string(
                settings.POSTGRES_URI
            )

        if not self._connection_string:
            raise ValueError(
                "PostgreSQL connection string is required. "
                "Set PGVECTOR_CONNECTION_STRING or POSTGRES_URI in settings, "
                "or pass connection_string parameter."
            )

        try:
            import psycopg
            from pgvector.psycopg import register_vector
        except ImportError:
            raise ImportError(
                "Could not import required packages. "
                "Please install with `pip install 'psycopg[binary,pool]' pgvector`."
            )

        self._psycopg = psycopg
        self._register_vector = register_vector
        self._connection = None
        self._pooled = False
        self._pool_max_size = _resolve_pool_max_size()
        # No DDL here: the graph tables are created at boot alongside the
        # pgvector table, and every write re-checks once (see _ensure_tables_once).
        self._tables_ensured = False

    def _get_connection(self):
        """Get or create this store's connection, pooled unless pooling is off.

        Shares :mod:`docsgpt.vectorstore.pgconn`'s per-DSN pool with
        ``PGVectorStore``, so a retrieval that touches both pays one checkout
        each instead of two fresh connect handshakes.
        """
        if self._connection is not None and self._connection.closed:
            # Hand the dead connection back before replacing it; an unreturned
            # checkout is a pool slot lost for the life of the process.
            self.close()
        if self._connection is None:
            if self._pool_max_size > 0:
                self._connection = pgconn.pool_for(
                    self._connection_string, self._pool_max_size
                ).getconn()
                self._pooled = True
                # No _register_pgvector_types here: the pool's ``configure``
                # hook already ran it on this physical connection, and repeating
                # it would cost a catalog lookup on every checkout. The DDL path
                # (_ensure_tables) still re-registers after CREATE EXTENSION.
            else:
                self._connection = self._psycopg.connect(self._connection_string)
                self._register_pgvector_types(self._connection)
                self._pooled = False
        return self._connection

    def _write_with_reconnect(self, operation):
        """Run ``operation(conn)``, once more on a fresh connection if it was dead.

        A graph build holds one checked-out connection for the length of the
        whole extraction and spends minutes per chunk waiting on the model, so
        the connection idles long enough for the server (or a pooler) to drop
        it. The pool only validates a connection when it is handed out, and
        this one was handed out at the start of the build, so the next write
        raises and its chunk is lost from the graph. Every statement here is an
        idempotent upsert, so replaying one on a new connection cannot
        double-write.

        Args:
            operation: Callable taking the connection and doing one write.

        Returns:
            Whatever ``operation`` returns.

        Raises:
            Exception: Anything ``operation`` raises that is not connection
                loss, and anything the single retry raises.
        """
        try:
            return operation(self._get_connection())
        except Exception as exc:
            if not _is_connection_lost(exc):
                raise
            logging.warning(
                "Graph write lost its connection (%s); reconnecting and retrying once.",
                exc,
            )
            self.close()
        # Second and final attempt, on a connection freshly checked out by
        # ``_get_connection``. A failure here belongs to the caller.
        return operation(self._get_connection())

    def _register_pgvector_types(self, conn) -> None:
        """Register pgvector's adapters, tolerating a not-yet-created extension.

        ``register_vector`` looks the ``vector`` type up in the catalog and
        raises when it is absent — which is exactly the state of a brand-new
        database, before ``CREATE EXTENSION`` has run. Swallow that so the
        schema bootstrap can proceed; it re-registers once the type exists.
        """
        try:
            self._register_vector(conn)
        except Exception as e:
            logging.debug("pgvector types not registered yet: %s", e)

    def _embedding_dim(self) -> int:
        """Dimension of the configured embeddings model, matching ``PGVectorStore``.

        Falls back to ``DEFAULT_NAME_EMBEDDING_DIM`` so the graph table and the
        pgvector ``documents`` table always agree on the configured model. A
        model outside the registry reports ``None`` rather than no attribute,
        so the fallback cannot be left to ``getattr``.
        """
        from docsgpt.vectorstore.base import get_embeddings

        embedding = get_embeddings()
        return getattr(embedding, "dimension", None) or DEFAULT_NAME_EMBEDDING_DIM

    @staticmethod
    def create_schema(conn, *, dimension: int = DEFAULT_NAME_EMBEDDING_DIM) -> None:
        """Create the graph tables and indexes on ``conn`` without committing.

        Shared by the boot hook (``ensure_vector_schema``) and the store's own
        write-path safety net; the caller owns the transaction.

        Args:
            conn: Open psycopg connection to the pgvector database.
            dimension: Width of the node name-embedding vectors.
        """
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    id UUID PRIMARY KEY,
                    source_id UUID NOT NULL,
                    name TEXT,
                    normalized_name TEXT,
                    type TEXT,
                    description TEXT,
                    degree INT DEFAULT 0,
                    doc_freq INT DEFAULT 0,
                    name_embedding vector({dimension}),
                    UNIQUE (source_id, normalized_name)
                );
                """
            )

            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS graph_edges (
                    id UUID PRIMARY KEY,
                    source_id UUID NOT NULL,
                    src_node_id UUID,
                    dst_node_id UUID,
                    type TEXT,
                    description TEXT,
                    weight REAL DEFAULT 1.0,
                    source_chunk_ids JSONB,
                    fact_embedding vector({dimension})
                );
                """
            )
            # ``CREATE TABLE IF NOT EXISTS`` is a no-op on a database that
            # already has the table, so a column added after the fact needs its
            # own statement or every existing deployment silently lacks it.
            cursor.execute(
                f"ALTER TABLE graph_edges "
                f"ADD COLUMN IF NOT EXISTS fact_embedding vector({dimension});"
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_node_chunks (
                    source_id UUID NOT NULL,
                    node_id UUID NOT NULL,
                    chunk_id TEXT NOT NULL,
                    PRIMARY KEY (source_id, node_id, chunk_id)
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_ingest_progress (
                    source_id UUID NOT NULL,
                    chunk_id TEXT NOT NULL,
                    status TEXT,
                    PRIMARY KEY (source_id, chunk_id)
                );
                """
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS graph_nodes_source_id_idx "
                "ON graph_nodes (source_id);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS graph_edges_source_id_idx "
                "ON graph_edges (source_id);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS graph_edges_src_node_id_idx "
                "ON graph_edges (src_node_id);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS graph_edges_dst_node_id_idx "
                "ON graph_edges (dst_node_id);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS graph_node_chunks_node_id_idx "
                "ON graph_node_chunks (node_id);"
            )
            # No vector index here, deliberately: this runs at table-creation
            # time, so an IVFFlat index would be built on an EMPTY table and get
            # random centroids. Combined with the ``WHERE source_id = ...``
            # post-filter in search_nodes_by_embedding that silently returns
            # zero nodes, and graph_rag does not fall back when the source has
            # nodes. Add an index deliberately once a graph is large enough.
        finally:
            cursor.close()

    def _ensure_tables(self):
        """Create the graph schema under an advisory lock, then commit."""
        # Same key as the pgvector store and the boot hook: one lock guards all
        # DDL in this database, so concurrent workers never race each other.
        from docsgpt.vectorstore.pgvector import SCHEMA_LOCK_KEY

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s));", (SCHEMA_LOCK_KEY,)
                )
            finally:
                cursor.close()
            self.create_schema(conn, dimension=self._embedding_dim())
            conn.commit()
            # The extension may have just been created; pick up its adapters.
            self._register_pgvector_types(conn)
        except Exception as e:
            conn.rollback()
            logging.error(f"Error creating graph tables: {e}")
            raise

    def _ensure_tables_once(self) -> None:
        """Create the graph schema on this instance's first write, at most once.

        Readers never create tables — boot owns the schema. This is the safety
        net for a process that never ran the boot hook (scripts, tests, the
        first extraction on a brand-new deployment).
        """
        if getattr(self, "_tables_ensured", False):
            return
        self._ensure_tables()
        self._tables_ensured = True

    def _upsert_node(
        self,
        cursor,
        source_id: str,
        name: str,
        normalized_name: str,
        type: Optional[str] = None,
        description: Optional[str] = None,
        name_embedding: Optional[List[float]] = None,
    ) -> str:
        """Upsert a node on an open cursor (no commit). Returns the node id.

        On conflict the description is concatenated (de-duped), ``doc_freq`` is
        incremented, the type is refreshed if previously empty, and the
        embedding is refreshed when provided.
        """
        node_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO graph_nodes
                (id, source_id, name, normalized_name, type, description,
                 doc_freq, name_embedding)
            VALUES (%s, %s, %s, %s, %s, %s, 1, %s)
            ON CONFLICT (source_id, normalized_name) DO UPDATE SET
                description = CASE
                    WHEN EXCLUDED.description IS NULL
                         OR EXCLUDED.description = '' THEN graph_nodes.description
                    WHEN graph_nodes.description IS NULL
                         OR graph_nodes.description = '' THEN EXCLUDED.description
                    WHEN position(EXCLUDED.description IN graph_nodes.description) > 0
                        THEN graph_nodes.description
                    ELSE graph_nodes.description || ' ' || EXCLUDED.description
                END,
                type = CASE
                    WHEN graph_nodes.type IS NULL
                         OR graph_nodes.type = '' THEN EXCLUDED.type
                    ELSE graph_nodes.type
                END,
                name = COALESCE(graph_nodes.name, EXCLUDED.name),
                doc_freq = graph_nodes.doc_freq + 1,
                name_embedding = COALESCE(
                    EXCLUDED.name_embedding, graph_nodes.name_embedding
                )
            RETURNING id;
            """,
            (
                node_id,
                source_id,
                name,
                normalized_name,
                type,
                description,
                name_embedding,
            ),
        )
        return str(cursor.fetchone()[0])

    def upsert_node(
        self,
        source_id: str,
        name: str,
        normalized_name: str,
        type: Optional[str] = None,
        description: Optional[str] = None,
        name_embedding: Optional[List[float]] = None,
    ) -> str:
        """Insert a node or merge into the existing one for ``(source_id, normalized_name)``.

        On conflict the description is concatenated (de-duped), ``doc_freq`` is
        incremented, the type is refreshed if previously empty, and the
        embedding is refreshed when provided. Returns the node id either way.
        """
        self._ensure_tables_once()
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            returned_id = self._upsert_node(
                cursor, source_id, name, normalized_name, type, description,
                name_embedding,
            )
            conn.commit()
            return returned_id
        except Exception as e:
            conn.rollback()
            logging.error(f"Error upserting node: {e}")
            raise
        finally:
            cursor.close()

    def _add_edge(
        self,
        cursor,
        source_id: str,
        src_node_id: str,
        dst_node_id: str,
        type: Optional[str] = None,
        description: Optional[str] = None,
        weight: float = 1.0,
        source_chunk_ids: Optional[List[str]] = None,
        fact_embedding: Optional[List[float]] = None,
    ) -> tuple[Optional[str], bool]:
        """Write an edge on an open cursor (no commit, no degree bump).

        Returns ``(edge_id, created)``. Two shapes of noise are rejected here
        rather than at read time, because once written neither is visible:

        * A self-loop feeds a node's PageRank mass straight back to itself. It
          is dropped, reported as ``(None, False)``.
        * A pair already related by the same type is *merged* rather than
          inserted again. ``graph_edges`` carries no uniqueness constraint, so
          re-extracting one relationship across many chunks otherwise writes a
          row per chunk — a fifth of a real corpus's edges — inflating that
          pair's traversal weight and spending the bounded subgraph fetch on
          duplicates. The surviving row keeps the strongest weight seen and
          every contributing chunk id.

        Callers that batch many edges run ``set_node_degrees`` once afterwards
        instead of bumping degree per edge.
        """
        if str(src_node_id) == str(dst_node_id):
            return None, False

        cursor.execute(
            """
            SELECT id
            FROM graph_edges
            WHERE source_id = %s AND src_node_id = %s AND dst_node_id = %s
              AND type IS NOT DISTINCT FROM %s
            LIMIT 1;
            """,
            (source_id, src_node_id, dst_node_id, type),
        )
        existing = cursor.fetchone()
        if existing:
            edge_id = existing[0]
            # The chunk ids are merged in SQL, against the row's own current
            # value, rather than read here and written back: a read-modify-write
            # would drop whatever a concurrent writer appended in between.
            cursor.execute(
                """
                UPDATE graph_edges
                SET weight = GREATEST(COALESCE(weight, 0), %s),
                    description = COALESCE(description, %s),
                    -- Backfills the fact embedding for an edge first written
                    -- before fact embeddings were switched on.
                    fact_embedding = COALESCE(fact_embedding, %s::vector),
                    source_chunk_ids = COALESCE(source_chunk_ids, '[]'::jsonb) || (
                        SELECT COALESCE(jsonb_agg(candidate), '[]'::jsonb)
                        FROM jsonb_array_elements(%s::jsonb) AS candidate
                        WHERE NOT COALESCE(source_chunk_ids, '[]'::jsonb)
                              @> jsonb_build_array(candidate)
                    )
                WHERE id = %s;
                """,
                (
                    weight,
                    description,
                    fact_embedding,
                    Jsonb(list(source_chunk_ids or [])),
                    edge_id,
                ),
            )
            return str(edge_id), False

        edge_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO graph_edges
                (id, source_id, src_node_id, dst_node_id, type, description,
                 weight, source_chunk_ids, fact_embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (
                edge_id,
                source_id,
                src_node_id,
                dst_node_id,
                type,
                description,
                weight,
                Jsonb(source_chunk_ids or []),
                fact_embedding,
            ),
        )
        return edge_id, True

    def add_edge(
        self,
        source_id: str,
        src_node_id: str,
        dst_node_id: str,
        type: Optional[str] = None,
        description: Optional[str] = None,
        weight: float = 1.0,
        source_chunk_ids: Optional[List[str]] = None,
        fact_embedding: Optional[List[float]] = None,
    ) -> Optional[str]:
        """Write an edge and bump the degree of both endpoints. Returns its id.

        Returns ``None`` for a self-loop, which is not written. A repeat of an
        existing pair merges into that row and returns its id, leaving degree
        alone — the endpoints gained no new neighbour.
        """
        self._ensure_tables_once()
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            edge_id, created = self._add_edge(
                cursor, source_id, src_node_id, dst_node_id, type, description,
                weight, source_chunk_ids, fact_embedding,
            )
            if created:
                cursor.execute(
                    "UPDATE graph_nodes SET degree = degree + 1 "
                    "WHERE source_id = %s AND id IN (%s, %s);",
                    (source_id, src_node_id, dst_node_id),
                )
            conn.commit()
            return edge_id
        except Exception as e:
            conn.rollback()
            logging.error(f"Error adding edge: {e}")
            raise
        finally:
            cursor.close()

    def _link_node_chunk(self, cursor, source_id: str, node_id: str, chunk_id: str):
        """Link a node to a chunk on an open cursor (no commit)."""
        cursor.execute(
            """
            INSERT INTO graph_node_chunks (source_id, node_id, chunk_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (source_id, node_id, chunk_id) DO NOTHING;
            """,
            (source_id, node_id, str(chunk_id)),
        )

    def link_node_chunk(self, source_id: str, node_id: str, chunk_id: str):
        self._ensure_tables_once()
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            self._link_node_chunk(cursor, source_id, node_id, chunk_id)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(f"Error linking node chunk: {e}")
            raise
        finally:
            cursor.close()

    def apply_chunk(
        self,
        source_id: str,
        chunk_id: str,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        name_embeddings: Dict[str, List[float]],
    ) -> tuple[int, int]:
        """Write one chunk's extracted entities and relationships in one transaction.

        ``entities`` are ``{name, normalized_name, type, description}`` dicts;
        each is upserted and linked to ``chunk_id``. ``relationships`` are
        ``{source, target, type, description, weight}`` dicts keyed by entity
        name; an endpoint not among the chunk's entities is upserted edge-only
        (not linked to the chunk), mirroring the per-call path.
        ``name_embeddings`` maps ``normalized_name`` to its embedding. Degrees
        are not bumped here — the caller runs ``set_node_degrees`` once at the
        end. Reconnects and retries once if the connection died while the
        extraction was waiting on the model.

        The chunk's ``graph_ingest_progress`` row is written in this same
        transaction, so the checkpoint and the rows it describes commit
        together and a replay of an already-applied chunk returns ``(0, 0)``
        without touching the graph. Returns ``(nodes_upserted, edges_added)``.
        """
        self._ensure_tables_once()

        def _write(conn):
            cursor = conn.cursor()
            node_ids: Dict[str, str] = {}
            edges_added = 0
            try:
                # ``commit()`` can report connection loss *after* the server
                # committed, and the retry then replays this write: doc_freq
                # would be bumped twice and a second logical edge inserted
                # (graph_edges has no uniqueness constraint). The progress row
                # below is written in this transaction, so a replay sees it.
                cursor.execute(
                    "SELECT status FROM graph_ingest_progress "
                    "WHERE source_id = %s AND chunk_id = %s;",
                    (source_id, str(chunk_id)),
                )
                applied = cursor.fetchone()
                if applied is not None and applied[0] == "done":
                    conn.rollback()
                    return 0, 0

                for entity in entities:
                    normalized_name = entity["normalized_name"]
                    node_id = self._upsert_node(
                        cursor,
                        source_id,
                        entity["name"],
                        normalized_name,
                        entity.get("type"),
                        entity.get("description"),
                        name_embeddings.get(normalized_name),
                    )
                    node_ids[normalized_name] = node_id
                    self._link_node_chunk(cursor, source_id, node_id, chunk_id)

                for rel in relationships:
                    src_id = self._resolve_endpoint(
                        cursor, source_id, rel.get("source"), node_ids, name_embeddings
                    )
                    dst_id = self._resolve_endpoint(
                        cursor, source_id, rel.get("target"), node_ids, name_embeddings
                    )
                    if src_id is None or dst_id is None:
                        continue
                    _, created = self._add_edge(
                        cursor,
                        source_id,
                        src_id,
                        dst_id,
                        type=rel.get("type"),
                        description=rel.get("description"),
                        weight=float(rel.get("weight") or 1.0),
                        source_chunk_ids=[chunk_id],
                        fact_embedding=rel.get("fact_embedding"),
                    )
                    if created:
                        edges_added += 1

                cursor.execute(
                    """
                    INSERT INTO graph_ingest_progress (source_id, chunk_id, status)
                    VALUES (%s, %s, 'done')
                    ON CONFLICT (source_id, chunk_id)
                    DO UPDATE SET status = EXCLUDED.status;
                    """,
                    (source_id, str(chunk_id)),
                )
                conn.commit()
                return len(entities), edges_added
            except Exception:
                _safe_rollback(conn)
                raise
            finally:
                cursor.close()

        return self._write_with_reconnect(_write)

    def _resolve_endpoint(
        self,
        cursor,
        source_id: str,
        name: Any,
        node_ids: Dict[str, str],
        name_embeddings: Dict[str, List[float]],
    ) -> Optional[str]:
        """Resolve a relationship endpoint to a node id, upserting if unseen this chunk."""
        if name is None:
            return None
        clean = str(name).strip()
        if not clean:
            return None
        from docsgpt.graphrag.naming import normalize_entity_name

        normalized_name = normalize_entity_name(clean)
        if not normalized_name:
            return None
        if normalized_name in node_ids:
            return node_ids[normalized_name]
        node_id = self._upsert_node(
            cursor,
            source_id,
            clean,
            normalized_name,
            name_embedding=name_embeddings.get(normalized_name),
        )
        node_ids[normalized_name] = node_id
        return node_id

    def get_node_by_normalized(
        self, source_id: str, normalized_name: str
    ) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, name, normalized_name, type, description, degree, doc_freq
                FROM graph_nodes
                WHERE source_id = %s AND normalized_name = %s;
                """,
                (source_id, normalized_name),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": str(row[0]),
                "name": row[1],
                "normalized_name": row[2],
                "type": row[3],
                "description": row[4],
                "degree": row[5],
                "doc_freq": row[6],
            }
        except Exception as e:
            logging.error(f"Error getting node by normalized name: {e}")
            return None
        finally:
            cursor.close()
            conn.rollback()

    def count_nodes(self, source_id: str, strict: bool = False) -> int:
        """Number of nodes for a source. Zero drives the ClassicRAG fallback.

        Args:
            source_id: Source whose nodes to count.
            strict: Re-raise a query failure instead of reporting ``0``.
                Retrieval wants the swallow — a broken count there just routes
                the source to ClassicRAG — but a caller reporting how big a
                graph is must not read a failed query as "the graph is empty".

        Returns:
            int: The node count, or ``0`` when a query failure is swallowed.

        Raises:
            Exception: The underlying query failure, when ``strict`` is set.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT count(*) FROM graph_nodes WHERE source_id = %s;",
                (source_id,),
            )
            return int(cursor.fetchone()[0])
        except Exception as e:
            logging.error(f"Error counting nodes: {e}")
            if strict:
                raise
            return 0
        finally:
            cursor.close()
            conn.rollback()

    def count_nodes_many(self, source_ids: List[str]) -> Dict[str, int]:
        """Node counts for several sources in one round trip.

        Replaces the retriever's per-source ``count_nodes`` fan-out: N sources
        used to cost N queries (each on its own fresh connection). Ids with no
        rows are filled in with 0 in Python, so the caller always gets an entry
        for every id it asked about.

        Args:
            source_ids: Source ids to count; empty/falsy entries are ignored.

        Returns:
            dict: ``{source_id: node_count}``, zero-filled. All zeros when the
            query fails, which drives the ClassicRAG fallback exactly as a
            failing ``count_nodes`` does.
        """
        ids = [str(s) for s in source_ids if s]
        if not ids:
            return {}
        counts: Dict[str, int] = {source_id: 0 for source_id in ids}
        # ``source_id`` is a UUID column, so Postgres hands back the canonical
        # lowercase text. Map it to the exact string the caller passed, or a
        # differently-cased id would land under a second key and read as 0.
        by_canonical = {source_id.lower(): source_id for source_id in ids}
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT source_id, count(*)
                FROM graph_nodes
                WHERE source_id = ANY(%s)
                GROUP BY source_id;
                """,
                (ids,),
            )
            for row in cursor.fetchall():
                returned = str(row[0])
                counts[by_canonical.get(returned.lower(), returned)] = int(row[1])
            return counts
        except Exception as e:
            logging.error(f"Error counting nodes: {e}")
            return counts
        finally:
            cursor.close()
            conn.rollback()

    def search_nodes_by_embedding(
        self, source_id: str, query_embedding: List[float], k: int = 10
    ) -> List[Dict[str, Any]]:
        """Cosine NN over ``graph_nodes.name_embedding`` scoped to a source."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, name, description,
                       (name_embedding <=> %s::vector) AS distance
                FROM graph_nodes
                WHERE source_id = %s AND name_embedding IS NOT NULL
                ORDER BY name_embedding <=> %s::vector
                LIMIT %s;
                """,
                (query_embedding, source_id, query_embedding, k),
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": str(row[0]),
                    "name": row[1],
                    "description": row[2],
                    "distance": row[3],
                }
                for row in rows
            ]
        except Exception as e:
            logging.error(f"Error searching nodes by embedding: {e}")
            return []
        finally:
            cursor.close()
            conn.rollback()

    def get_subgraph(
        self, source_id: str, node_ids: List[str], hops: int = 1
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Bounded 1-2-hop neighborhood of ``node_ids`` via indexed joins.

        Expands the seed set one hop at a time over edges (no recursive PageRank
        in SQL), capping node and edge counts so a hub never explodes the fetch.
        """
        if not node_ids:
            return {"nodes": [], "edges": []}

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            frontier = set(str(n) for n in node_ids)
            visited = set(frontier)
            for _ in range(max(1, hops)):
                if not frontier or len(visited) >= MAX_SUBGRAPH_NODES:
                    break
                cursor.execute(
                    """
                    SELECT src_node_id, dst_node_id
                    FROM graph_edges
                    WHERE source_id = %s
                      AND (src_node_id = ANY(%s) OR dst_node_id = ANY(%s))
                    ORDER BY weight DESC NULLS LAST
                    LIMIT %s;
                    """,
                    (
                        source_id,
                        list(frontier),
                        list(frontier),
                        MAX_SUBGRAPH_EDGES,
                    ),
                )
                next_frontier = set()
                for src, dst in cursor.fetchall():
                    for neighbor in (str(src), str(dst)):
                        if neighbor not in visited:
                            next_frontier.add(neighbor)
                if len(visited) + len(next_frontier) > MAX_SUBGRAPH_NODES:
                    allowed = MAX_SUBGRAPH_NODES - len(visited)
                    next_frontier = set(sorted(next_frontier)[:allowed])
                visited |= next_frontier
                frontier = next_frontier

            node_id_list = list(visited)
            cursor.execute(
                """
                SELECT id, name, type, description, degree, doc_freq
                FROM graph_nodes
                WHERE source_id = %s AND id = ANY(%s);
                """,
                (source_id, node_id_list),
            )
            nodes = [
                {
                    "id": str(row[0]),
                    "name": row[1],
                    "type": row[2],
                    "description": row[3],
                    "degree": row[4],
                    "doc_freq": row[5],
                }
                for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                SELECT id, src_node_id, dst_node_id, type, weight
                FROM graph_edges
                WHERE source_id = %s
                  AND src_node_id = ANY(%s) AND dst_node_id = ANY(%s)
                ORDER BY weight DESC NULLS LAST
                LIMIT %s;
                """,
                (source_id, node_id_list, node_id_list, MAX_SUBGRAPH_EDGES),
            )
            edges = [
                {
                    "id": str(row[0]),
                    "src_node_id": str(row[1]),
                    "dst_node_id": str(row[2]),
                    "type": row[3],
                    "weight": row[4],
                }
                for row in cursor.fetchall()
            ]
            return {"nodes": nodes, "edges": edges}
        except Exception as e:
            logging.error(f"Error getting subgraph: {e}")
            return {"nodes": [], "edges": []}
        finally:
            cursor.close()
            conn.rollback()

    def get_graph_overview(
        self, source_id: str, limit: int = GRAPH_OVERVIEW_DEFAULT_LIMIT
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Top-``limit`` nodes by degree and the edges among them.

        Bounds the visualization: the top nodes by degree are selected, then only
        edges whose endpoints are both in that set are returned (edge ids
        reference node ids). ``limit`` is clamped to ``GRAPH_OVERVIEW_MAX_LIMIT``.
        """
        limit = max(1, min(int(limit), GRAPH_OVERVIEW_MAX_LIMIT))
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, name, type, description, degree
                FROM graph_nodes
                WHERE source_id = %s
                ORDER BY degree DESC, id
                LIMIT %s;
                """,
                (source_id, limit),
            )
            nodes = [
                {
                    "id": str(row[0]),
                    "name": row[1],
                    "type": row[2],
                    "description": row[3],
                    "degree": row[4],
                }
                for row in cursor.fetchall()
            ]
            if not nodes:
                return {"nodes": [], "edges": []}

            node_ids = [n["id"] for n in nodes]
            cursor.execute(
                """
                SELECT src_node_id, dst_node_id, type, weight
                FROM graph_edges
                WHERE source_id = %s
                  AND src_node_id = ANY(%s) AND dst_node_id = ANY(%s)
                LIMIT %s;
                """,
                (source_id, node_ids, node_ids, MAX_SUBGRAPH_EDGES),
            )
            edges = [
                {
                    "source": str(row[0]),
                    "target": str(row[1]),
                    "type": row[2],
                    "weight": row[3],
                }
                for row in cursor.fetchall()
            ]
            return {"nodes": nodes, "edges": edges}
        except Exception as e:
            logging.error(f"Error getting graph overview: {e}")
            return {"nodes": [], "edges": []}
        finally:
            cursor.close()
            conn.rollback()

    def get_chunk_ids_for_nodes(
        self, source_id: str, node_ids: List[str]
    ) -> Dict[str, List[str]]:
        if not node_ids:
            return {}
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT node_id, chunk_id
                FROM graph_node_chunks
                WHERE source_id = %s AND node_id = ANY(%s);
                """,
                (source_id, [str(n) for n in node_ids]),
            )
            result: Dict[str, List[str]] = {}
            for node_id, chunk_id in cursor.fetchall():
                result.setdefault(str(node_id), []).append(chunk_id)
            return result
        except Exception as e:
            logging.error(f"Error getting chunk ids for nodes: {e}")
            return {}
        finally:
            cursor.close()
            conn.rollback()

    def seed_nodes_from_facts(
        self,
        source_id: str,
        query_embedding: List[float],
        fact_limit: int = 5,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Seed nodes drawn from the *relationships* nearest the question.

        Name matching asks "which entity is this question about", which a
        multi-document question cannot answer: the entity holding the answer is
        named in another document, not in the question. A fact string carries
        the relation — "Alder streams_to Quill: ..." — so a question about what
        a service writes to can match the edge itself and seed the walk on both
        of its endpoints, including the one nothing in the question names.

        Endpoints are weighted by fact score divided by the entity's
        ``doc_freq``: an entity appearing in every chunk is a poor seed even
        when it sits on a well-matched fact, and dividing by how widely it
        occurs prefers the specific endpoint over the hub.

        Rows match :meth:`search_nodes_by_embedding`'s shape, so the caller's
        seed weighting is unchanged. Returns nothing when the source has no
        fact embeddings, which is the signal to fall back to name matching.
        """
        if not query_embedding:
            return []
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                WITH top_facts AS (
                    SELECT src_node_id, dst_node_id,
                           1 - (fact_embedding <=> %s::vector) AS score
                    FROM graph_edges
                    WHERE source_id = %s AND fact_embedding IS NOT NULL
                    ORDER BY fact_embedding <=> %s::vector
                    LIMIT %s
                )
                SELECT n.id::text, n.name, n.description,
                       MAX(f.score / GREATEST(COALESCE(n.doc_freq, 1), 1)) AS weight
                FROM top_facts f
                JOIN graph_nodes n
                  ON n.id = f.src_node_id OR n.id = f.dst_node_id
                WHERE n.source_id = %s
                GROUP BY n.id, n.name, n.description
                ORDER BY weight DESC
                LIMIT %s;
                """,
                (
                    query_embedding,
                    source_id,
                    query_embedding,
                    max(1, int(fact_limit)),
                    source_id,
                    max(1, int(limit)),
                ),
            )
            return [
                {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    # The caller reads weight back as ``1 - distance``.
                    "distance": 1.0 - float(row[3] or 0.0),
                }
                for row in cursor.fetchall()
            ]
        except Exception as e:
            logging.error(f"Error seeding nodes from facts: {e}")
            return []
        finally:
            cursor.close()
            conn.rollback()

    def entity_relationships(
        self, source_id: str, name: str, limit: int = 25
    ) -> List[Dict[str, Any]]:
        """The relationships an entity takes part in, strongest first.

        This is the one thing a caller cannot get from vector search: which
        *named* thing an entity is connected to. Matching is on the name rather
        than a node id because the caller is an LLM holding a name it read in
        the text, not an id.
        """
        clean = (name or "").strip()
        if not clean:
            return []
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT s.name, e.type, d.name, e.description
                FROM graph_edges e
                JOIN graph_nodes s ON s.id = e.src_node_id
                JOIN graph_nodes d ON d.id = e.dst_node_id
                WHERE e.source_id = %s AND (s.name ILIKE %s OR d.name ILIKE %s)
                ORDER BY e.weight DESC NULLS LAST
                LIMIT %s;
                """,
                (source_id, f"%{clean}%", f"%{clean}%", max(1, int(limit))),
            )
            return [
                {"source": row[0], "type": row[1], "target": row[2], "description": row[3]}
                for row in cursor.fetchall()
            ]
        except Exception as e:
            logging.error(f"Error reading relationships for {name!r}: {e}")
            return []
        finally:
            cursor.close()
            conn.rollback()

    def entity_pages(
        self, source_id: str, name: str, limit: int = 4
    ) -> List[Dict[str, Any]]:
        """Chunks an entity appears in, with the chunk it is *about* first.

        A plain substring match answers "Halvard" with pages that merely mention
        Halvard, and an unordered ``LIMIT`` then decides which of those the
        caller sees. Nodes whose name is the entity (or the entity plus a
        qualifier the extractor appended, "Quill" -> "Quill Store") are
        preferred, and among those the chunk whose text opens with the name
        comes first; a substring match is the fallback so an unusual name still
        resolves.
        """
        clean = (name or "").strip()
        if not clean:
            return []
        table, text_col, metadata_col, source_col = _pgvector_identifiers()
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                sql.SQL(
                    """
                    SELECT d.{metadata}, d.{text},
                           (lower(n.name) = %s OR lower(n.name) LIKE %s) AS is_subject
                    FROM graph_node_chunks gc
                    JOIN graph_nodes n ON n.id = gc.node_id
                    JOIN {table} d ON d.id::text = gc.chunk_id
                    WHERE gc.source_id = %s AND d.{source} = %s
                      AND (lower(n.name) = %s OR lower(n.name) LIKE %s OR n.name ILIKE %s)
                    GROUP BY d.{metadata}, d.{text}, is_subject
                    ORDER BY is_subject DESC, (d.{text} ILIKE %s) DESC
                    LIMIT %s;
                    """
                ).format(
                    metadata=_identifier(metadata_col),
                    text=_identifier(text_col),
                    table=_identifier(table),
                    source=_identifier(source_col),
                ),
                (
                    clean.lower(), f"{clean.lower()} %",
                    source_id, source_id,
                    clean.lower(), f"{clean.lower()} %", f"%{clean}%",
                    f"{clean}%",
                    max(1, int(limit)),
                ),
            )
            return [
                {"metadata": row[0] or {}, "text": row[1] or ""}
                for row in cursor.fetchall()
            ]
        except Exception as e:
            logging.error(f"Error reading pages for {name!r}: {e}")
            return []
        finally:
            cursor.close()
            conn.rollback()

    def chunk_similarities(
        self, source_id: str, chunk_ids: List[str], query_embedding: List[float]
    ) -> Dict[str, float]:
        """Cosine similarity between the query and specific chunks of a source.

        Passage nodes need their own relevance to claim a share of the walk's
        restart mass, and that number lives in the co-located pgvector table —
        the same one :meth:`get_chunk_texts` reads. Restricted to the chunk ids
        the subgraph actually reached, so this never scans the whole source.
        """
        if not chunk_ids or not query_embedding:
            return {}
        table, _text_col, _metadata_col, source_col = _pgvector_identifiers()
        vector_col = _pgvector_vector_column()
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                sql.SQL(
                    """
                    SELECT id::text, 1 - ({vector} <=> %s::vector)
                    FROM {table}
                    WHERE {source} = %s AND id::text = ANY(%s);
                    """
                ).format(
                    vector=_identifier(vector_col),
                    table=_identifier(table),
                    source=_identifier(source_col),
                ),
                (query_embedding, source_id, [str(c) for c in chunk_ids]),
            )
            return {row[0]: float(row[1]) for row in cursor.fetchall()}
        except Exception as e:
            logging.error(f"Error scoring chunks against the query: {e}")
            return {}
        finally:
            cursor.close()
            conn.rollback()

    def get_chunk_texts(
        self,
        source_id: str,
        chunk_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Map chunk ids to ``{"text": ..., "metadata": {...}}`` from the pgvector table.

        Reads the co-located documents table, deriving its name and the text,
        metadata and source-id column names from the same defaults
        ``PGVectorStore`` uses so a customized deployment still resolves. Chunk
        ids are pgvector document ids (SERIAL) cast to text to match the
        JSONB-sourced string ids without per-id round trips.
        """
        if not chunk_ids:
            return {}
        table, text_col, metadata_col, source_col = _pgvector_identifiers()
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                sql.SQL(
                    """
                    SELECT id, {text}, {metadata} FROM {table}
                    WHERE {source} = %s AND id::text = ANY(%s);
                    """
                ).format(
                    text=_identifier(text_col),
                    metadata=_identifier(metadata_col),
                    table=_identifier(table),
                    source=_identifier(source_col),
                ),
                (source_id, [str(c) for c in chunk_ids]),
            )
            return {
                str(row[0]): {"text": row[1], "metadata": row[2] or {}}
                for row in cursor.fetchall()
            }
        except Exception as e:
            logging.error(f"Error getting chunk texts: {e}")
            return {}
        finally:
            cursor.close()
            conn.rollback()

    def get_node_detail(
        self, source_id: str, node_id: str, max_chunks: int = 20
    ) -> Optional[Dict[str, Any]]:
        """A node's full record plus a bounded list of its linked chunks.

        Returns ``None`` when the node does not belong to the source. Chunk texts
        are read from the co-located pgvector table; at most ``max_chunks`` are
        returned so a hub node never streams an unbounded payload.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT id, name, type, description, degree, doc_freq
                    FROM graph_nodes
                    WHERE source_id = %s AND id = %s;
                    """,
                    (source_id, node_id),
                )
                row = cursor.fetchone()
            finally:
                cursor.close()
            if row is None:
                return None
            node = {
                "id": str(row[0]),
                "name": row[1],
                "type": row[2],
                "description": row[3],
                "degree": row[4],
                "doc_freq": row[5],
            }

            chunk_ids = self.get_chunk_ids_for_nodes(source_id, [node_id]).get(
                str(node_id), []
            )[: max(0, int(max_chunks))]
            texts = (
                self.get_chunk_texts(source_id, chunk_ids) if chunk_ids else {}
            )
            node["chunks"] = [
                {
                    "chunk_id": cid,
                    "text": texts.get(cid, {}).get("text", ""),
                    "metadata": texts.get(cid, {}).get("metadata", {}),
                }
                for cid in chunk_ids
            ]
            return node
        except Exception as e:
            logging.error(f"Error getting node detail: {e}")
            return None
        finally:
            conn.rollback()

    def set_node_degrees(self, source_id: str):
        """Recompute every node's degree from its incident edges for a source.

        A self-loop counts once, matching ``add_edge``'s incremental update
        (``WHERE id IN (src, dst)`` bumps the endpoint a single time when
        ``src == dst``). ``UNION`` deduplicates the two endpoints of each edge.
        """
        self._ensure_tables_once()
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE graph_nodes n
                SET degree = COALESCE(d.deg, 0)
                FROM (
                    SELECT node_id, count(*) AS deg
                    FROM (
                        SELECT id, src_node_id AS node_id FROM graph_edges
                        WHERE source_id = %s
                        UNION
                        SELECT id, dst_node_id AS node_id FROM graph_edges
                        WHERE source_id = %s
                    ) incident
                    GROUP BY node_id
                ) d
                WHERE n.source_id = %s AND n.id = d.node_id;
                """,
                (source_id, source_id, source_id),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(f"Error setting node degrees: {e}")
            raise
        finally:
            cursor.close()

    def mark_chunk(self, source_id: str, chunk_id: str, status: str):
        """Record a chunk's extraction status, reconnecting once if the connection died."""
        self._ensure_tables_once()

        def _write(conn):
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO graph_ingest_progress (source_id, chunk_id, status)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_id, chunk_id) DO UPDATE SET status = EXCLUDED.status;
                    """,
                    (source_id, str(chunk_id), status),
                )
                conn.commit()
            except Exception as e:
                _safe_rollback(conn)
                logging.error(f"Error marking chunk: {e}")
                raise
            finally:
                cursor.close()

        return self._write_with_reconnect(_write)

    def pending_chunks(self, source_id: str, all_chunk_ids: List[str]) -> List[str]:
        """Chunk ids from ``all_chunk_ids`` not yet marked ``done`` for the source."""
        if not all_chunk_ids:
            return []
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT chunk_id FROM graph_ingest_progress
                WHERE source_id = %s AND status = 'done';
                """,
                (source_id,),
            )
            done = {row[0] for row in cursor.fetchall()}
            return [str(c) for c in all_chunk_ids if str(c) not in done]
        except Exception as e:
            logging.error(f"Error getting pending chunks: {e}")
            return [str(c) for c in all_chunk_ids]
        finally:
            cursor.close()
            conn.rollback()

    def get_progress(self, source_id: str) -> Dict[str, str]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT chunk_id, status FROM graph_ingest_progress "
                "WHERE source_id = %s;",
                (source_id,),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}
        except Exception as e:
            logging.error(f"Error getting progress: {e}")
            return {}
        finally:
            cursor.close()
            conn.rollback()

    def delete_by_source(self, source_id: str):
        """Remove every graph row for a source (no FK cascade across clusters)."""
        self._ensure_tables_once()
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            for table in (
                "graph_node_chunks",
                "graph_edges",
                "graph_nodes",
                "graph_ingest_progress",
            ):
                cursor.execute(
                    sql.SQL("DELETE FROM {} WHERE source_id = %s;").format(
                        sql.Identifier(table)
                    ),
                    (source_id,),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(f"Error deleting graph by source: {e}")
            raise
        finally:
            cursor.close()

    def close(self) -> None:
        """Release this store's connection: back to the pool, or closed outright.

        A pooled connection is rolled back first when it is still in a
        transaction, so the next borrower gets a clean session.
        """
        conn = getattr(self, "_connection", None)
        if conn is None:
            return
        self._connection = None
        pgconn.release(
            getattr(self, "_connection_string", ""),
            conn,
            getattr(self, "_pooled", False),
        )

    def __del__(self):
        """Release the connection when the object is destroyed. Never raises."""
        try:
            self.close()
        except Exception:
            # Interpreter teardown can null out module globals; never raise here.
            pass
