# oracle_db.py
from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings
from application.vectorstore.document_class import Document


class OracleDBVectorStore(BaseVectorStore):
    def __init__(
        self,
        embeddings_key: str = "embeddings",
        table: str = "documents",
        text_key: str = "text",
        embedding_key: str = "embedding",
        database: str = "docsgpt",
    ):
        self._table = table
        self._text_key = text_key
        self._embedding_key = embedding_key
        self._embeddings_key = embeddings_key
        self._oracle_uri = settings.ORACLE_URI
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)

        try:
            import oracledb
        except ImportError:
            raise ImportError(
                "Could not import oracledb python package. "
                "Please install it with `pip install oracledb`."
            )

        self._connection = oracledb.connect(self._oracle_uri)
        self._cursor = self._connection.cursor()

    def search(self, question, k=2, *args, **kwargs):
        query_vector = self._embedding.embed_query(question)

        query = f"""
        SELECT {self._text_key}, {self._embedding_key}, METADATA
        FROM {self._table}
        ORDER BY SDO_GEOM.SDO_DISTANCE(SDO_GEOMETRY({query_vector}),
        SDO_GEOMETRY({self._embedding_key})) ASC
        FETCH FIRST {k} ROWS ONLY
        """

        self._cursor.execute(query)
        results = []
        for row in self._cursor.fetchall():
            text, embedding, metadata = row
            results.append(Document(text, metadata))
        return results

    def _insert_texts(self, texts, metadatas):
        if not texts:
            return []

        embeddings = self._embedding.embed_documents(texts)
        to_insert = [
            (t, embedding, m) for t, m, embedding in zip(texts, metadatas, embeddings)
        ]

        query = f"""
        INSERT INTO {self._table} ({self._text_key}, {self._embedding_key}, METADATA)
        VALUES (:1, :2, :3)
        """

        self._cursor.executemany(query, to_insert)
        self._connection.commit()
        return [i[0] for i in self._cursor.fetchall()]

    def add_texts(
        self,
        texts,
        metadatas=None,
        ids=None,
        refresh_indices=True,
        create_index_if_not_exists=True,
        bulk_kwargs=None,
        **kwargs,
    ):
        batch_size = 100
        _metadatas = metadatas or ({} for _ in texts)
        texts_batch = []
        metadatas_batch = []
        result_ids = []

        for i, (text, metadata) in enumerate(zip(texts, _metadatas)):
            texts_batch.append(text)
            metadatas_batch.append(metadata)
            if (i + 1) % batch_size == 0:
                result_ids.extend(self._insert_texts(texts_batch, metadatas_batch))
                texts_batch = []
                metadatas_batch = []

        if texts_batch:
            result_ids.extend(self._insert_texts(texts_batch, metadatas_batch))
        return result_ids

    def delete_index(self, *args, **kwargs):
        query = f"DELETE FROM {self._table} WHERE 1=1"
        self._cursor.execute(query)
        self._connection.commit()
