import logging
import oracledb
import json
from typing import List, Optional

# LangChain Imports for Oracle AI Vector Search
from langchain_community.vectorstores import oraclevs
from langchain_community.vectorstores.oraclevs import OracleVS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.documents import Document as LangchainDocument

# DocsGPT Application Imports
from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document as AppDocument

# Set up logging
logger = logging.getLogger(__name__)


class OracleVectorStore(BaseVectorStore):
    """
    OracleVectorStore provides an interface to Oracle AI Vector Search for DocsGPT.

    It handles database connections, creation of vector tables and indexes,
    as well as adding, deleting, and searching for documents.
    """

    def __init__(
        self,
        source_id: str,
        table_name: str = "docsgpt_vectors",
        embeddings_key: str = "embeddings",
    ):
        """
        Initializes the OracleVectorStore.

        Args:
            source_id (str): The identifier for the document source.
            table_name (str): The name of the database table to store vectors.
            embeddings_key (str): The key for embeddings in the application's settings.
        """
        self._source_id = source_id
        final_table_name = table_name if table_name is not None else "docsgpt_vectors"
        self._table_name = final_table_name.upper()  # Oracle table names are typically uppercase        self._embeddings_key = embeddings_key
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        self.vector_store: Optional[OracleVS] = None
        self.connection = None

        self._connect()

        # If the table already exists, create an instance of the vector store
        if self._table_exists():
            self._get_vector_store_instance()

    def _connect(self):
        """Establishes a connection to the Oracle database."""
        try:
            # Add connection validation
            if not all([settings.ORACLE_USER, settings.ORACLE_PASSWORD, settings.ORACLE_DSN]):
                raise ValueError("Oracle connection parameters are not properly configured")
            
            # Check if connecting as SYS user (requires SYSDBA mode)
            if settings.ORACLE_USER.lower() == 'sys':
                self.connection = oracledb.connect(
                    user=settings.ORACLE_USER,
                    password=settings.ORACLE_PASSWORD,
                    dsn=settings.ORACLE_DSN,
                    mode=oracledb.SYSDBA  # Required for SYS user
                )
                logger.info("Successfully connected to Oracle Database as SYSDBA.")
            else:
                self.connection = oracledb.connect(
                    user=settings.ORACLE_USER,
                    password=settings.ORACLE_PASSWORD,
                    dsn=settings.ORACLE_DSN
                )
                logger.info("Successfully connected to Oracle Database.")
            # Test the connection
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM DUAL")
                cursor.fetchone()
            
        except ValueError as e:
            logger.error(f"Configuration error: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to connect to Oracle Database: {e}")
            logger.error(f"Connection details: User={settings.ORACLE_USER}, DSN={settings.ORACLE_DSN}")
            raise

    def _table_exists(self) -> bool:
        """Checks if the vector store table exists in the database."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM user_tables WHERE table_name = :1",
                [self._table_name],
            )
            return cursor.fetchone() is not None

    def _get_vector_store_instance(self):
        """Initializes the OracleVS object for an existing table."""
        self.vector_store = OracleVS(
            client=self.connection,
            embedding_function=self._embedding,
            table_name=self._table_name,
            distance_strategy=DistanceStrategy.COSINE,  # Defaulting to COSINE similarity
        )
        logger.info(f"Initialized OracleVS for existing table: {self._table_name}")

    def _create_index_if_not_exists(self):
        """Creates an HNSW index on the vector table if it doesn't already exist."""
        index_name = f"{self._table_name}_HNSW_IDX"
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT index_name FROM user_indexes WHERE index_name = :1",
                [index_name],
            )
            if cursor.fetchone():
                logger.info(f"Index '{index_name}' already exists.")
                return

        logger.info(f"Creating HNSW index '{index_name}' on table '{self._table_name}'...")
        try:
            oraclevs.create_index(
                self.connection,
                self.vector_store,
                params={"idx_name": index_name, "idx_type": "HNSW"},
            )
            logger.info(f"Successfully created index '{index_name}'.")
        except Exception as e:
            logger.error(f"Failed to create index '{index_name}': {e}", exc_info=True)

    def search(self, question: str, k: int = 4, *args, **kwargs) -> List[AppDocument]:
        """Performs a similarity search for a given question."""
        if not self.vector_store:
            logger.warning("Vector store is not initialized. No search can be performed.")
            return []

        # Filter results to only include documents from the current source_id
        filter_criteria = {"source_id": self._source_id}

        try:
            results: List[LangchainDocument] = self.vector_store.similarity_search(
                query=question, k=k, filter=filter_criteria
            )
            # Convert LangChain's Document format to DocsGPT's format
            app_results = [
                AppDocument(page_content=doc.page_content, metadata=doc.metadata)
                for doc in results
            ]
            return app_results
        except Exception as e:
            logger.error(f"Error during similarity search: {e}", exc_info=True)
            return []

    def add_texts(self, texts: List[str], metadatas: Optional[List[dict]] = None, **kwargs):
        """Adds texts and their metadata to the vector store."""
        if not texts:
            return

        _metadatas = metadatas or [{} for _ in texts]
        for meta in _metadatas:
            meta["source_id"] = self._source_id

        documents = [
            LangchainDocument(page_content=t, metadata=m) for t, m in zip(texts, _metadatas)
        ]

        if not self.vector_store:
            # If the table doesn't exist, create it using from_documents
            logger.info(f"Table '{self._table_name}' not found. Creating and ingesting documents.")
            self.vector_store = OracleVS.from_documents(
                documents=documents,
                embedding=self._embedding,
                client=self.connection,
                table_name=self._table_name,
                distance_strategy=DistanceStrategy.COSINE,
            )
            self._create_index_if_not_exists()
        else:
            # If the table exists, add new texts to it
            logger.info(f"Adding {len(texts)} documents to existing table '{self._table_name}'.")
            self.vector_store.add_texts(texts=texts, metadatas=_metadatas)
    
    def delete_index(self, *args, **kwargs):
        """Deletes all documents associated with the source_id from the table."""
        logger.warning(
            f"Deleting all documents for source_id '{self._source_id}' from table '{self._table_name}'."
        )
        try:
            with self.connection.cursor() as cursor:
                # The metadata column is a CLOB storing a JSON string.
                # Use JSON_VALUE to query the 'source_id' key within the JSON.
                sql = f"""
                DELETE FROM {self._table_name}
                WHERE JSON_VALUE(metadata, '$.source_id') = :source_id
                """
                cursor.execute(sql, source_id=self._source_id)
                self.connection.commit()
                logger.info(
                    f"Successfully deleted {cursor.rowcount} documents for source_id '{self._source_id}'."
                )
        except Exception as e:
            logger.error(f"Error deleting documents for source_id '{self._source_id}': {e}")
            self.connection.rollback()

    def get_chunks(self) -> List[dict]:
        """Retrieves all document chunks for the current source_id."""
        chunks = []
        if not self._table_exists():
            return chunks
            
        try:
            with self.connection.cursor() as cursor:
                sql = f"SELECT c_id, text, metadata FROM {self._table_name} WHERE JSON_VALUE(metadata, '$.source_id') = :source_id"
                cursor.execute(sql, source_id=self._source_id)
                for row in cursor:
                    doc_id, text, metadata_clob = row
                    metadata = json.loads(metadata_clob.read())
                    clean_metadata = {
                        k: v for k, v in metadata.items() if k not in ["source_id"]
                    }
                    chunks.append({"doc_id": doc_id, "text": text, "metadata": clean_metadata})
            return chunks
        except Exception as e:
            logger.error(f"Error getting chunks for source_id '{self._source_id}': {e}", exc_info=True)
            return []

    def add_chunk(self, text: str, metadata: Optional[dict] = None) -> str:
        """Adds a single document chunk to the vector store."""
        _metadata = metadata or {}
        self.add_texts([text], [_metadata])
        # Note: Getting the specific ID back from LangChain's bulk insert isn't straightforward.
        # This implementation adds the chunk but doesn't return its database ID.
        return "Chunk added successfully."

    def delete_chunk(self, chunk_id: str) -> bool:
        """Deletes a single document chunk by its database ID."""
        try:
            with self.connection.cursor() as cursor:
                # 'c_id' is the default primary key column created by OracleVS.
                sql = f"DELETE FROM {self._table_name} WHERE c_id = :id"
                cursor.execute(sql, id=chunk_id)
                self.connection.commit()
                deleted_count = cursor.rowcount
                logger.info(f"Deleted chunk with id '{chunk_id}'. Rows affected: {deleted_count}.")
                return deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting chunk '{chunk_id}': {e}", exc_info=True)
            self.connection.rollback()
            return False

    def __del__(self):
        """Ensures the database connection is closed when the object is destroyed."""
        if self.connection:
            self.connection.close()
            logger.info("Oracle database connection closed.")