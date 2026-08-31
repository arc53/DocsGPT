"""Base schema for readers."""
from dataclasses import dataclass

from application.parser.schema.schema import BaseDocument
from application.vectorstore.document_class import Document as VectorDocument


@dataclass
class Document(BaseDocument):
    """Generic interface for a data document.

    This document connects to data sources.

    """

    def __post_init__(self) -> None:
        """Post init."""
        if self.text is None:
            raise ValueError("text field not set.")

    @classmethod
    def get_type(cls) -> str:
        """Get Document type."""
        return "Document"

    def to_vector_format(self) -> VectorDocument:
        """Convert struct to the page_content/metadata shape vector stores take."""
        metadata = self.extra_info or {}
        return VectorDocument(page_content=self.text, metadata=metadata)

    @classmethod
    def from_vector_format(cls, doc: VectorDocument) -> "Document":
        """Convert struct from the vector-store document shape."""
        return cls(text=doc.page_content, extra_info=doc.metadata)
