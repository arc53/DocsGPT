"""Base parser and config class."""

import importlib.util
import logging
import sys
from abc import abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Union

logger = logging.getLogger(__name__)


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


def module_available(name: str) -> bool:
    """Whether top-level module ``name`` can be imported, without importing it.

    Cheap enough to call while building a parser map. Honors ``sys.modules``
    first so tests that stub a module in (or block one out with ``None``)
    are seen the same way the import system would see them; a stub with no
    ``__spec__`` counts as present rather than raising.

    Args:
        name: Top-level module name, e.g. ``"docling"``.

    Returns:
        True when an import of ``name`` would succeed.
    """
    if name in sys.modules:
        return sys.modules[name] is not None
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def delegate_parse(
    parser: "BaseParser", file: Path, errors: str
) -> Union[str, List[str]]:
    """Run a fallback parser, normalizing its failures to ``DocumentParseError``.

    Used wherever one parser hands a file to another (docling to the plain
    tabular parsers for oversized sheets, anydoc to docling/legacy parsers
    for files it cannot convert). Wrapping matters twice over: the Celery
    tasks that own these paths list ``DocumentParseError`` in
    ``dont_autoretry_for``, so a deterministic content error fails once
    instead of retrying four times; and ``SimpleDirectoryReader.load_data``
    catches only ``DocumentParseError``, so one poison file is skipped into
    ``failed_files`` instead of aborting an entire multi-file ingest.

    Args:
        parser: The parser to delegate to; initialized here if needed.
        file: Path to the file being parsed.
        errors: Decoding error policy, forwarded to the parser.

    Returns:
        The parsed text, or list of row strings.

    Raises:
        DocumentParseError: If the fallback parser fails for any reason.
    """
    try:
        if not parser.parser_config_set:
            parser.init_parser()
        return parser.parse_file(file, errors)
    except DocumentParseError:
        raise
    except ImportError:
        # A fallback whose dependency is missing is a deployment problem, not
        # a bad document: let it reach the ingest task's setup-error path
        # instead of blaming every file with "could not be read".
        raise
    except Exception as e:
        logger.error(
            f"Fallback parse of {Path(file).name} with "
            f"{type(parser).__name__} failed: {e}",
            exc_info=True,
        )
        raise DocumentParseError(
            f"Failed to parse {Path(file).name}: the file could not be read."
        ) from e
