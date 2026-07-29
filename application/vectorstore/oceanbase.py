"""OceanBase vector-store adapter for DocsGPT."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from sqlalchemy import JSON, Column, String, Table, column, delete, literal

from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document

logger = logging.getLogger(__name__)


def _import_oceanbase_vector_store() -> Any:
    """Import the optional langchain-oceanbase integration on first use.

    Returns:
        The ``OceanbaseVectorStore`` class.

    Raises:
        ImportError: If ``langchain-oceanbase`` (or its pyobvector backend)
            is unavailable.
    """
    try:
        from langchain_oceanbase.vectorstores import OceanbaseVectorStore
    except ImportError as exc:
        raise ImportError(
            "Could not import the OceanBase vector-store dependencies. "
            "Install them with `pip install 'langchain-oceanbase>=0.6,<0.7'`."
        ) from exc

    return OceanbaseVectorStore


class OceanBaseStore(BaseVectorStore):
    """Store DocsGPT document chunks in an externally managed OceanBase.

    Dense-vector indexing and similarity search use ``langchain-oceanbase``.
    DocsGPT-specific chunk listing and targeted deletion use the underlying
    pyobvector client exposed by that integration.
    """

    TABLE_NAME = "docsgpt"
    SOURCE_ID_FIELD = "source_id"
    SUPPORTED_CONNECTION_SCHEMES = frozenset({"mysql", "mysql+pymysql"})

    score_kind = "cosine_similarity"

    def __init__(
        self,
        source_id: str = "",
        embeddings_key: str = "embeddings",
        connection_string: str | None = None,
    ) -> None:
        """Initialize an OceanBase vector store.

        Args:
            source_id: DocsGPT source identifier used to isolate all operations.
            embeddings_key: API key passed to DocsGPT's embedding factory.
            connection_string: Optional OceanBase URI. Supported schemes are
                ``mysql`` and ``mysql+pymysql``.

        Raises:
            ValueError: If the connection string is invalid.
            ImportError: If the optional OceanBase dependencies are unavailable.
        """
        super().__init__()

        self._source_id = str(source_id or "").replace("application/indexes/", "").rstrip("/")
        self._table_name = self.TABLE_NAME

        configured_connection = connection_string or settings.OCEANBASE_URI
        if not configured_connection:
            raise ValueError("OceanBase connection string is required. Set OCEANBASE_URI or pass connection_string.")
        connection_args = self._parse_connection_string(configured_connection)

        oceanbase_vector_store = _import_oceanbase_vector_store()
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)

        self._docsearch = oceanbase_vector_store(
            embedding_function=self._embedding,
            table_name=self._table_name,
            connection_args=connection_args,
            vidx_metric_type="cosine",
            extra_columns=[
                Column(
                    self.SOURCE_ID_FIELD,
                    String(255),
                    nullable=False,
                    index=True,
                )
            ],
        )
        self._client = self._docsearch.obvector
        self._source_filter = self._compile_source_filter()

    @classmethod
    def _parse_connection_string(cls, connection_string: str) -> dict[str, str]:
        """Convert a database URI into langchain-oceanbase connection args.

        Args:
            connection_string: URI containing user, password, host, port, and
                database name.

        Returns:
            A connection dictionary accepted by ``OceanbaseVectorStore``.

        Raises:
            ValueError: If the URI is malformed or uses an unsupported scheme.
        """
        if not isinstance(connection_string, str) or not connection_string.strip():
            raise ValueError("OceanBase connection string must not be empty.")

        parsed = urlsplit(connection_string.strip())
        scheme = parsed.scheme.lower()
        if scheme not in cls.SUPPORTED_CONNECTION_SCHEMES:
            supported = ", ".join(sorted(cls.SUPPORTED_CONNECTION_SCHEMES))
            raise ValueError(f"Unsupported OceanBase connection scheme '{parsed.scheme}'. Use one of: {supported}.")

        if not parsed.hostname:
            raise ValueError("OceanBase connection string must include a host.")
        if not parsed.username:
            raise ValueError("OceanBase connection string must include a user.")

        database = unquote(parsed.path.strip("/"))
        if not database or "/" in database:
            raise ValueError("OceanBase connection string must include one database name.")

        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("OceanBase connection string contains an invalid port.") from exc
        # Require an explicit port: direct connections (2881) and ODP/proxy
        # connections (2883) differ, so silently defaulting is a footgun.
        if port is None:
            raise ValueError("OceanBase connection string must include a port (2881 direct, 2883 via ODP).")

        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"

        return {
            "host": host,
            "port": str(port),
            "user": unquote(parsed.username),
            "password": unquote(parsed.password or ""),
            "db_name": database,
        }

    def _compile_source_filter(self) -> str:
        """Build a safely quoted source filter for langchain-oceanbase."""
        dialect = self._client.engine.dialect
        field_name = dialect.identifier_preparer.quote(self.SOURCE_ID_FIELD)
        source_literal = literal(self._source_id).compile(
            dialect=dialect,
            compile_kwargs={"literal_binds": True},
        )
        return f"{field_name} = {source_literal}"

    def _table_exists(self) -> bool:
        """Return whether the configured vector table exists."""
        return bool(self._client.check_table_exists(self._table_name))

    def _source_condition(self) -> Any:
        """Build the SQLAlchemy condition that enforces source isolation."""
        return column(self.SOURCE_ID_FIELD) == self._source_id

    def _metadata_source_condition(self, path: str) -> Any:
        """Build a server-side JSON condition for ``metadata.source``."""
        metadata_column = column(self._docsearch.metadata_field, JSON)
        return metadata_column["source"].as_string() == str(path)

    @staticmethod
    def _materialize_rows(result: Any) -> list[Any]:
        """Convert a pyobvector result into a concrete row list."""
        if result is None:
            return []
        fetchall = getattr(result, "fetchall", None)
        if callable(fetchall):
            return list(fetchall())
        return list(result)

    @staticmethod
    def _decode_metadata(value: Any) -> dict[str, Any]:
        """Decode the JSON metadata representation returned by OceanBase."""
        if isinstance(value, (str, bytes)):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
                return {}
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _to_document(document: Any) -> Document:
        """Convert a LangChain document into DocsGPT's document type."""
        converted = Document(
            page_content=str(document.page_content or ""),
            metadata=dict(document.metadata or {}),
        )
        document_id = getattr(document, "id", None)
        if document_id is not None:
            converted.id = str(document_id)
        return converted

    def _get_matching_ids(
        self,
        *,
        ids: Sequence[str] | None = None,
        limit: int | None = None,
        extra_conditions: Sequence[Any] | None = None,
    ) -> list[str]:
        """Return IDs matching this source and optional server-side filters."""
        if not self._table_exists():
            return []

        conditions = [self._source_condition()]
        conditions.extend(extra_conditions or [])
        result = self._client.get(
            table_name=self._table_name,
            ids=list(ids) if ids is not None else None,
            where_clause=conditions,
            output_column_name=[self._docsearch.primary_field],
            n_limits=limit,
        )
        return [str(row[0]) for row in self._materialize_rows(result) if row and row[0] is not None]

    def _delete_ids(self, ids: Sequence[str]) -> None:
        """Delete IDs while retaining the source-isolation condition."""
        if not ids:
            return
        self._client.delete(
            table_name=self._table_name,
            ids=[str(document_id) for document_id in ids],
            where_clause=[self._source_condition()],
        )

    def _delete_where(self, *conditions: Any) -> int:
        """Delete rows matching all conditions and return the affected row count."""
        table = Table(
            self._table_name,
            self._client.metadata_obj,
            autoload_with=self._client.engine,
            extend_existing=True,
        )
        with self._client.engine.connect() as conn, conn.begin():
            result = conn.execute(delete(table).where(*conditions))
            return result.rowcount or 0

    def search(
        self,
        question: str,
        k: int = 2,
        *args: Any,
        score_threshold: float | None = None,
        **kwargs: Any,
    ) -> list[Document]:
        """Search for chunks using cosine similarity.

        Args:
            question: Query text.
            k: Maximum number of chunks to return.
            score_threshold: Optional minimum cosine similarity.

        Returns:
            Matching DocsGPT documents in descending similarity order.
        """
        return [
            document
            for document, _ in self.search_with_scores(
                question,
                k,
                *args,
                score_threshold=score_threshold,
                **kwargs,
            )
        ]

    def search_with_scores(
        self,
        question: str,
        k: int = 2,
        *args: Any,
        score_threshold: float | None = None,
        **kwargs: Any,
    ) -> list[tuple[Document, float]]:
        """Search for chunks and return higher-is-better cosine similarities.

        ``langchain-oceanbase`` returns raw cosine distances. This method
        converts each distance to ``1 - distance`` and translates DocsGPT's
        similarity threshold into pyobvector's server-side distance threshold.

        Args:
            question: Query text.
            k: Maximum number of chunks to return.
            score_threshold: Optional minimum cosine similarity.

        Returns:
            Pairs of DocsGPT documents and cosine-similarity scores.
        """
        if k <= 0:
            return []

        try:
            if not self._table_exists():
                return []

            kwargs.pop("fltr", None)

            threshold = float(score_threshold) if score_threshold is not None else None
            if threshold is not None:
                kwargs["distance_threshold"] = 1.0 - threshold

            raw_results = self._docsearch.similarity_search_with_score(
                question,
                k,
                *args,
                fltr=self._source_filter,
                **kwargs,
            )

            results: list[tuple[Document, float]] = []
            for langchain_document, distance in raw_results:
                if distance is None:
                    continue
                score = 1.0 - float(distance)
                # Re-check the threshold client-side on purpose: the
                # server-side distance_threshold pass-through depends on the
                # langchain-oceanbase version in use.
                if threshold is not None and score < threshold:
                    continue
                results.append((self._to_document(langchain_document), score))
            return results
        except Exception:
            logger.exception("Error searching OceanBase vectors")
            return []

    def add_texts(
        self,
        texts: Iterable[str],
        metadatas: Sequence[dict[str, Any]] | None = None,
        *args: Any,
        ids: Sequence[str] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """Embed and add text chunks to OceanBase.

        Args:
            texts: Chunk texts to embed.
            metadatas: Metadata corresponding to each text.
            ids: Optional stable IDs corresponding to each text.

        Returns:
            IDs inserted by langchain-oceanbase.

        Raises:
            ValueError: If input list lengths do not match.
            RuntimeError: If langchain-oceanbase reports a partial batch.
        """
        text_list = list(texts)
        if not text_list:
            return []

        if metadatas is None:
            metadata_list = [{} for _ in text_list]
        else:
            metadata_list = [dict(metadata or {}) for metadata in metadatas]
        if len(metadata_list) != len(text_list):
            raise ValueError("Length of metadatas must match number of texts.")

        # Normalize metadata to this store's source: other backends filter on
        # metadata.source_id, and callers must not be able to spoof it here.
        for metadata in metadata_list:
            metadata[self.SOURCE_ID_FIELD] = self._source_id

        if ids is None:
            requested_ids = [str(uuid4()) for _ in text_list]
        else:
            requested_ids = [str(document_id) for document_id in ids]
        if len(requested_ids) != len(text_list):
            raise ValueError("Length of ids must match number of texts.")

        if "extras" in kwargs:
            raise ValueError("The OceanBase adapter reserves extras for source isolation.")
        extras = [{self.SOURCE_ID_FIELD: self._source_id} for _ in text_list]

        inserted_ids = self._docsearch.add_texts(
            text_list,
            metadata_list,
            *args,
            ids=requested_ids,
            extras=extras,
            **kwargs,
        )

        inserted_ids = [str(document_id) for document_id in inserted_ids]
        if len(inserted_ids) != len(text_list):
            raise RuntimeError(f"OceanBase inserted {len(inserted_ids)} of {len(text_list)} requested chunks.")
        return inserted_ids

    def add_chunk(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Add one chunk and return its ID."""
        return self.add_texts([text], [dict(metadata or {})], *args, **kwargs)[0]

    def get_chunks(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """Return all chunks belonging to this DocsGPT source."""
        del args, kwargs
        try:
            if not self._table_exists():
                return []

            result = self._client.get(
                table_name=self._table_name,
                where_clause=[self._source_condition()],
                output_column_name=[
                    self._docsearch.primary_field,
                    self._docsearch.text_field,
                    self._docsearch.metadata_field,
                ],
            )
            return [
                {
                    "doc_id": str(row[0]),
                    "text": str(row[1] or ""),
                    "metadata": self._decode_metadata(row[2]),
                }
                for row in self._materialize_rows(result)
            ]
        except Exception:
            logger.exception("Error getting OceanBase chunks")
            return []

    def delete_chunk(
        self,
        chunk_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """Delete one chunk only if it belongs to this source."""
        del args, kwargs
        try:
            matching_ids = self._get_matching_ids(
                ids=[str(chunk_id)],
                limit=1,
            )
            if not matching_ids:
                return False
            self._delete_ids(matching_ids)
            return True
        except Exception:
            logger.exception("Error deleting OceanBase chunk")
            return False

    def delete_chunks_by_source_path(self, path: str) -> int:
        """Delete this source's chunks whose ``metadata.source`` matches path."""
        try:
            if not self._table_exists():
                return 0
            path_condition = self._metadata_source_condition(path)
            return self._delete_where(self._source_condition(), path_condition)
        except Exception:
            logger.exception("Error deleting OceanBase chunks by source path")
            raise

    def delete_index(self, *args: Any, **kwargs: Any) -> None:
        """Delete every chunk belonging to this source, not the shared table."""
        del args, kwargs
        if not self._table_exists():
            return
        self._client.delete(
            table_name=self._table_name,
            where_clause=[self._source_condition()],
        )
