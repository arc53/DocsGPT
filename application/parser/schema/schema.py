"""Base schema for data structures."""
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dataclasses_json import DataClassJsonMixin


@dataclass
class BaseDocument(DataClassJsonMixin):
    """Base document.

    Generic abstract interfaces that captures both index structs
    as well as documents.

    """

    # consolidated fields from document/indexstruct into base class
    page_content: Optional[str] = None  # main text content (formerly 'text')
    doc_id: Optional[str] = None
    embedding: Optional[List[float]] = None

    # additional metadata
    metadata: Optional[Dict[str, Any]] = None  # flexible metadata storage (formerly 'extra_info')

    @classmethod
    @abstractmethod
    def get_type(cls) -> str:
        """Get Document type."""

    def get_page_content(self) -> str:
        """get page content."""
        if self.page_content is None:
            raise ValueError("page_content field not set.")
        return self.page_content

    # backward compatibility method
    def get_text(self) -> str:
        """get text (legacy method for backward compatibility)."""
        return self.get_page_content()

    def get_doc_id(self) -> str:
        """get doc_id."""
        if self.doc_id is None:
            raise ValueError("doc_id not set.")
        return self.doc_id

    @property
    def is_doc_id_none(self) -> bool:
        """Check if doc_id is None."""
        return self.doc_id is None

    def get_embedding(self) -> List[float]:
        """Get embedding.

        Errors if embedding is None.

        """
        if self.embedding is None:
            raise ValueError("embedding not set.")
        return self.embedding

    @property
    def metadata_str(self) -> Optional[str]:
        """metadata string representation."""
        if self.metadata is None:
            return None

        return "\n".join([f"{k}: {str(v)}" for k, v in self.metadata.items()])

    # backward compatibility property
    @property
    def extra_info_str(self) -> Optional[str]:
        """extra info string (legacy property for backward compatibility)."""
        return self.metadata_str

    @property
    def extra_info(self) -> Optional[Dict[str, Any]]:
        """extra info (legacy property for backward compatibility)."""
        return self.metadata

    @extra_info.setter
    def extra_info(self, value: Optional[Dict[str, Any]]) -> None:
        """set extra info (legacy setter for backward compatibility)."""
        self.metadata = value
