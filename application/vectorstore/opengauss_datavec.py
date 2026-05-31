import json
import logging
import math
from typing import Any, Dict, List, Optional

from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document

_TABLE = "documents"
_INSERT_BATCH_SIZE = 500
_CONNECT_KWARGS = dict(
    keepalives=1,
    keepalives_idle=30,
    keepalives_interval=10,
    keepalives_count=5,
)


class OpenGaussDataVecStore(BaseVectorStore):
    """Vector store backed by openGauss DataVec.

    Single shared table 'documents' with fixed schema:
        id, text, embedding (vector), metadata (jsonb), source_id, created_at

    Requires OPENGAUSS_CONNECTION_STRING in settings.
    """

    # Set once on first instantiation via _load_driver()
    _psycopg2 = None
    _sql = None
    _pg_extras = None

    @classmethod
    def _load_driver(cls):
        if cls._psycopg2 is not None:
            return
        try:
            import psycopg2
            import psycopg2.sql
            from psycopg2 import extras
        except ImportError:
            raise ImportError(
                "psycopg2 is required for openGauss. "
                "Install with: pip install psycopg2-binary"
            )
        cls._psycopg2 = psycopg2
        cls._sql = psycopg2.sql
        cls._pg_extras = extras

    def __init__(self, source_id: str = "", embeddings_key: str = "embeddings"):
        super().__init__()
        self._load_driver()
        self._source_id = str(source_id)
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        self._embedding_dimension = self._resolve_embedding_dimension()
        self._conn_str = getattr(settings, "OPENGAUSS_CONNECTION_STRING", None)
        if not self._conn_str:
            raise ValueError("OPENGAUSS_CONNECTION_STRING is required in settings.")
        self._connection = None
        self._ensure_table_exists()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_connection(self):
        """Return the shared connection, reconnecting if closed or stale."""
        if self._connection is not None and not self._connection.closed:
            try:
                self._connection.poll()
                return self._connection
            except Exception:
                pass
        self._connection = self._psycopg2.connect(self._conn_str, **_CONNECT_KWARGS)
        return self._connection

    @staticmethod
    def _vec_to_str(vec) -> str:
        floats = [float(v) for v in vec]
        if any(math.isnan(f) or math.isinf(f) for f in floats):
            raise ValueError("Vector contains NaN or Inf values")
        return "[" + ",".join(str(f) for f in floats) + "]"

    @staticmethod
    def _parse_metadata(raw) -> dict:
        if isinstance(raw, dict):
            return raw
        if raw:
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                pass
        return {}

    def _resolve_embedding_dimension(self) -> int:
        """Resolve the actual embedding dimension via a probe call."""
        probe = self._embedding.embed_query("dimension probe")
        actual_dim = len(probe)
        if actual_dim <= 0:
            raise ValueError("Embedding probe returned an empty vector")

        declared = getattr(self._embedding, "dimension", None)
        if declared != actual_dim:
            logging.warning(
                "Embedding dimension mismatch: declared=%s actual=%s. Using actual.",
                declared,
                actual_dim,
            )
            try:
                self._embedding.dimension = actual_dim
            except Exception:
                pass
        return actual_dim

    def _ensure_table_exists(self):
        sql = self._sql
        table = sql.Identifier(_TABLE)
        conn = self._get_connection()
        with conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id         BIGSERIAL PRIMARY KEY,
                        text       TEXT NOT NULL,
                        embedding  vector({dim}),
                        metadata   JSONB,
                        source_id  TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """).format(table=table, dim=sql.Literal(int(self._embedding_dimension)))
            )
            cur.execute(
                sql.SQL("""
                    CREATE INDEX IF NOT EXISTS {idx}
                    ON {table} USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);
                """).format(
                    idx=sql.Identifier(f"{_TABLE}_embedding_ivfflat_idx"),
                    table=table,
                )
            )
            cur.execute(
                sql.SQL("""
                    CREATE INDEX IF NOT EXISTS {idx}
                    ON {table} (source_id);
                """).format(
                    idx=sql.Identifier(f"{_TABLE}_source_id_idx"),
                    table=table,
                )
            )

    # ------------------------------------------------------------------
    # BaseVectorStore interface
    # ------------------------------------------------------------------

    def search(self, question: str, k: int = 2, *args, **kwargs) -> List[Document]:
        sql = self._sql
        query_vec = self._embedding.embed_query(question)
        try:
            conn = self._get_connection()
            with conn, conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT text, metadata
                        FROM   {table}
                        WHERE  source_id = %s
                        ORDER  BY embedding <-> %s::vector
                        LIMIT  %s;
                    """).format(table=sql.Identifier(_TABLE)),
                    (self._source_id, self._vec_to_str(query_vec), k),
                )
                return [
                    Document(
                        page_content=text, metadata=self._parse_metadata(meta)
                    )
                    for text, meta in cur.fetchall()
                ]
        except Exception as e:
            logging.error(f"OpenGaussDataVecStore.search error: {e}", exc_info=True)
            return []

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        *args,
        **kwargs,
    ) -> List[str]:
        if not texts:
            return []
        sql = self._sql
        embeddings = self._embedding.embed_documents(texts)
        metadatas = metadatas or [{}] * len(texts)
        rows = [
            (text, self._vec_to_str(emb), json.dumps(meta), self._source_id)
            for text, emb, meta in zip(texts, embeddings, metadatas)
        ]

        query = sql.SQL("""
            INSERT INTO {table} (text, embedding, metadata, source_id)
            VALUES %s
            RETURNING id;
        """).format(table=sql.Identifier(_TABLE))

        conn = self._get_connection()
        inserted_ids = []
        with conn, conn.cursor() as cur:
            for i in range(0, len(rows), _INSERT_BATCH_SIZE):
                self._pg_extras.execute_values(
                    cur,
                    query.as_string(cur),
                    rows[i : i + _INSERT_BATCH_SIZE],
                    template="(%s, %s::vector, %s::jsonb, %s)",
                    fetch=True,
                )
                inserted_ids.extend(str(row[0]) for row in cur.fetchall())
        return inserted_ids

    def delete_index(self, *args, **kwargs):
        sql = self._sql
        conn = self._get_connection()
        with conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("DELETE FROM {table} WHERE source_id = %s;").format(
                    table=sql.Identifier(_TABLE)
                ),
                (self._source_id,),
            )

    def save_local(self, *args, **kwargs):
        pass

    def get_chunks(self) -> List[Dict[str, Any]]:
        sql = self._sql
        try:
            conn = self._get_connection()
            with conn, conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT id, text, metadata FROM {table} WHERE source_id = %s;"
                    ).format(table=sql.Identifier(_TABLE)),
                    (self._source_id,),
                )
                return [
                    {
                        "doc_id": str(doc_id),
                        "text": text,
                        "metadata": self._parse_metadata(meta),
                    }
                    for doc_id, text, meta in cur.fetchall()
                ]
        except Exception as e:
            logging.error(f"OpenGaussDataVecStore.get_chunks error: {e}")
            return []

    def add_chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        return self.add_texts([text], [metadata or {}])[0]

    def delete_chunk(self, chunk_id: str) -> bool:
        sql = self._sql
        try:
            conn = self._get_connection()
            with conn, conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        "DELETE FROM {table} WHERE id = %s AND source_id = %s;"
                    ).format(table=sql.Identifier(_TABLE)),
                    (int(chunk_id), self._source_id),
                )
                return cur.rowcount > 0
        except Exception as e:
            logging.error(f"OpenGaussDataVecStore.delete_chunk error: {e}")
            return False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self._connection and not self._connection.closed:
            self._connection.close()
        return False

    def __del__(self):
        if hasattr(self, "_connection") and self._connection and not self._connection.closed:
            self._connection.close()
