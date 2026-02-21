import logging
from typing import List, Optional, Any, Dict
from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document


class OracleVectorStore(BaseVectorStore):
    """
    Oracle Vector Store implementation using Oracle 26ai Autonomous Database.
    Uses LangChain's Oracle VectorStore integration for all operations.
    Follows the same architecture as PGVectorStore for consistency.
    """

    def __init__(
        self,
        source_id: str = "",
        embeddings_key: str = "embeddings",
        table_name: str = "docsgpt_vectors",
        decoded_token: Optional[str] = None,
        connection_string: str = None,
    ):
        """
        Initialize Oracle Vector Store.

        Args:
            source_id: Unique identifier for the document source (for multi-tenant filtering)
            embeddings_key: API key for embeddings (if using OpenAI embeddings)
            table_name: Name of the Oracle table to store vectors
            decoded_token: Optional JWT token (not used but kept for interface consistency)
            connection_string: Oracle connection string (DSN format or connection string)
        """
        super().__init__()
        
        # Store the source_id for use in filtering operations
        self._source_id = str(source_id).replace("application/indexes/", "").rstrip("/")
        self._embeddings_key = embeddings_key
        self._table_name = table_name
        
        # Initialize embeddings using the base class method
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        
        # Use provided connection string or fall back to settings
        self._connection_string = connection_string or getattr(settings, 'ORACLE_CONNECTION_STRING', None)
        
        if not self._connection_string:
            raise ValueError(
                "Oracle connection string is required. "
                "Set ORACLE_CONNECTION_STRING in settings or pass connection_string parameter. "
                "Format: user/password@host:port/service_name or similar DSN format."
            )

        # Import LangChain Oracle VectorStore
        try:
            from langchain_community.vectorstores import OracleVS
            from langchain_community.vectorstores.oraclevs import OracleVSConfig
            from langchain_community.vectorstores.utils import DistanceStrategy
        except ImportError:
            raise ImportError(
                "Could not import Oracle VectorStore from LangChain. "
                "Please install with: pip install langchain-community oracledb"
            )

        self._OracleVS = OracleVS
        self._OracleVSConfig = OracleVSConfig
        self._DistanceStrategy = DistanceStrategy
        self._vectorstore = None
        self._initialize_vectorstore()

    def _initialize_vectorstore(self):
        """
        Initialize the LangChain Oracle VectorStore.
        LangChain will handle table creation, vector column creation, and indexing.
        """
        try:
            # Create Oracle VS configuration
            # LangChain Oracle VectorStore will automatically:
            # - Create the table if it doesn't exist
            # - Add VECTOR column for embeddings
            # - Add metadata columns
            # - Create appropriate indexes
            config = self._OracleVSConfig(
                table_name=self._table_name,
                distance_strategy=self._DistanceStrategy.COSINE,
            )
            
            # Initialize the vectorstore
            # LangChain will handle all schema creation automatically
            self._vectorstore = self._OracleVS(
                embedding_function=self._embedding,
                config=config,
                client=None,  # Will create connection using connection_string
                connection_string=self._connection_string,
            )
            
            logging.info(f"Oracle VectorStore initialized successfully with table: {self._table_name}")
            
        except Exception as e:
            logging.error(f"Error initializing Oracle VectorStore: {e}", exc_info=True)
            raise

    def search(self, question: str, k: int = 2, *args, **kwargs) -> List[Document]:
        """
        Search for similar documents using vector similarity.
        
        Args:
            question: The query text to search for
            k: Number of results to return
            
        Returns:
            List[Document]: List of similar documents filtered by source_id
        """
        try:
            # Generate query embedding
            # LangChain's similarity_search will handle the vector search
            
            # Filter by source_id in metadata
            filter_dict = {"source_id": self._source_id}
            
            # Perform similarity search using LangChain
            results = self._vectorstore.similarity_search(
                query=question,
                k=k,
                filter=filter_dict,
                **kwargs
            )
            
            # Convert LangChain documents to our Document class
            documents = []
            for doc in results:
                # Ensure metadata exists
                metadata = doc.metadata or {}
                documents.append(Document(page_content=doc.page_content, metadata=metadata))
            
            return documents
            
        except Exception as e:
            logging.error(f"Error searching documents in Oracle: {e}", exc_info=True)
            return []

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        *args,
        **kwargs,
    ) -> List[str]:
        """
        Add texts with their embeddings to the Oracle vector store.
        
        Args:
            texts: List of text strings to add
            metadatas: Optional list of metadata dictionaries for each text
            
        Returns:
            List[str]: List of inserted document IDs
        """
        if not texts:
            return []

        try:
            # Prepare metadatas with source_id
            metadatas = metadatas or [{}] * len(texts)
            
            # Ensure each metadata contains source_id for filtering
            for metadata in metadatas:
                metadata["source_id"] = self._source_id
            
            # Use LangChain's add_texts method
            # This will:
            # - Generate embeddings
            # - Insert into Oracle table
            # - Return document IDs
            ids = self._vectorstore.add_texts(
                texts=texts,
                metadatas=metadatas,
                **kwargs
            )
            
            # Convert IDs to strings
            return [str(id) for id in ids] if ids else []
            
        except Exception as e:
            logging.error(f"Error adding texts to Oracle: {e}", exc_info=True)
            raise

    def delete_index(self, *args, **kwargs):
        """
        Delete all documents for this source_id.
        Does NOT drop the entire table - only deletes documents belonging to this source.
        Safe for multi-tenant usage.
        """
        try:
            # Delete only documents with this source_id
            # LangChain Oracle VectorStore should support deletion by filter
            # We need to get all document IDs for this source_id first, then delete them
            
            # Since LangChain's delete method typically requires IDs,
            # we need to retrieve all IDs for this source_id first
            chunks = self.get_chunks()
            
            if chunks:
                ids_to_delete = [chunk["doc_id"] for chunk in chunks]
                
                if hasattr(self._vectorstore, 'delete'):
                    self._vectorstore.delete(ids=ids_to_delete)
                else:
                    # Fallback: delete one by one
                    for doc_id in ids_to_delete:
                        self.delete_chunk(doc_id)
                        
            logging.info(f"Deleted {len(chunks)} documents for source_id: {self._source_id}")
            
        except Exception as e:
            logging.error(f"Error deleting index in Oracle: {e}", exc_info=True)
            raise

    def save_local(self, *args, **kwargs):
        """
        No-op for Oracle - data is already persisted in the database.
        Kept for interface consistency with other vector stores.
        """
        pass

    def get_chunks(self) -> List[Dict[str, Any]]:
        """
        Get all chunks for this source_id.
        
        Returns:
            List[Dict]: List of chunks with doc_id, text, and metadata
        """
        try:
            # Use similarity_search with a dummy query and high k value
            # Filter by source_id
            # This is a workaround since LangChain doesn't have a "get all" method
            
            # Alternative: use the underlying connection to query directly
            # But we want to avoid raw SQL as per requirements
            
            # We'll use a broad search with filtering
            filter_dict = {"source_id": self._source_id}
            
            # Retrieve with a high k value (this may need adjustment based on your use case)
            # Note: This is a limitation of using LangChain abstraction
            results = self._vectorstore.similarity_search(
                query="",  # Empty query
                k=10000,  # Large number to get all documents
                filter=filter_dict,
            )
            
            chunks = []
            for idx, doc in enumerate(results):
                # LangChain documents may not have explicit IDs in metadata
                # Try to extract ID from metadata or use index
                doc_id = doc.metadata.get("id", str(idx))
                
                chunks.append({
                    "doc_id": str(doc_id),
                    "text": doc.page_content,
                    "metadata": doc.metadata or {}
                })
            
            return chunks
            
        except Exception as e:
            logging.error(f"Error getting chunks from Oracle: {e}", exc_info=True)
            return []

    def add_chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Add a single chunk to the Oracle vector store.
        
        Args:
            text: The text content to add
            metadata: Optional metadata dictionary
            
        Returns:
            str: ID of the inserted chunk
        """
        try:
            metadata = metadata or {}
            
            # Ensure metadata contains source_id
            final_metadata = metadata.copy()
            final_metadata["source_id"] = self._source_id
            
            # Use add_texts with single text
            ids = self.add_texts(
                texts=[text],
                metadatas=[final_metadata]
            )
            
            if ids and len(ids) > 0:
                return ids[0]
            else:
                raise ValueError("Failed to insert chunk - no ID returned")
            
        except Exception as e:
            logging.error(f"Error adding chunk to Oracle: {e}", exc_info=True)
            raise

    def delete_chunk(self, chunk_id: str) -> bool:
        """
        Delete a specific chunk by its ID.
        Only deletes if the chunk belongs to this source_id.
        
        Args:
            chunk_id: ID of the chunk to delete
            
        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            # First verify the chunk belongs to this source_id
            chunks = self.get_chunks()
            chunk_ids = [chunk["doc_id"] for chunk in chunks]
            
            if chunk_id not in chunk_ids:
                logging.warning(f"Chunk {chunk_id} not found or does not belong to source_id {self._source_id}")
                return False
            
            # Delete using LangChain's delete method
            if hasattr(self._vectorstore, 'delete'):
                self._vectorstore.delete(ids=[chunk_id])
                return True
            else:
                logging.error("Oracle VectorStore does not support delete operation")
                return False
            
        except Exception as e:
            logging.error(f"Error deleting chunk from Oracle: {e}", exc_info=True)
            return False

    def __del__(self):
        """
        Cleanup when object is destroyed.
        LangChain will handle connection cleanup internally.
        """
        # LangChain handles connection cleanup
        pass