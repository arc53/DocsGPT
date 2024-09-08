from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings
import lancedb
import pyarrow as pa
from typing import List, Optional

class LanceDBVectorStore(BaseVectorStore):
    def __init__(self, path: str = settings.LANCEDB_PATH, table_name: str = settings.LANCEDB_TABLE_NAME, embeddings_key: str = "embeddings"):
        super().__init__()
        self._path = path
        self._table_name = table_name
        self.embeddings_key = embeddings_key
        self._db = None  # Lazy load the DB connection
        self._table = None  # Table will also be lazily loaded when required

    @property
    def db(self):
        """Lazy load the LanceDB connection."""
        if self._db is None:
            # You might want to add error handling here for failed connections
            self._db = lancedb.connect(self._path)
        return self._db

    @property
    def table(self):
        """Lazy load the LanceDB table."""
        if self._table is None:
            if self._table_name not in self.db.table_names():
                self._table = None  # Table will be created when data is inserted
            else:
                self._table = self.db.open_table(self._table_name)
        return self._table

    def assert_embedding_dimensions(self, embeddings):
        """Ensure that embedding dimensions match the table index dimensions."""
        word_embedding_dimension = embeddings.dimension
        if self.table:
            table_index_dimension = len(self.table.schema["vector"].type.value_type)
            if word_embedding_dimension != table_index_dimension:
                raise ValueError(
                    f"Embedding dimension mismatch: embeddings.dimension ({word_embedding_dimension}) "
                    f"!= table index dimension ({table_index_dimension})"
                )

    def add_texts(self, texts: List[str], metadatas: Optional[List[dict]] = None, *args, **kwargs):
        """Add texts with metadata and their embeddings to the LanceDB table."""
        embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, self.embeddings_key).embed_documents(texts)
        vectors = [{"vector": embedding, "text": text, **metadata} for embedding, text, metadata in zip(embeddings, texts, metadatas or [{}] * len(texts))]

        if self.table is None:
            # This handles first-time table creation if the table doesn't exist
            schema = pa.schema([
                pa.field("vector", pa.list_(pa.float32(), list_size=len(vectors[0]["vector"]))),
                pa.field("text", pa.string()),
                pa.field("metadata", pa.map_(pa.string(), pa.string())),
            ])
            self._table = self.db.create_table(self._table_name, schema=schema)

        # Add data to the table
        self._table.add(vectors)

    def search(self, query: str, k: int = 2, *args, **kwargs):
        """Search LanceDB for the top k most similar vectors."""
        query_embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, self.embeddings_key).embed_query(query)
        results = self.table.search(query_embedding).limit(k).to_list()

        return [(result["_distance"], result["text"], result["metadata"]) for result in results]

    def delete_index(self, *args, **kwargs):
        """Delete the entire LanceDB index (table)."""
        if self.table:
            # Make sure to handle the case where the table is not found or there's an issue
            self.db.drop_table(self._table_name)

    def filter_documents(self, filter_condition: dict) -> List[dict]:
        """Filter documents based on certain conditions."""
        if not self.table:
            raise ValueError("Table does not exist.")

        # Apply the filter condition to the table and return filtered results
        filtered_data = self.table.filter(filter_condition).to_list()
        return filtered_data
