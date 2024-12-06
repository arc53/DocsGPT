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
        if self.text is None:
            raise ValueError("text field not set.")

    @classmethod
    def get_type(cls) -> str:
        """Get Document type."""
        return "Document"

    def to_langchain_format(self) -> LCDocument:
        """Convert struct to LangChain document format."""
        metadata = self.extra_info or {}

        if self.images is not None:
            metadata["images"] = self.images
        if self.tables is not None:
            metadata["tables"] = self.tables

        return LCDocument(page_content=self.text, metadata=metadata)

    @classmethod
    def from_langchain_format(cls, doc: LCDocument) -> "Document":
        """Convert struct from LangChain document format."""
        images = doc.metadata.pop("images", None)
        tables = doc.metadata.pop("tables", None)

        return cls(
            text=doc.page_content, extra_info=doc.metadata, images=images, tables=tables
        )
