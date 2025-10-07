import logging
from typing import List, Optional, Any, Dict
from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document


class PGVectorStore(BaseVectorStore):
    def __init__(
        self,
        source_id: str = "",
        embeddings_key: str = "embeddings",
        table_name: str = "documents",
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
        
        # Use provided connection string or fall back to settings
        self._connection_string = connection_string or getattr(settings, 'PGVECTOR_CONNECTION_STRING', None)
        
        if not self._connection_string:
            raise ValueError(
                "PostgreSQL connection string is required. "
                "Set PGVECTOR_CONNECTION_STRING in settings or pass connection_string parameter."
            )

        try:
            import psycopg2
            from psycopg2.extras import Json
            import pgvector.psycopg2
        except ImportError:
            raise ImportError(
                "Could not import required packages. "
                "Please install with `pip install psycopg2-binary pgvector`."
            )

        self._psycopg2 = psycopg2
        self._Json = Json
        self._pgvector = pgvector.psycopg2
        self._connection = None
        self._ensure_table_exists()

    def _get_connection(self):
        """Get or create database connection"""
        if self._connection is None or self._connection.closed:
            self._connection = self._psycopg2.connect(self._connection_string)
            # Register pgvector types
            self._pgvector.register_vector(self._connection)
        return self._connection

    def _ensure_table_exists(self):
        """Create table and enable pgvector extension if they don't exist"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Enable pgvector extension
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            
            # Get embedding dimension
            embedding_dim = getattr(self._embedding, 'dimension', 1536)  # Default to OpenAI dimension
            
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
            
            # Create index for vector similarity search
            index_query = f"""
            CREATE INDEX IF NOT EXISTS {self._table_name}_{self._vector_column}_idx 
            ON {self._table_name} USING ivfflat ({self._vector_column} vector_cosine_ops)
            WITH (lists = 100);
            """
            cursor.execute(index_query)
            
            # Create index for source_id filtering
            source_index_query = f"""
            CREATE INDEX IF NOT EXISTS {self._table_name}_source_id_idx 
            ON {self._table_name} (source_id);
            """
            cursor.execute(source_index_query)
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(f"Error creating table: {e}")
            raise
        finally:
            cursor.close()

    def search(self, question: str, k: int = 2, *args, **kwargs) -> List[Document]:
        """Search for similar documents using vector similarity"""
        query_vector = self._embedding.embed_query(question)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Use cosine distance for similarity search with proper vector formatting
            search_query = f"""
            SELECT {self._text_column}, {self._metadata_column}, 
                   ({self._vector_column} <=> %s::vector) as distance
            FROM {self._table_name}
            WHERE source_id = %s
            ORDER BY {self._vector_column} <=> %s::vector
            LIMIT %s;
            """
            
            cursor.execute(search_query, (query_vector, self._source_id, query_vector, k))
            results = cursor.fetchall()
            
            
            documents = []
            for text, metadata, distance in results:
                metadata = metadata or {}
                documents.append(Document(page_content=text, metadata=metadata))
            
            return documents
            
        except Exception as e:
            logging.error(f"Error searching documents: {e}", exc_info=True)
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
                    (text, embedding, self._Json(metadata), self._source_id)
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
        
        # Create a copy to avoid modifying the original metadata
        final_metadata = metadata.copy()
        
        # Ensure the source_id is in the metadata so the chunk can be found by filters
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
                (text, embeddings[0], self._Json(final_metadata), self._source_id)
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

    def __del__(self):
        """Close database connection when object is destroyed"""
        if hasattr(self, '_connection') and self._connection and not self._connection.closed:
            self._connection.close()