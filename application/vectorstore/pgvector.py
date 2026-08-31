import logging
import math
import re
from typing import List, Optional, Any, Dict

from psycopg.types.json import Jsonb

from application.core.settings import settings
from application.vectorstore import pgconn
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document

# table name -> IVFFlat ``lists`` (None when the table has no such index)
_IVFFLAT_LISTS_CACHE: Dict[str, Optional[int]] = {}

DEFAULT_EMBEDDING_DIM = 768
# Advisory-lock key shared with the boot hook so concurrent workers serialize DDL.
SCHEMA_LOCK_KEY = "docsgpt:vectors:ddl"

# The connection pools moved to ``application.vectorstore.pgconn`` so the graph
# store can share them without importing this module. Only the names something
# actually reaches through *this* module stay bound here — same objects, not
# copies: callers and tests read ``pgvector._POOLS``, patch
# ``pgvector._pool_for``, and assert on ``pgvector.DEFAULT_POOL_MAX_SIZE``.
# Anything else belongs to ``pgconn`` alone; re-exporting it here would just be
# a second name to keep in sync.
DEFAULT_POOL_MAX_SIZE = pgconn.DEFAULT_POOL_MAX_SIZE
_POOLS = pgconn._POOLS
_pool_for = pgconn.pool_for


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
        self._pooled = False
        self._pool_max_size = self._resolve_pool_max_size()
        # No DDL here. The retriever builds one store per source per request, so
        # construction must stay free: schema is owned at boot by
        # ``ensure_vector_schema``, and the write path below re-checks it once as
        # a safety net for processes that never ran the boot hook.
        self._schema_ensured = False

    # Shared with ``GraphStore`` via pgconn so the two can never disagree.
    _resolve_pool_max_size = staticmethod(pgconn.resolve_pool_max_size)

    def _get_connection(self):
        """Get or create this store's connection, pooled unless pooling is off."""
        if self._connection is not None and self._connection.closed:
            # Hand the dead connection back before replacing it: psycopg_pool
            # never reclaims a checkout that is not returned, so dropping it
            # costs the pool a slot for the life of the process.
            self.close()
        if self._connection is None:
            if self._pool_max_size > 0:
                self._connection = _pool_for(
                    self._connection_string, self._pool_max_size
                ).getconn()
                self._pooled = True
            else:
                self._connection = self._psycopg.connect(self._connection_string)
                # Register pgvector types
                self._register_pgvector_types(self._connection)
                self._pooled = False
            self._apply_probes_once(self._connection)
        return self._connection

    def _register_pgvector_types(self, conn) -> None:
        """Register pgvector's adapters, tolerating a not-yet-created extension.

        Kept as a method rather than calling :func:`pgconn.configure_pooled_connection`
        directly because ``self._register_vector`` is the seam the tests patch.
        """
        try:
            self._register_vector(conn)
        except Exception as e:
            logging.debug("pgvector types not registered yet: %s", e)

    def _apply_probes_once(self, conn) -> None:
        """Set ``ivfflat.probes`` once per physical connection and table.

        A pooled connection outlives the store that checked it out, and the
        ``SET`` is session-level, so the probe lookup must not repeat on every
        checkout. The marker lives on the connection object itself because that
        is what the pool recycles.
        """
        if getattr(conn, "_docsgpt_probes_table", None) == self._table_name:
            return
        self._apply_ivfflat_probes(conn)
        try:
            # ``SET`` (not SET LOCAL) is undone by a rollback, so make it stick
            # before any query runs on this connection.
            conn.commit()
            conn._docsgpt_probes_table = self._table_name
        except Exception as e:  # never let session tuning break a query
            logging.debug("Could not persist ivfflat.probes: %s", e)

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

    @staticmethod
    def create_schema(
        conn,
        *,
        table_name: str = "documents",
        vector_column: str = "embedding",
        text_column: str = "text",
        metadata_column: str = "metadata",
        dimension: int = DEFAULT_EMBEDDING_DIM,
    ) -> None:
        """Create the extension, table and indexes on ``conn`` without committing.

        Shared by the boot hook (``ensure_vector_schema``) and the store's own
        write-path safety net; the caller owns the transaction.

        Args:
            conn: Open psycopg connection.
            table_name: Documents table to create.
            vector_column: Embedding column name.
            text_column: Chunk-text column name.
            metadata_column: JSONB metadata column name.
            dimension: Width of the embedding vectors.
        """
        cursor = conn.cursor()

        try:
            # Enable pgvector extension
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # Create table with vector column
            create_table_query = f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id SERIAL PRIMARY KEY,
                {text_column} TEXT NOT NULL,
                {vector_column} vector({dimension}),
                {metadata_column} JSONB,
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
            CREATE INDEX IF NOT EXISTS {table_name}_source_id_idx
            ON {table_name} (source_id);
            """
            cursor.execute(source_index_query)

            # Functional GIN index backing keyword_search full-text queries.
            fts_index_query = f"""
            CREATE INDEX IF NOT EXISTS {table_name}_text_fts_idx
            ON {table_name} USING gin(to_tsvector('english', {text_column}));
            """
            cursor.execute(fts_index_query)
        finally:
            cursor.close()

    @staticmethod
    def table_dimension(
        conn, table_name: str = "documents", vector_column: str = "embedding"
    ) -> Optional[int]:
        """Width declared by the table's vector column, or ``None`` if unknown.

        ``None`` means the table is absent or the column is not a ``vector``.
        """
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT to_regclass(%s);", (table_name,))
            row = cursor.fetchone()
            if not row or row[0] is None:
                return None
            cursor.execute(
                "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                "WHERE a.attrelid = %s::regclass AND a.attname = %s "
                "AND NOT a.attisdropped",
                (table_name, vector_column),
            )
            row = cursor.fetchone()
            if not row or not row[0]:
                return None
            match = re.search(r"vector\((\d+)\)", str(row[0]))
            return int(match.group(1)) if match else None
        finally:
            cursor.close()

    def _ensure_table_exists(self) -> None:
        """Create this store's schema under an advisory lock, then commit."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s));", (SCHEMA_LOCK_KEY,)
                )
            finally:
                cursor.close()
            self.create_schema(
                conn,
                table_name=self._table_name,
                vector_column=self._vector_column,
                text_column=self._text_column,
                metadata_column=self._metadata_column,
                dimension=getattr(self._embedding, "dimension", DEFAULT_EMBEDDING_DIM),
            )
            conn.commit()
            # The extension may have just been created; pick up its adapters so
            # the insert that follows can bind a vector.
            self._register_pgvector_types(conn)
        except Exception as e:
            conn.rollback()
            logging.error(f"Error creating table: {e}")
            raise

    def _ensure_schema_once(self) -> None:
        """Create the schema on this instance's first write, at most once.

        Readers never create schema — boot owns it. This is the safety net for a
        process that never ran the boot hook (scripts, tests, the first ingest on
        a brand-new deployment); a read against a missing table surfaces
        psycopg's own error, like every other store.
        """
        if self._schema_ensured:
            return
        self._ensure_table_exists()
        self._schema_ensured = True

    score_kind = "cosine_similarity"

    def search(
        self,
        question: str,
        k: int = 2,
        *args,
        score_threshold: float = None,
        query_vector: Optional[List[float]] = None,
        **kwargs,
    ) -> List[Document]:
        """Search for similar documents using vector similarity.

        Args:
            question: The query string.
            k: Maximum number of results.
            score_threshold: Optional cosine-similarity floor in ``[0, 1]``.
                Cosine distance = ``1 - similarity``; rows with similarity below
                the threshold (distance above ``1 - threshold``) are dropped.
            query_vector: Precomputed embedding of ``question``. Supplied by a
                caller searching several sources with one query, so the query is
                embedded once instead of once per store.
        """
        return [
            doc
            for doc, _ in self.search_with_scores(
                question,
                k,
                *args,
                score_threshold=score_threshold,
                query_vector=query_vector,
                **kwargs,
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
        query_vector: Optional[List[float]] = None,
        **kwargs,
    ) -> List[tuple]:
        """Same search as :meth:`search`, pairing each hit with its similarity.

        The score is the cosine similarity (``1 - cosine_distance``) — the exact
        quantity ``score_threshold`` is compared against, so a caller can read a
        result's score and pick a threshold from it directly.

        Args:
            query_vector: Precomputed embedding of ``question``; when given the
                store skips embedding the query itself.
        """
        if query_vector is None:
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

            # End the read transaction. On a persistent (pooled) connection an
            # uncommitted SELECT leaves the backend "idle in transaction",
            # pinning a snapshot and blocking VACUUM for as long as the store
            # lives.
            conn.commit()
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

            conn.commit()
            return documents

        except Exception as e:
            logging.error(f"Error in keyword search: {e}", exc_info=True)
            try:
                conn.rollback()
            except Exception:
                # Connection already gone; nothing left to roll back.
                pass
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

        self._ensure_schema_once()
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

            conn.commit()
            return chunks

        except Exception as e:
            logging.error(f"Error getting chunks: {e}")
            try:
                conn.rollback()
            except Exception:
                # Connection already gone; nothing left to roll back.
                pass
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

        self._ensure_schema_once()
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

    def close(self) -> None:
        """Release this store's connection: back to the pool, or closed outright.

        A pooled connection is rolled back first when it is still in a
        transaction, so the next borrower gets a clean session.
        """
        conn = getattr(self, "_connection", None)
        if conn is None:
            return
        self._connection = None
        pgconn.release(self._connection_string, conn, getattr(self, "_pooled", False))

    def __del__(self):
        """Release the connection when the object is destroyed. Never raises."""
        try:
            self.close()
        except Exception:
            # Interpreter teardown can null out module globals; never raise here.
            pass