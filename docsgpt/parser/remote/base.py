"""Base reader class."""
from abc import abstractmethod
from typing import Any, List

from docsgpt.parser.schema.base import Document
from docsgpt.vectorstore.document_class import Document as VectorDocument


class BaseRemote:
    """Utilities for loading data from a directory."""

    @abstractmethod
    def load_data(self, *args: Any, **load_kwargs: Any) -> List[Document]:
        """Load data from the input directory."""

    def load_vector_documents(self, **load_kwargs: Any) -> List[VectorDocument]:
        """Load data in the vector-store document format."""
        docs = self.load_data(**load_kwargs)
        return [d.to_vector_format() for d in docs]
