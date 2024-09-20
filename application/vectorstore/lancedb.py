from typing import List, Optional
import pyarrow as pa
import lancedb
from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings

class LanceDBVectorStore(BaseVectorStore):
    """Class for LanceDB Vector Store integration."""

    def __init__(self, path: str = settings.LANCEDB_PATH,
                 table_name: str = settings.LANCEDB_TABLE_NAME,
                 embeddings_key: str = "embeddings"):
        """Initialize the LanceDB vector store."""
        super().__init__()
        self.path = path
        self.table_name = table_name
        self.embeddings_key = embeddings_key
        self._lance_db = None  # Updated to snake_case
        self.docsearch = None

    @property
    def lance_db(self):
        """Lazy load the LanceDB connection."""
        if self._lance_db is None:
            self._lance_db = lancedb.connect(self.path)
        return self._lance_db

    @property
    def table(self):
        """Lazy load the LanceDB table."""
        if self.docsearch is None:
            if self.table_name in self.lance_db.table_names():
                self.docsearch = self.lance_db.open_table(self.table_name)
            else:
                self.docsearch = None
        return self.docsearch

    def ensure_table_exists(self):
        """Ensure the table exists before performing operations."""
        if self.table is None:
            embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, self.embeddings_key)
            schema = pa.schema([
                pa.field("vector", pa.list_(pa.float32(), list_size=embeddings.dimension)),
                pa.field("text", pa.string()),
                pa.field("metadata", pa.struct([
                    pa.field("key", pa.string()),
                    pa.field("value", pa.string())
                ]))
            ])
            self.docsearch = self.lance_db.create_table(self.table_name, schema=schema)

    def add_texts(self, texts: List[str], metadatas: Optional[List[dict]] = None):
        """Add texts with metadata and their embeddings to the LanceDB table."""
        embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, self.embeddings_key).embed_documents(texts)
        vectors = []
        for embedding, text, metadata in zip(embeddings, texts, metadatas or [{}] * len(texts)):
            metadata_struct = [{"key": k, "value": str(v)} for k, v in metadata.items()]
            vectors.append({
                "vector": embedding,
                "text": text,
                "metadata": metadata_struct
            })
        self.ensure_table_exists()
        self.docsearch.add(vectors)

    def search(self, query: str, k: int = 2, *args, **kwargs):
        """Search LanceDB for the top k most similar vectors."""
        self.ensure_table_exists()
        query_embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, self.embeddings_key).embed_query(query)
        results = self.docsearch.search(query_embedding).limit(k).to_list()
        return [(result["_distance"], result["text"], result["metadata"]) for result in results]

    def delete_index(self):
        """Delete the entire LanceDB index (table)."""
        if self.table:
            self.lance_db.drop_table(self.table_name)

    def assert_embedding_dimensions(self, embeddings):
        """Ensure that embedding dimensions match the table index dimensions."""
        word_embedding_dimension = embeddings.dimension
        if self.table:
            table_index_dimension = len(self.docsearch.schema["vector"].type.value_type)
            if word_embedding_dimension != table_index_dimension:
                raise ValueError(
                    f"Embedding dimension mismatch: embeddings.dimension ({word_embedding_dimension}) "
                    f"!= table index dimension ({table_index_dimension})"
                )

    def filter_documents(self, filter_condition: dict) -> List[dict]:
        """Filter documents based on certain conditions."""
        self.ensure_table_exists()
        filtered_data = self.docsearch.filter(filter_condition).to_list()
        return filtered_data