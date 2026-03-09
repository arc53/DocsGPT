import json
import logging
import os
from typing import Any, Dict, List, Optional

from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document


class OracleVectorStore(BaseVectorStore):
    """
    Oracle Vector Store using Oracle 23ai/26ai Autonomous Database.

    Architecture:
      - LangChain OracleVS  →  add_texts(), search()
      - Raw oracledb SQL    →  get_chunks(), delete_index(), delete_chunk()
      - Wallet-based mTLS   →  Oracle 26ai Free Tier (Autonomous DB)

    Table schema is created by LangChain on first init.
    A function-based index on JSON_VALUE(metadata, '$.source_id') is added
    for efficient per-source filtering in all raw SQL operations.
    """

    def __init__(
        self,
        source_id: str = "",
        embeddings_key: str = "embeddings",
        table_name: str = "docsgpt_vectors",
        decoded_token: Optional[str] = None,
        connection_string: str = None,  # kept for interface consistency, not used
    ):
        super().__init__()

        # ── source_id (mirrors pgvector exactly) ──────────────────────────────
        self._source_id = (
            str(source_id).replace("application/indexes/", "").rstrip("/")
        )
        self._embeddings_key = embeddings_key
        self._table_name = table_name

        # ── Embeddings model (via base class, same as pgvector) ───────────────
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)

        # ── Oracle connection credentials ─────────────────────────────────────
        # Read from settings (pydantic) first, fall back to os.getenv for
        # fields that aren't yet in Settings class.
        self._oracle_user = (
            getattr(settings, "ORACLE_USER", None) or os.getenv("ORACLE_USER")
        )
        self._oracle_password = (
            getattr(settings, "ORACLE_PASSWORD", None) or os.getenv("ORACLE_PASSWORD")
        )
        self._oracle_dsn = (
            getattr(settings, "ORACLE_DSN", None) or os.getenv("ORACLE_DSN")
        )
        self._wallet_location = (
            getattr(settings, "ORACLE_WALLET_LOCATION", None)
            or os.getenv("ORACLE_WALLET_LOCATION")
        )
        self._wallet_password = (
            getattr(settings, "ORACLE_WALLET_PASSWORD", None)
            or os.getenv("ORACLE_WALLET_PASSWORD")
        )

        if not all([self._oracle_user, self._oracle_password, self._oracle_dsn]):
            raise ValueError(
                "Oracle connection requires ORACLE_USER, ORACLE_PASSWORD, and "
                "ORACLE_DSN to be set in your .env file."
            )

        # ── Import oracledb (thin mode — no Oracle Client libs needed) ────────
        try:
            import oracledb
        except ImportError:
            raise ImportError(
                "Could not import oracledb. "
                "Please install with: pip install oracledb"
            )
        self._oracledb = oracledb
        self._connection = None  # lazy; created in _get_connection()

        # ── Import LangChain OracleVS (used ONLY for add_texts + search) ──────
        try:
            from langchain_community.vectorstores.oraclevs import OracleVS
            from langchain_community.vectorstores.utils import DistanceStrategy
        except ImportError:
            raise ImportError(
                "Could not import LangChain Oracle VectorStore. "
                "Please install with: pip install langchain-community"
            )
        self._OracleVS = OracleVS
        self._DistanceStrategy = DistanceStrategy
        self._vectorstore = None

        # ── Boot sequence ──────────────────────────────────────────────────────
        # 1. LangChain creates the table (if not exists) with its standard schema.
        # 2. We then ensure a fast function-based index on source_id inside metadata.
        self._init_langchain_vectorstore()
        self._ensure_source_id_index()

    # ── Connection ─────────────────────────────────────────────────────────────

    def _get_connection(self):
        """
        Get or create a raw oracledb connection.
        Supports wallet-based mTLS for Oracle 26ai Autonomous DB.
        Mirrors pgvector's _get_connection().
        """
        if self._connection is None or not self._connection.is_healthy():
            connect_kwargs = dict(
                user=self._oracle_user,
                password=self._oracle_password,
                dsn=self._oracle_dsn,
            )
            # Wallet params (required for Oracle 26ai Free Tier)
            if self._wallet_location:
                connect_kwargs["config_dir"] = self._wallet_location
                connect_kwargs["wallet_location"] = self._wallet_location
            if self._wallet_password:
                connect_kwargs["wallet_password"] = self._wallet_password

            self._connection = self._oracledb.connect(**connect_kwargs)
            logging.info("Oracle DB connection established.")

        return self._connection

    # ── Init helpers ───────────────────────────────────────────────────────────

    def _init_langchain_vectorstore(self):
        """
        Init LangChain OracleVS, which creates the table if it does not exist.
        LangChain schema: id (VARCHAR2), text (CLOB), metadata (CLOB), embedding (VECTOR).
        """
        try:
            conn = self._get_connection()
            self._vectorstore = self._OracleVS(
                client=conn,
                embedding_function=self._embedding,
                table_name=self._table_name,
                distance_strategy=self._DistanceStrategy.COSINE,
            )
            logging.info(
                f"LangChain OracleVS ready (table: '{self._table_name}')."
            )
        except Exception as e:
            logging.error(f"Error initialising LangChain OracleVS: {e}", exc_info=True)
            raise

    def _ensure_source_id_index(self):
        """
        Add a function-based index on JSON_VALUE(metadata, '$.source_id').

        This gives raw SQL operations (get_chunks, delete_index, delete_chunk)
        the same performance as pgvector's dedicated source_id column + B-tree index,
        without altering the schema that LangChain manages.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        idx_name = f"{self._table_name}_srcid_idx".upper()

        try:
            cursor.execute(
                f"""
                DECLARE
                    v_count NUMBER;
                BEGIN
                    SELECT COUNT(*) INTO v_count
                    FROM   user_indexes
                    WHERE  index_name = :idx_name;

                    IF v_count = 0 THEN
                        EXECUTE IMMEDIATE '
                            CREATE INDEX {idx_name}
                            ON {self._table_name}
                            (JSON_VALUE(metadata, ''$.source_id''))
                        ';
                    END IF;
                END;
                """,
                {"idx_name": idx_name},
            )
            conn.commit()
            logging.info(f"Source-id index '{idx_name}' ensured.")
        except Exception as e:
            conn.rollback()
            logging.warning(f"Could not create source_id index (non-fatal): {e}")
        finally:
            cursor.close()

    # ── Public API ─────────────────────────────────────────────────────────────

    def search(self, question: str, k: int = 2, *args, **kwargs) -> List[Document]:
        """
        Search for similar documents.
        We embed the query ourselves (mirrors pgvector) and pass the raw vector
        to similarity_search_by_vector — bypasses LangChain's broken EmbeddingsWrapper handling.
        """
        try:
            # Generate query vector ourselves — same as pgvector
            query_vector = self._embedding.embed_query(question)
    
            # Pass raw vector directly — LangChain skips re-embedding
            results = self._vectorstore.similarity_search_by_vector(
                embedding=query_vector,
                k=k * 3,
            )

            documents = []
            for doc in results:
                meta = doc.metadata or {}
                if meta.get("source_id") == self._source_id:
                    documents.append(Document(page_content=doc.page_content, metadata=meta))
                if len(documents) == k:
                    break
            return documents
        
        except Exception as e:
            logging.error(f"Error searching Oracle VectorStore: {e}", exc_info=True)
            return []

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        *args,
        **kwargs,
    ) -> List[str]:
        """
        Add texts via LangChain OracleVS.
        LangChain handles embedding generation + INSERT in one call.
        source_id is injected into every metadata dict for later filtering.
        """
        if not texts:
            return []

        metadatas = metadatas or [{}] * len(texts)
        # Stamp source_id into every chunk's metadata (mirrors pgvector's source_id column)
        for meta in metadatas:
            meta["source_id"] = self._source_id

        try:
            ids = self._vectorstore.add_texts(texts=texts, metadatas=metadatas)
            return [str(i) for i in ids] if ids else []
        except Exception as e:
            logging.error(f"Error adding texts to Oracle: {e}", exc_info=True)
            raise

    def add_chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Add a single chunk. Delegates to add_texts (mirrors pgvector).
        """
        metadata = metadata or {}
        final_metadata = metadata.copy()
        final_metadata["source_id"] = self._source_id

        ids = self.add_texts(texts=[text], metadatas=[final_metadata])
        if ids:
            return ids[0]
        raise ValueError("Failed to insert chunk — no ID returned from Oracle.")

    def delete_index(self, *args, **kwargs):
        """
        Delete ALL documents for this source_id.
        Raw SQL — one DELETE, no LangChain, no loops. Mirrors pgvector exactly.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"""
                DELETE FROM {self._table_name}
                WHERE  JSON_VALUE(metadata, '$.source_id') = :1
                """,
                [self._source_id],
            )
            deleted = cursor.rowcount
            conn.commit()
            logging.info(
                f"delete_index: removed {deleted} rows for source_id '{self._source_id}'."
            )
        except Exception as e:
            conn.rollback()
            logging.error(f"Error in delete_index (Oracle): {e}")
            raise
        finally:
            cursor.close()

    def get_chunks(self) -> List[Dict[str, Any]]:
        """
        Return all chunks for this source_id.
        Raw SQL SELECT — fast, direct, no dummy similarity search. Mirrors pgvector.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"""
                SELECT id, text, metadata
                FROM   {self._table_name}
                WHERE  JSON_VALUE(metadata, '$.source_id') = :1
                """,
                [self._source_id],
            )
            rows = cursor.fetchall()

            chunks = []
            for doc_id, text_lob, metadata_lob in rows:
                # Oracle returns CLOB objects — read() converts to str
                text = text_lob.read() if hasattr(text_lob, "read") else text_lob
                if isinstance(metadata_lob, dict):
                    metadata = metadata_lob
                elif hasattr(metadata_lob, "read"):
                    try:
                        metadata = json.loads(metadata_lob.read())
                    except (json.JSONDecodeError, TypeError):
                        metadata = {}
                elif isinstance(metadata_lob, str):
                    try:
                        metadata = json.loads(metadata_lob)
                    except (json.JSONDecodeError, TypeError):
                        metadata = {}
                else:
                    metadata = {}

                chunks.append(
                    {"doc_id": str(doc_id), "text": text, "metadata": metadata}
                )
            return chunks

        except Exception as e:
            logging.error(f"Error in get_chunks (Oracle): {e}")
            return []
        finally:
            cursor.close()

    def delete_chunk(self, chunk_id: str) -> bool:
        """
        Delete a single chunk by ID, scoped to this source_id.
        Raw SQL DELETE — mirrors pgvector's safe 'WHERE id = ? AND source_id = ?'.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"""
                DELETE FROM {self._table_name}
                WHERE  id  = :1
                AND    JSON_VALUE(metadata, '$.source_id') = :2
                """,
                [chunk_id, self._source_id],
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted > 0

        except Exception as e:
            conn.rollback()
            logging.error(f"Error in delete_chunk (Oracle): {e}")
            return False
        finally:
            cursor.close()

    def save_local(self, *args, **kwargs):
        """No-op for Oracle — data is already persisted. Mirrors pgvector."""
        pass

    def __del__(self):
        """Close the raw oracledb connection on teardown. Mirrors pgvector."""
        if hasattr(self, "_connection") and self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
