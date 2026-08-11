import logging
import math
import re
from typing import List, Optional, Any, Dict

from psycopg.types.json import Jsonb

from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document

# table name -> IVFFlat ``lists`` (None when the table has no such index)
_IVFFLAT_LISTS_CACHE: Dict[str, Optional[int]] = {}


class PGVectorStore(BaseVectorStore):
    def __init__(
        self,
        source_id: str = "",
        embeddings_key: str = "embeddings",
        table_name: str = "documents",
        decoded_token: Optional[str] = None,
        vector_column: str = "embedding",
        text_column: str = "text",
        metadata_column: str = "metadata",
        connection_string: str = None,
    ):
        super().__init__()
        # Store the source_id for use in add_chunk
        self._source_id = str(source_id).replace("application/indexes/", "").rstrip("/")
        self._embeddings_key = embeddings_key
        self._table_name = table_name
        self._vector_column = vector_column
        self._text_column = text_column
        self._metadata_column = metadata_column
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        
        # Use provided connection string or fall back to settings.
        # If PGVECTOR_CONNECTION_STRING is not set but POSTGRES_URI is,
        # reuse the same cluster — normalize from SQLAlchemy dialect to libpq form.
        self._connection_string = connection_string or getattr(settings, 'PGVECTOR_CONNECTION_STRING', None)

        if not self._connection_string and getattr(settings, 'POSTGRES_URI', None):
            from application.core.db_uri import normalize_pgvector_connection_string
            self._connection_string = normalize_pgvector_connection_string(settings.POSTGRES_URI)

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
        self._ensure_table_exists()

    def _get_connection(self):
        """Get or create database connection"""
        if self._connection is None or self._connection.closed:
            self._connection = self._psycopg.connect(self._connection_string)
            # Register pgvector types
            self._register_vector(self._connection)
            self._apply_ivfflat_probes(self._connection)
        return self._connection

    def _ivfflat_lists(self, conn) -> Optional[int]:
        """Return the ``lists`` value of this table's IVFFlat index, if any.

        Cached per table because it only changes when the index is rebuilt.
        """
        if self._table_name in _IVFFLAT_LISTS_CACHE:
            return _IVFFLAT_LISTS_CACHE[self._table_name]
        lists = None
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = %s AND indexdef ILIKE %s",
                    (self._table_name, "%ivfflat%"),
                )
                row = cursor.fetchone()
            if row:
                match = re.search(r"lists\s*=\s*'?(\d+)", row[0])
                if match:
                    lists = int(match.group(1))
        except Exception as e:  # index introspection must never break search
            logging.debug("Could not read IVFFlat lists for %s: %s", self._table_name, e)
        # Only cache a hit: an index may be created after this process booted,
        # and caching None would keep probes unset for the process's lifetime.
        if lists:
            _IVFFLAT_LISTS_CACHE[self._table_name] = lists
        return lists

    def _apply_ivfflat_probes(self, conn) -> None:
        """Raise ``ivfflat.probes`` so a filtered search cannot come back empty.

        An IVFFlat index partitions vectors into ``lists`` clusters and the
        default ``probes = 1`` scans exactly one of them. Our searches filter by
        ``source_id`` *after* the index picks candidates, so with one probe the
        candidates frequently all belong to other sources and the query returns
        nothing — retrieval reports zero documents and the model answers with no
        source material, silently. ``sqrt(lists)`` is pgvector's own recall
        guidance and costs a proportional amount of scan.
        """
        probes = settings.PGVECTOR_IVFFLAT_PROBES
        if probes is None:
            lists = self._ivfflat_lists(conn)
            if not lists:
                return
            probes = max(1, math.isqrt(lists))
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SET ivfflat.probes = {int(probes)};")
        except Exception as e:  # older pgvector / no index — search still works
            logging.debug("Could not set ivfflat.probes: %s", e)

    def _ensure_table_exists(self):
        """Create table and enable pgvector extension if they don't exist"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Enable pgvector extension
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            
            embedding_dim = getattr(self._embedding, 'dimension', 768)
            
            # Create table with vector column
            create_table_query = f"""
            CREATE TABLE IF NOT EXISTS {self._table_name} (
                id SERIAL PRIMARY KEY,
                {self._text_column} TEXT NOT NULL,
                {self._vector_column} vector({embedding_dim}),
                {self._metadata_column} JSONB,
                source_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
            cursor.execute(create_table_query)
            
            # NO vector index is created here, deliberately.
            #
            # This runs when the table is first created, i.e. on an EMPTY
            # table. IVFFlat computes its cluster centroids at build time, so
            # an index built on no rows gets random centroids and never
            # recovers — measured recall 0.06 once 5k rows are added. Combined
            # with our ``WHERE source_id = ...`` post-filter, that returned
            # ZERO rows for sources with hundreds of chunks: retrieval reported
            # no documents and the model answered from nothing, silently.
            # pgvector only warns when sampled_rows < lists, so the common bad
            # case is silent.
            #
            # Exact search is correct and fast well past the sizes most
            # deployments ever reach. Add an index deliberately, sized to real
            # data, once a corpus is large enough to need one.
            # Create index for source_id filtering
            source_index_query = f"""
            CREATE INDEX IF NOT EXISTS {self._table_name}_source_id_idx
            ON {self._table_name} (source_id);
            """
            cursor.execute(source_index_query)

            # Functional GIN index backing keyword_search full-text queries.
            fts_index_query = f"""
            CREATE INDEX IF NOT EXISTS {self._table_name}_text_fts_idx
            ON {self._table_name} USING gin(to_tsvector('english', {self._text_column}));
            """
            cursor.execute(fts_index_query)

            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(f"Error creating table: {e}")
            raise
        finally:
            cursor.close()

    score_kind = "cosine_similarity"

    def search(
        self,
        question: str,
        k: int = 2,
        *args,
        score_threshold: float = None,
        **kwargs,
    ) -> List[Document]:
        """Search for similar documents using vector similarity.

        Args:
            question: The query string.
            k: Maximum number of results.
            score_threshold: Optional cosine-similarity floor in ``[0, 1]``.
                Cosine distance = ``1 - similarity``; rows with similarity below
                the threshold (distance above ``1 - threshold``) are dropped.
        """
        return [
            doc
            for doc, _ in self.search_with_scores(
                question, k, *args, score_threshold=score_threshold, **kwargs
            )
        ]

    def _nearest_sql(self) -> str:
        """Build the nearest-neighbour SELECT for this store's table.

        Identifiers (table/column names) come from this instance's
        construction, never from a request, so they cannot be interpolated by a
        caller; the query *values* are always bound parameters.
        """
        return (
            f"SELECT {self._text_column}, {self._metadata_column}, "
            f"({self._vector_column} <=> %s::vector) AS distance "
            f"FROM {self._table_name} "
            "WHERE source_id = %s "
            f"ORDER BY {self._vector_column} <=> %s::vector "
            "LIMIT %s;"
        )

    def _exact_search(self, cursor, query_vector, k: int, ann_results: list) -> list:
        """Redo a short indexed search exactly, when the source has more rows.

        Args:
            cursor: Open cursor on the search connection.
            query_vector: The embedded query.
            k: Requested top-k.
            ann_results: What the indexed search returned.

        Returns:
            list: Exact rows when the indexed search under-returned, otherwise
            ``ann_results`` unchanged.
        """
        try:
            cursor.execute(
                f"SELECT count(*) FROM {self._table_name} WHERE source_id = %s",
                (self._source_id,),
            )
            available = cursor.fetchone()[0]
            if len(ann_results) >= min(k, available):
                return ann_results

            cursor.execute("SET LOCAL enable_indexscan = off;")
            cursor.execute("SET LOCAL enable_bitmapscan = off;")
            cursor.execute(
                self._nearest_sql(),
                (query_vector, self._source_id, query_vector, k),
            )
            exact = cursor.fetchall()
            if len(exact) > len(ann_results):
                logging.info(
                    "Vector index under-returned for source %s (%d of %d); "
                    "used exact search instead.",
                    self._source_id, len(ann_results), min(k, available),
                )
                return exact
            return ann_results
        except Exception as e:
            # Never let the safety net take down the search it is protecting —
            # but roll back, or the aborted transaction poisons the connection
            # and every later search on this store returns nothing.
            logging.warning("Exact-search fallback failed: %s", e)
            try:
                cursor.connection.rollback()
            except Exception:
                # Connection already gone; nothing left to roll back.
                pass
            return ann_results
        finally:
            try:
                # RESET, not "= on": a deployment may disable these globally.
                cursor.execute("RESET enable_indexscan;")
                cursor.execute("RESET enable_bitmapscan;")
            except Exception:
                # Cursor/transaction already unusable; the settings die with it.
                pass

    def search_with_scores(
        self,
        question: str,
        k: int = 2,
        *args,
        score_threshold: float = None,
        **kwargs,
    ) -> List[tuple]:
        """Same search as :meth:`search`, pairing each hit with its similarity.

        The score is the cosine similarity (``1 - cosine_distance``) — the exact
        quantity ``score_threshold`` is compared against, so a caller can read a
        result's score and pick a threshold from it directly.
        """
        query_vector = self._embedding.embed_query(question)

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Use cosine distance for similarity search with proper vector formatting
            search_query = self._nearest_sql()

            cursor.execute(search_query, (query_vector, self._source_id, query_vector, k))
            results = cursor.fetchall()

            # An ANN index filters ``source_id`` *after* choosing candidates, so
            # a source holding a small share of the table can come back short —
            # or empty — no matter how the index is tuned. Raising probes /
            # ef_search only moves that threshold. When the result looks short,
            # redo the query exactly: correctness is worth one extra scan, and a
            # silent empty result reaches the model as "no documents exist".
            if len(results) < k:
                results = self._exact_search(cursor, query_vector, k, results)

            max_distance = None
            if score_threshold is not None:
                max_distance = 1.0 - float(score_threshold)

            documents = []
            for text, metadata, distance in results:
                if max_distance is not None and distance is not None and distance > max_distance:
                    continue
                metadata = metadata or {}
                score = None if distance is None else 1.0 - float(distance)
                documents.append(
                    (Document(page_content=text, metadata=metadata), score)
                )

            return documents

        except Exception as e:
            logging.error(f"Error searching documents: {e}", exc_info=True)
            try:
                conn.rollback()
            except Exception:
                # Connection already gone; nothing left to roll back.
                pass
            return []
        finally:
            cursor.close()

    def keyword_search(self, question: str, k: int = 10) -> List[Document]:
        """Full-text keyword search using Postgres ``websearch_to_tsquery``.

        Returns the same ``Document`` shape as :meth:`search`. The question is
        bound as a query parameter (never interpolated) to prevent injection.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            keyword_query = f"""
            SELECT {self._text_column}, {self._metadata_column},
                   ts_rank(
                       to_tsvector('english', {self._text_column}),
                       websearch_to_tsquery('english', %s)
                   ) AS rank
            FROM {self._table_name}
            WHERE source_id = %s
              AND to_tsvector('english', {self._text_column})
                  @@ websearch_to_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT %s;
            """

            cursor.execute(
                keyword_query, (question, self._source_id, question, k)
            )
            results = cursor.fetchall()

            documents = []
            for text, metadata, _rank in results:
                metadata = metadata or {}
                documents.append(Document(page_content=text, metadata=metadata))

            return documents

        except Exception as e:
            logging.error(f"Error in keyword search: {e}", exc_info=True)
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
        """Add texts with their embeddings to the vector store"""
        if not texts:
            return []

        embeddings = self._embedding.embed_documents(texts)
        metadatas = metadatas or [{}] * len(texts)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            insert_query = f"""
            INSERT INTO {self._table_name} ({self._text_column}, {self._vector_column}, {self._metadata_column}, source_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """
            
            inserted_ids = []
            for text, embedding, metadata in zip(texts, embeddings, metadatas):
                cursor.execute(
                    insert_query,
                    (text, embedding, Jsonb(metadata), self._source_id)
                )
                inserted_id = cursor.fetchone()[0]
                inserted_ids.append(str(inserted_id))
            
            conn.commit()
            return inserted_ids
            
        except Exception as e:
            conn.rollback()
            logging.error(f"Error adding texts: {e}")
            raise
        finally:
            cursor.close()

    def delete_index(self, *args, **kwargs):
        """Delete all documents for this source_id"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            delete_query = f"DELETE FROM {self._table_name} WHERE source_id = %s;"
            cursor.execute(delete_query, (self._source_id,))
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            logging.error(f"Error deleting index: {e}")
            raise
        finally:
            cursor.close()

    def save_local(self, *args, **kwargs):
        """No-op for PostgreSQL - data is already persisted"""
        pass

    def get_chunks(self) -> List[Dict[str, Any]]:
        """Get all chunks for this source_id"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            select_query = f"""
            SELECT id, {self._text_column}, {self._metadata_column}
            FROM {self._table_name}
            WHERE source_id = %s;
            """
            cursor.execute(select_query, (self._source_id,))
            results = cursor.fetchall()
            
            chunks = []
            for doc_id, text, metadata in results:
                chunks.append({
                    "doc_id": str(doc_id),
                    "text": text,
                    "metadata": metadata or {}
                })
            
            return chunks
            
        except Exception as e:
            logging.error(f"Error getting chunks: {e}")
            return []
        finally:
            cursor.close()

    def add_chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Add a single chunk to the vector store"""
        metadata = metadata or {}

        final_metadata = metadata.copy()

        final_metadata["source_id"] = self._source_id

        embeddings = self._embedding.embed_documents([text])

        if not embeddings:
            raise ValueError("Could not generate embedding for chunk")
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            insert_query = f"""
            INSERT INTO {self._table_name} ({self._text_column}, {self._vector_column}, {self._metadata_column}, source_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """
            
            cursor.execute(
                insert_query,
                (text, embeddings[0], Jsonb(final_metadata), self._source_id)
            )
            inserted_id = cursor.fetchone()[0]
            conn.commit()
            
            return str(inserted_id)
            
        except Exception as e:
            conn.rollback()
            logging.error(f"Error adding chunk: {e}")
            raise
        finally:
            cursor.close()

    def delete_chunk(self, chunk_id: str) -> bool:
        """Delete a specific chunk by its ID"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            delete_query = f"DELETE FROM {self._table_name} WHERE id = %s AND source_id = %s;"
            cursor.execute(delete_query, (int(chunk_id), self._source_id))
            deleted_count = cursor.rowcount
            conn.commit()
            
            return deleted_count > 0
            
        except Exception as e:
            conn.rollback()
            logging.error(f"Error deleting chunk: {e}")
            return False
        finally:
            cursor.close()

    def delete_chunks_by_source_path(self, path: str) -> int:
        """Delete this source's chunks whose ``metadata.source`` equals ``path``.

        One targeted statement instead of the base loop+scan. The path is bound
        as a query parameter (never interpolated); only the internal table name
        is f-string interpolated. Returns the number of rows deleted.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            delete_query = (
                f"DELETE FROM {self._table_name} "
                f"WHERE source_id = %s AND {self._metadata_column}->>'source' = %s;"
            )
            cursor.execute(delete_query, (self._source_id, path))
            deleted_count = cursor.rowcount
            conn.commit()

            return deleted_count

        except Exception as e:
            conn.rollback()
            logging.error(f"Error deleting chunks by source path: {e}")
            raise
        finally:
            cursor.close()

    def __del__(self):
        """Close database connection when object is destroyed"""
        if hasattr(self, '_connection') and self._connection and not self._connection.closed:
            self._connection.close()