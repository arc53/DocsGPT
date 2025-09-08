"""Base schema for readers."""
from dataclasses import dataclass

from langchain.docstore.document import Document as LCDocument
from application.parser.schema.schema import BaseDocument


@dataclass
class Document(BaseDocument):
    """Generic interface for a data document.

    This document connects to data sources.

    """

    def __post_init__(self) -> None:
        """Post init."""
        if self.page_content is None:
            raise ValueError("page_content field not set.")

    @classmethod
    def get_type(cls) -> str:
        """Get document type."""
        return "Document"

    def to_langchain_format(self) -> LCDocument:
        """Convert struct to LangChain document format."""
        metadata = self.metadata or {}
        return LCDocument(page_content=self.page_content, metadata=metadata)

    @classmethod
    def from_langchain_format(cls, doc: LCDocument) -> "Document":
        """Convert struct from LangChain document format."""
        return cls(page_content=doc.page_content, metadata=doc.metadata)
