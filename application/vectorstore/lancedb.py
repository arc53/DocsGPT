


from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings
import lancedb
import pyarrow as pa

class LanceDBVectorStore(BaseVectorStore):
    def __init__(self, path: str = settings.LANCEDB_PATH, table_name: str = settings.LANCEDB_TABLE_NAME, embeddings_key: str = "embeddings"):
        super().__init__()
        self.path = path
        self.table_name = table_name
        self.embeddings_key = embeddings_key

        # Initialize LanceDB connection
        self.db = lancedb.connect(self.path)

        # Check if the table exists, otherwise create it
        if self.table_name not in self.db.table_names():
            self.table = None  # Table will be created with the first insertion
        else:
            self.table = self.db.open_table(self.table_name)

    def assert_embedding_dimensions(self, embeddings):
        # Similar to the FAISS implementation
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
        vectors = [{"vector": embedding, "text": text, **metadata} for embedding, text, metadata in zip(embeddings, texts, metadatas or [{}]*len(texts))]

        if self.table is None:
            schema = pa.schema([
                pa.field("vector", pa.list_(pa.float32(), list_size=len(vectors[0]["vector"]))),
                pa.field("text", pa.string()),
                pa.field("metadata", pa.map_(pa.string(), pa.string())),
            ])
            self.table = self.db.create_table(self.table_name, schema=schema)

        # Add data to the table
        self.table.add(vectors)

    def search(self, query: str, k: int = 2, *args, **kwargs):
        """Search LanceDB for the top k most similar vectors."""
        query_embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, self.embeddings_key).embed_query(query)
        results = self.table.search(query_embedding).limit(k).to_list()

        return [(result["_distance"], result["text"], result["metadata"]) for result in results]

    def delete_index(self, *args, **kwargs):
        """Delete the entire LanceDB index (table)."""
        self.db.drop_table(self.table_name)
