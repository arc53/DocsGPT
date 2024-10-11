from typing import List, Optional
import importlib
from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings

class LanceDBVectorStore(BaseVectorStore):
    """Class for LanceDB Vector Store integration."""

    def __init__(self, path: str = settings.LANCEDB_PATH,
                 table_name_prefix: str = settings.LANCEDB_TABLE_NAME,
                 source_id: str = None,
                 embeddings_key: str = "embeddings"):
        """Initialize the LanceDB vector store."""
        super().__init__()
        self.path = path
        self.table_name = f"{table_name_prefix}_{source_id}" if source_id else table_name_prefix
        self.embeddings_key = embeddings_key
        self._lance_db = None
        self.docsearch = None
        self._pa = None  # PyArrow (pa) will be lazy loaded

    @property
    def pa(self):
        """Lazy load pyarrow module."""
        if self._pa is None:
            self._pa = importlib.import_module("pyarrow")
        return self._pa

    @property
    def lancedb(self):
        """Lazy load lancedb module."""
        if not hasattr(self, "_lancedb_module"):
            self._lancedb_module = importlib.import_module("lancedb")
        return self._lancedb_module

    @property
    def lance_db(self):
        """Lazy load the LanceDB connection."""
        if self._lance_db is None:
            self._lance_db = self.lancedb.connect(self.path)
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
            schema = self.pa.schema([
                self.pa.field("vector", self.pa.list_(self.pa.float32(), list_size=embeddings.dimension)),
                self.pa.field("text", self.pa.string()),
                self.pa.field("metadata", self.pa.struct([
                    self.pa.field("key", self.pa.string()),
                    self.pa.field("value", self.pa.string())
                ]))
            ])
            self.docsearch = self.lance_db.create_table(self.table_name, schema=schema)

    def add_texts(self, texts: List[str], metadatas: Optional[List[dict]] = None, source_id: str = None):
        """Add texts with metadata and their embeddings to the LanceDB table."""
        embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, self.embeddings_key).embed_documents(texts)
        vectors = []
        for embedding, text, metadata in zip(embeddings, texts, metadatas or [{}] * len(texts)):
            if source_id:
                metadata["source_id"] = source_id
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

        # Ensure source_id exists in the filter condition
        if 'source_id' not in filter_condition:
            raise ValueError("filter_condition must contain 'source_id'")

        source_id = filter_condition["source_id"]

        # Use LanceDB's native filtering if supported, otherwise filter manually
        filtered_data = self.docsearch.filter(lambda x: x.metadata and x.metadata.get("source_id") == source_id).to_list()

        return filtered_data