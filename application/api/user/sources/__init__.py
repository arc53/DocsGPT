"""Sources module."""

from .chunks import sources_chunks_ns
from .routes import sources_ns
from .upload import sources_upload_ns

__all__ = ["sources_ns", "sources_chunks_ns", "sources_upload_ns"]
