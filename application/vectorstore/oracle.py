"""Oracle Database 23ai Vector Store for DocsGPT.

Supports Oracle Database 23ai's native VECTOR data type and vector similarity
search via the ``oracledb`` Python driver.

Requires:
    - Oracle Database 23ai (or later) with VECTOR datatype support.
    - ``oracledb`` package (``pip install oracledb``).
    - A database user with privileges to create tables and vector indexes.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document


logger = logging.getLogger(__name__)


class OracleVectorStore(BaseVectorStore):
    """Oracle Database 23ai vector store.

    Stores document embeddings in an Oracle table using the native ``VECTOR``
    column type and performs similarity search with ``VECTOR_DISTANCE()``.
    """

    def __init__(
        self,
        source_id: str = "",
        embeddings_key: str = "embeddings",
        table_name: str = "docsgpt_documents",
        vector_column: str = "embedding",
        text_column: str = "text",
        metadata_column: str = "metadata",
        user: Optional[str] = None,
        password: Optional[str] = None,
        dsn: Optional[str] = None,
        connection_string: Optional[str] = None,
    ):
        """Initialize the Oracle vector store.

        Args:
            source_id: Unique identifier for the document source.
            embeddings_key: Key/label for the embedding model.
            table_name: Name of the Oracle table to store vectors in.
            vector_column: Name of the VECTOR column.
            text_column: Name of the text content column.
            metadata_column: Name of the JSON metadata column.
            user: Oracle database username (overrides ``ORACLE_USER``).
            password: Oracle database password (overrides ``ORACLE_PASSWORD``).
            dsn: Oracle DSN / Easy Connect string (overrides ``ORACLE_DSN``).
            connection_string: Full ``oracledb.connect()`` connection string
                (overrides individual user/password/dsn). Format:
                ``user/password@dsn``
        """
        super().__init__()

        self._source_id = str(source_id).replace("application/indexes/", "").rstrip("/")
        self._embeddings_key = embeddings_key
        self._table_name = table_name
        self._vector_column = vector_column
        self._text_column = text_column
        self._metadata_column = metadata_column
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)

        # Resolve connection parameters: explicit args > settings > env
        self._user = user or getattr(settings, "ORACLE_USER", None)
        self._password = password or getattr(settings, "ORACLE_PASSWORD", None)
        self._dsn = dsn or getattr(settings, "ORACLE_DSN", None)

        # A full connection string (user/password@dsn) takes precedence
        self._connection_string = connection_string or getattr(
            settings, "ORACLE_CONNECTION_STRING", None
        )

        if not any([self._connection_string, (self._user and self._password and self._dsn)]):
            raise ValueError(
                "Oracle connection parameters are required. "
                "Set ORACLE_USER, ORACLE_PASSWORD, and ORACLE_DSN in settings, "
                "or set ORACLE_CONNECTION_STRING, "
                "or pass connection_string/user/password/dsn parameters."
            )

        try:
            import oracledb
        except ImportError:
            raise ImportError(
                "Could not import the oracledb Python driver. "
                "Please install it with `pip install oracledb`."
            )

        self._oracledb = oracledb
        self._connection: Optional[Any] = None
        self._ensure_table_exists()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_connection(self):
        """Get or create a database connection."""
        if self._connection is None:
            self._connection = self._connect()
        else:
            try:
                # Lightweight round-trip check; cursor open implies connected.
                with self._connection.cursor():
                    pass
            except Exception:
                # Connection is stale — reconnect.
                logger.info("Oracle connection stale, reconnecting.")
                self._close_connection()
                self._connection = self._connect()
        return self._connection

    def _connect(self):
        """Create a new Oracle database connection."""
        if self._connection_string:
            logger.debug("Connecting to Oracle via connection string.")
            return self._oracledb.connect(self._connection_string)

        logger.debug(
            "Connecting to Oracle with user=%s, dsn=%s", self._user, self._dsn
        )
        return self._oracledb.connect(user=self._user, password=self._password, dsn=self._dsn)

    def _close_connection(self):
        """Close the current connection if open."""
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def _ensure_table_exists(self):
        """Create the table and vector index if they don't already exist."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            embedding_dim = getattr(self._embedding, "dimension", 768)

            # Create the documents table with a VECTOR column.
            # Oracle 23ai supports VECTOR(n, FLOAT64) as a native column type.
            create_table_sql = f"""
            CREATE TABLE {self._table_name} (
                id NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                {self._text_column} CLOB NOT NULL,
                {self._vector_column} VECTOR({embedding_dim}, FLOAT64),
                {self._metadata_column} CLOB,
                source_id VARCHAR2(1000) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            cursor.execute(create_table_sql)
            conn.commit()
            logger.info("Created table %s.", self._table_name)

        except Exception as exc:
            # ORA-00955: name is already used by an existing object
            # (table already exists) — this is expected on re-init.
            conn.rollback()
            if "ORA-00955" not in str(exc):
                logger.warning("Table may already exist: %s", exc)

        try:
            # Create an HNSW vector index for approximate nearest neighbour search.
            # Oracle 23ai supports: VECTOR INDEX … ORGANIZATION NEIGHBOR PARTITIONS
            # with DISTANCE COSINE and TARGET ACCURACY.
            index_name = f"{self._table_name}_{self._vector_column}_idx"
            # Oracle object names are capped at 30 bytes by default; truncate if needed.
            index_name = index_name[:30]

            create_index_sql = f"""
            CREATE VECTOR INDEX {index_name}
            ON {self._table_name}({self._vector_column})
            ORGANIZATION NEIGHBOR PARTITIONS
            DISTANCE COSINE
            WITH TARGET ACCURACY 95
            """
            cursor.execute(create_index_sql)
            conn.commit()
            logger.info("Created vector index %s.", index_name)

        except Exception as exc:
            conn.rollback()
            if "ORA-00955" not in str(exc):
                logger.warning("Vector index may already exist: %s", exc)

        try:
            # B-tree index on source_id for efficient filtering.
            source_idx_name = f"{self._table_name}_src_idx"[:30]
            cursor.execute(
                f"CREATE INDEX {source_idx_name} ON {self._table_name}(source_id)"
            )
            conn.commit()

        except Exception as exc:
            conn.rollback()
            if "ORA-00955" not in str(exc):
                logger.warning("source_id index may already exist: %s", exc)

        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Public API  (required by BaseVectorStore)
    # ------------------------------------------------------------------

    def search(self, question: str, k: int = 2, *args, **kwargs) -> List[Document]:
        """Search for the *k* most similar documents using cosine distance."""
        query_vector = self._embedding.embed_query(question)

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Oracle uses VECTOR_DISTANCE() for similarity and
            # FETCH FIRST … ROWS ONLY instead of LIMIT.
            search_sql = f"""
            SELECT {self._text_column}, {self._metadata_column},
                   VECTOR_DISTANCE({self._vector_column}, :qv, COSINE) AS distance
            FROM {self._table_name}
            WHERE source_id = :sid
            ORDER BY VECTOR_DISTANCE({self._vector_column}, :qv2, COSINE)
            FETCH FIRST :k ROWS ONLY
            """
            cursor.execute(
                search_sql,
                qv=self._encode_vector(query_vector),
                sid=self._source_id,
                qv2=self._encode_vector(query_vector),
                k=k,
            )
            results = cursor.fetchall()

            documents = []
            for row in results:
                text = row[0]
                metadata_raw = row[1]
                metadata = self._decode_metadata(metadata_raw)
                documents.append(Document(page_content=text, metadata=metadata))

            return documents

        except Exception as e:
            logger.error("Error searching documents: %s", e, exc_info=True)
            return []
        finally:
            cursor.close()

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        *args,
        **kwargs,
    ) -> List[str]:
        """Add a list of texts with their embeddings to the store.

        Returns a list of inserted row IDs as strings.
        """
        if not texts:
            return []

        embeddings = self._embedding.embed_documents(texts)
        metadatas = metadatas or [{}] * len(texts)

        conn = self._get_connection()
        cursor = conn.cursor()

        # Oracle's RETURNING … INTO needs an OUT bind variable.
        # We use a PL/SQL block or the simpler rowid approach.
        # Here we use INSERT … RETURNING id INTO :rid with a bind variable.
        insert_sql = f"""
        INSERT INTO {self._table_name}
            ({self._text_column}, {self._vector_column}, {self._metadata_column}, source_id)
        VALUES (:txt, :vec, :meta, :sid)
        RETURNING id INTO :rid
        """

        inserted_ids = []
        try:
            for text, embedding, metadata in zip(texts, embeddings, metadatas):
                row_id = cursor.var(self._oracledb.NUMBER)
                cursor.execute(
                    insert_sql,
                    txt=text,
                    vec=self._encode_vector(embedding),
                    meta=self._encode_metadata(metadata),
                    sid=self._source_id,
                    rid=row_id,
                )
                inserted_ids.append(str(row_id.getvalue()[0]))

            conn.commit()
            return inserted_ids

        except Exception as e:
            conn.rollback()
            logger.error("Error adding texts: %s", e)
            raise
        finally:
            cursor.close()

    def delete_index(self, *args, **kwargs):
        """Delete all documents for the current *source_id*."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                f"DELETE FROM {self._table_name} WHERE source_id = :sid",
                sid=self._source_id,
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("Error deleting index: %s", e)
            raise
        finally:
            cursor.close()

    def save_local(self, *args, **kwargs):
        """No-op — data is already persisted in Oracle Database."""
        pass

    def get_chunks(self) -> List[Dict[str, Any]]:
        """Return all chunks for the current *source_id*."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                f"SELECT id, {self._text_column}, {self._metadata_column} "
                f"FROM {self._table_name} "
                f"WHERE source_id = :sid "
                f"ORDER BY id",
                sid=self._source_id,
            )
            results = cursor.fetchall()

            chunks = []
            for doc_id, text, metadata_raw in results:
                chunks.append({
                    "doc_id": str(doc_id),
                    "text": text,
                    "metadata": self._decode_metadata(metadata_raw),
                })
            return chunks

        except Exception as e:
            logger.error("Error getting chunks: %s", e)
            return []
        finally:
            cursor.close()

    def add_chunk(
        self, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a single chunk and return its row ID."""
        metadata = metadata or {}
        final_metadata = metadata.copy()
        final_metadata["source_id"] = self._source_id

        embeddings = self._embedding.embed_documents([text])
        if not embeddings:
            raise ValueError("Could not generate embedding for chunk")

        conn = self._get_connection()
        cursor = conn.cursor()

        insert_sql = f"""
        INSERT INTO {self._table_name}
            ({self._text_column}, {self._vector_column}, {self._metadata_column}, source_id)
        VALUES (:txt, :vec, :meta, :sid)
        RETURNING id INTO :rid
        """

        try:
            row_id = cursor.var(self._oracledb.NUMBER)
            cursor.execute(
                insert_sql,
                txt=text,
                vec=self._encode_vector(embeddings[0]),
                meta=self._encode_metadata(final_metadata),
                sid=self._source_id,
                rid=row_id,
            )
            conn.commit()
            return str(row_id.getvalue()[0])

        except Exception as e:
            conn.rollback()
            logger.error("Error adding chunk: %s", e)
            raise
        finally:
            cursor.close()

    def delete_chunk(self, chunk_id: str) -> bool:
        """Delete a single chunk by its row ID.

        Returns ``True`` if a row was deleted, ``False`` otherwise.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                f"DELETE FROM {self._table_name} WHERE id = :cid AND source_id = :sid",
                cid=int(chunk_id),
                sid=self._source_id,
            )
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count > 0

        except Exception as e:
            conn.rollback()
            logger.error("Error deleting chunk: %s", e)
            return False
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_vector(vector: List[float]) -> str:
        """Format a Python float list as an Oracle VECTOR literal string.

        Oracle accepts the format ``'[1.5, 2.3, -0.7]'`` for vector bind
        parameters when passed as a string. The oracledb driver may also
        accept a list-of-floats directly in some versions; the string
        representation is the most portable approach.
        """
        return "[" + ", ".join(str(v) for v in vector) + "]"

    @staticmethod
    def _encode_metadata(metadata: dict) -> Optional[str]:
        """Serialize metadata dict to a JSON string for the CLOB column."""
        if not metadata:
            return None
        return json.dumps(metadata)

    @staticmethod
    def _decode_metadata(metadata_raw: Any) -> dict:
        """Deserialize the CLOB metadata column back to a dict."""
        if metadata_raw is None:
            return {}
        if isinstance(metadata_raw, dict):
            return metadata_raw
        if isinstance(metadata_raw, str):
            try:
                return json.loads(metadata_raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        # CLOB objects from oracledb may need .read()
        if hasattr(metadata_raw, "read"):
            try:
                return json.loads(metadata_raw.read())
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    def __del__(self):
        """Close the database connection when the object is garbage-collected."""
        if hasattr(self, "_connection"):
            self._close_connection()
