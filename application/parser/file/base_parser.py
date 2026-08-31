"""Base parser and config class."""

from abc import abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Union


class DocumentParseError(Exception):
    """A file could not be converted to text.

    Raised instead of returning the failure message as the document body: a
    parser that hands back its own traceback produces an attachment/source
    whose "content" is an error string, which then reaches the LLM as if it
    were the document. Callers should treat this as a failed upload and tell
    the user, rather than storing anything.

    Deterministic for a given input, so it is marked non-retryable on the
    Celery tasks that parse (alongside ``DataError`` and
    ``AttachmentRejectedError``) — a poison file fails once instead of
    re-failing identically on every retry.
    """


class BaseParser:
    """Base class for all parsers."""

    def __init__(self, parser_config: Optional[Dict] = None):
        """Init params."""
        self._parser_config = parser_config

    def init_parser(self) -> None:
        """Init parser and store it."""
        parser_config = self._init_parser()
        self._parser_config = parser_config

    @property
    def parser_config_set(self) -> bool:
        """Check if parser config is set."""
        return self._parser_config is not None

    @property
    def parser_config(self) -> Dict:
        """Check if parser config is set."""
        if self._parser_config is None:
            raise ValueError("Parser config not set.")
        return self._parser_config

    @abstractmethod
    def _init_parser(self) -> Dict:
        """Initialize the parser with the config."""

    @abstractmethod
    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse file."""

    def get_file_metadata(self, file: Path) -> Dict:
        """Return parser-specific metadata for the most recently parsed file."""
        _ = file
        return {}
