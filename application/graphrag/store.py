"""Per-source knowledge-graph store co-located with the pgvector ``documents`` table.

GraphRAG is pgvector-only: the graph tables live in the same DB as the
pgvector store and are created on-demand (``CREATE TABLE IF NOT EXISTS`` +
``CREATE EXTENSION IF NOT EXISTS vector``), mirroring
``PGVectorStore._ensure_table_exists`` rather than going through app-DB Alembic.
That DB may be a separate cluster (e.g. Neon) from the app DB where ``sources``
lives, so ``source_id`` is a plain indexed UUID column with no cross-DB FK and
all ids are generated in Python.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from psycopg.types.json import Jsonb

from application.core.settings import settings

DEFAULT_NAME_EMBEDDING_DIM = 768

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


def _pgvector_identifiers() -> tuple[str, str, str, str]:
    """Resolve ``(table, text_col, metadata_col, source_col)`` from ``PGVectorStore``.

    Reads the table and column defaults from ``PGVectorStore.__init__`` so the
    graph store queries the same names a customized deployment configured.
    """
    import inspect

    from application.vectorstore.pgvector import PGVectorStore

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


class GraphStore:
    """Stores and queries a per-source knowledge graph in the pgvector DB."""

    def __init__(self, connection_string: Optional[str] = None):
        self._connection_string = connection_string or getattr(
            settings, "PGVECTOR_CONNECTION_STRING", None
        )

        if not self._connection_string and getattr(settings, "POSTGRES_URI", None):
            from application.core.db_uri import normalize_pgvector_connection_string

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
        self._ensure_tables()

    def _get_connection(self):
        if self._connection is None or self._connection.closed:
            self._connection = self._psycopg.connect(self._connection_string)
            self._register_vector(self._connection)
        return self._connection

    def _embedding_dim(self) -> int:
        """Dimension of the configured embeddings model, matching ``PGVectorStore``.

        Falls back to ``DEFAULT_NAME_EMBEDDING_DIM`` so the graph table and the
        pgvector ``documents`` table always agree on the configured model.
        """
        from application.vectorstore.base import EmbeddingsSingleton

        embedding = EmbeddingsSingleton.get_instance(
            settings.EMBEDDINGS_NAME, settings.EMBEDDINGS_KEY
        )
        return getattr(embedding, "dimension", DEFAULT_NAME_EMBEDDING_DIM)

    def _ensure_tables(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            embedding_dim = self._embedding_dim()

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
                    name_embedding vector({embedding_dim}),
                    UNIQUE (source_id, normalized_name)
                );
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_edges (
                    id UUID PRIMARY KEY,
                    source_id UUID NOT NULL,
                    src_node_id UUID,
                    dst_node_id UUID,
                    type TEXT,
                    description TEXT,
                    weight REAL DEFAULT 1.0,
                    source_chunk_ids JSONB
                );
                """
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
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS graph_nodes_name_embedding_idx "
                "ON graph_nodes USING ivfflat (name_embedding vector_cosine_ops) "
                "WITH (lists = 100);"
            )

            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(f"Error creating graph tables: {e}")
            raise
        finally:
            cursor.close()

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
    ) -> str:
        """Insert an edge on an open cursor (no commit, no degree bump).

        Callers that batch many edges run ``set_node_degrees`` once afterwards
        instead of bumping degree per edge.
        """
        edge_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO graph_edges
                (id, source_id, src_node_id, dst_node_id, type, description,
                 weight, source_chunk_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
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
            ),
        )
        return edge_id

    def add_edge(
        self,
        source_id: str,
        src_node_id: str,
        dst_node_id: str,
        type: Optional[str] = None,
        description: Optional[str] = None,
        weight: float = 1.0,
        source_chunk_ids: Optional[List[str]] = None,
    ) -> str:
        """Insert an edge and bump the degree of both endpoints. Returns its id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            edge_id = self._add_edge(
                cursor, source_id, src_node_id, dst_node_id, type, description,
                weight, source_chunk_ids,
            )
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
        end. Returns ``(nodes_upserted, edges_added)``.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        node_ids: Dict[str, str] = {}
        edges_added = 0
        try:
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
                self._add_edge(
                    cursor,
                    source_id,
                    src_id,
                    dst_id,
                    type=rel.get("type"),
                    description=rel.get("description"),
                    weight=float(rel.get("weight") or 1.0),
                    source_chunk_ids=[chunk_id],
                )
                edges_added += 1

            conn.commit()
            return len(entities), edges_added
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

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
        normalized_name = clean.lower()
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

    def count_nodes(self, source_id: str) -> int:
        """Number of nodes for a source. Zero drives the ClassicRAG fallback."""
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
            return 0
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
                f"""
                SELECT id, {text_col}, {metadata_col} FROM {table}
                WHERE {source_col} = %s AND id::text = ANY(%s);
                """,
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
        conn = self._get_connection()
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
            conn.rollback()
            logging.error(f"Error marking chunk: {e}")
            raise
        finally:
            cursor.close()

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
                    f"DELETE FROM {table} WHERE source_id = %s;", (source_id,)
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(f"Error deleting graph by source: {e}")
            raise
        finally:
            cursor.close()

    def __del__(self):
        if (
            hasattr(self, "_connection")
            and self._connection
            and not self._connection.closed
        ):
            self._connection.close()
