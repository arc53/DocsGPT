"""Simple reader that reads files of different formats from a directory."""
import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from docsgpt.parser.file.base import BaseReader
from docsgpt.parser.file.base_parser import BaseParser, DocumentParseError, TransientParseError, module_available
from docsgpt.parser.file.docs_parser import DocxParser, PDFParser
from docsgpt.parser.file.epub_parser import EpubParser
from docsgpt.parser.file.html_parser import HTMLParser
from docsgpt.parser.file.markdown_parser import MarkdownParser
from docsgpt.parser.file.rst_parser import RstParser
from docsgpt.parser.file.tabular_parser import PandasCSVParser, ExcelParser
from docsgpt.parser.file.json_parser import JSONParser
from docsgpt.parser.file.pptx_parser import PPTXParser
from docsgpt.parser.file.image_parser import ImageParser
from docsgpt.parser.file.audio_parser import AudioParser
from docsgpt.parser.schema.base import Document
from docsgpt.parser.tokenization import count_tokens_windowed
from docsgpt.stt.constants import SUPPORTED_AUDIO_EXTENSIONS
from docsgpt.core.settings import settings
from docsgpt.core.optional_deps import install_hint


def _sleep(seconds: float) -> None:
    """The cool-down before rate-limited files are parsed again; a module attribute so tests can skip it."""
    time.sleep(seconds)


def _build_audio_parser_mapping() -> Dict[str, BaseParser]:
    return {extension: AudioParser() for extension in SUPPORTED_AUDIO_EXTENSIONS}


def _wrap_pdf_fast_path(pdf_parser: BaseParser) -> BaseParser:
    """Put the pypdfium2 text-layer parser in front of ``pdf_parser``.

    Args:
        pdf_parser: Parser to fall back to for PDFs with no usable text layer.

    Returns:
        BaseParser: The fast-path parser, or ``pdf_parser`` unchanged when
        pypdfium2 is unavailable.
    """
    try:
        from docsgpt.parser.file.pdfium_parser import PdfiumTextParser
    except ImportError:
        logging.warning(
            "pypdfium2 is not installed; PDF attachments will use %s",
            type(pdf_parser).__name__,
        )
        return pdf_parser
    return PdfiumTextParser(
        fallback_parser=pdf_parser,
        min_median_chars=settings.ATTACHMENT_PDF_TEXT_MIN_MEDIAN_CHARS,
    )


def _gained_format_entries() -> Dict[str, BaseParser]:
    """Anydoc-only formats (legacy/macro Office, OpenDocument, RTF) for every map.

    anydoc is a core dependency, so these suffixes are parseable under both
    engines. When anydoc is somehow missing the entries are omitted and
    ``SimpleDirectoryReader.load_data`` rejects such files with a
    ``DocumentParseError`` naming the install, rather than reading OLE/zip
    bytes as text.
    """
    from docsgpt.parser.file.anydoc_parser import (
        ANYDOC_GAINED_SUFFIXES,
        AnydocParser,
        anydoc_available,
    )

    if not anydoc_available():
        return {}
    return {suffix: AnydocParser() for suffix in ANYDOC_GAINED_SUFFIXES}


def _native_ocr_parsers(
    text_parser: Optional[BaseParser] = None,
) -> Optional[Tuple[BaseParser, Callable[[], BaseParser]]]:
    """PDF parser and image-parser factory for the native OCR backend.

    Args:
        text_parser: Parser for PDFs whose every page has a text layer (the
            docling PDF parser under the docling engine); None reads text
            layers with pypdfium2.

    Returns:
        ``(pdf_parser, image_parser_factory)``, or None when pypdfium2 or
        Pillow is missing — both are core dependencies, so that is a broken
        install, logged as such.
    """
    from docsgpt.parser.file.ocr_parser import (
        NativeOcrImageParser,
        NativeOcrPdfParser,
        native_ocr_available,
    )

    if not native_ocr_available():
        logging.error(
            "OCR is enabled but pypdfium2/Pillow are not importable, so the native "
            "OCR backend cannot run; scanned PDFs and images will not be OCR'd"
        )
        return None
    return NativeOcrPdfParser(text_parser=text_parser), NativeOcrImageParser


def _image_entries(factory: Callable[[], BaseParser], suffixes) -> Dict[str, BaseParser]:
    """One parser instance per image suffix."""
    return {suffix: factory() for suffix in suffixes}


def _legacy_file_extractor(pdf_text_fast_path: bool = False, ocr_enabled: bool = False) -> Dict[str, BaseParser]:
    """Parser map that needs neither docling nor anydoc.

    Args:
        pdf_text_fast_path: Put the pypdfium2 text-layer parser in front of
            the PDF parser.
        ocr_enabled: Use the native OCR parsers (tesseract / DeepSeek-OCR via
            pypdfium2 + Pillow) for PDFs and images instead of the plain
            pypdf / remote-service parsers.

    Returns:
        Dict[str, BaseParser]: Parser keyed by lower-case file suffix.
    """
    from docsgpt.parser.file.ocr_parser import IMAGE_SUFFIXES

    pdf_parser: BaseParser = PDFParser()
    # Every image suffix gets an entry even without OCR: the image itself is
    # what a vision model is sent, so a missing entry only means the upload is
    # refused before any model sees it (.webp was, in production).
    images: Dict[str, BaseParser] = _image_entries(ImageParser, sorted(IMAGE_SUFFIXES))
    if ocr_enabled:
        native = _native_ocr_parsers()
        if native is not None:
            pdf_parser, image_factory = native
            images = _image_entries(image_factory, sorted(IMAGE_SUFFIXES))
    if pdf_text_fast_path:
        pdf_parser = _wrap_pdf_fast_path(pdf_parser)
    return {
        ".pdf": pdf_parser,
        ".docx": DocxParser(),
        ".csv": PandasCSVParser(),
        ".xlsx": ExcelParser(),
        ".epub": EpubParser(),
        ".md": MarkdownParser(),
        ".rst": RstParser(),
        ".html": HTMLParser(),
        ".xhtml": HTMLParser(),
        ".mdx": MarkdownParser(),
        ".json": JSONParser(),
        ".pptx": PPTXParser(),
        **images,
        **_build_audio_parser_mapping(),
        **_gained_format_entries(),
    }


def _docling_file_extractor(
    ocr_enabled: bool,
    pdf_text_fast_path: bool = False,
    *,
    missing_log_level: int = logging.WARNING,
) -> Dict[str, BaseParser]:
    """docling parser map, or the legacy map when docling is not installed.

    With OCR on, ``OCR_BACKEND`` decides who OCRs: docling's own hybrid
    pipeline, or the native parsers (``ocr_parser.py``) with the docling PDF
    parser kept — OCR off — for PDFs that have a text layer on every page.
    Without docling installed the legacy map takes over, itself using the
    native OCR parsers when OCR is on.

    The availability check has to happen here, not at parse time:
    ``DoclingParser`` only imports docling inside ``_init_parser``, and the
    ``ImportError`` that raises is not a ``DocumentParseError``, so a map
    that handed out docling parsers on a docling-less install would abort
    the whole ingest on its first file instead of degrading.

    Args:
        ocr_enabled: Enable OCR in the docling PDF/image parsers.
        pdf_text_fast_path: Put the pypdfium2 text-layer parser in front of
            the PDF parser (attachments only; see ``get_default_file_extractor``).
        missing_log_level: Level at which a missing docling install is logged;
            informational when docling is only the *fallback* engine.

    Returns:
        Dict[str, BaseParser]: Parser keyed by lower-case file suffix.
    """
    try:
        if not module_available("docling"):
            raise ImportError("docling is not installed")
        from docsgpt.parser.file.docling_parser import (
            DoclingPDFParser,
            DoclingDocxParser,
            DoclingPPTXParser,
            DoclingXLSXParser,
            DoclingHTMLParser,
            DoclingImageParser,
            DoclingCSVParser,
            DoclingAsciiDocParser,
            DoclingVTTParser,
            DoclingXMLParser,
        )
    except ImportError:
        logging.log(
            missing_log_level,
            "docling is not installed. Using standard parsers%s. For layout-model "
            "parsing, install the docling extra: %s",
            " with native OCR" if ocr_enabled else "",
            install_hint("docling"),
        )
        return _legacy_file_extractor(pdf_text_fast_path, ocr_enabled=ocr_enabled)

    from docsgpt.parser.file.ocr_parser import IMAGE_SUFFIXES, resolve_ocr_backend

    native = None
    if ocr_enabled and resolve_ocr_backend() == "native":
        native = _native_ocr_parsers(text_parser=DoclingPDFParser(ocr_enabled=False))
    if native is not None:
        pdf_parser, image_factory = native
        images = _image_entries(image_factory, sorted(IMAGE_SUFFIXES))
    else:
        pdf_parser = DoclingPDFParser(ocr_enabled=ocr_enabled)
        # Images (with OCR) - only use Docling when OCR is enabled
        image_factory = (
            (lambda: DoclingImageParser(ocr_enabled=True)) if ocr_enabled else ImageParser
        )
        images = _image_entries(image_factory, sorted(IMAGE_SUFFIXES))
    if pdf_text_fast_path:
        pdf_parser = _wrap_pdf_fast_path(pdf_parser)
    return {
        # Documents
        ".pdf": pdf_parser,
        ".docx": DoclingDocxParser(),
        ".pptx": DoclingPPTXParser(),
        ".xlsx": DoclingXLSXParser(),
        # Web formats
        ".html": DoclingHTMLParser(),
        ".xhtml": DoclingHTMLParser(),
        # Data formats
        ".csv": DoclingCSVParser(),
        ".json": JSONParser(),  # Keep JSON parser (specialized handling)
        # Text/markup formats
        ".md": MarkdownParser(),  # Keep markdown parser (specialized handling)
        ".mdx": MarkdownParser(),
        ".rst": RstParser(),
        ".adoc": DoclingAsciiDocParser(),
        ".asciidoc": DoclingAsciiDocParser(),
        # Images: OCR'd by the selected backend when OCR is on, else ImageParser
        **images,
        # Media/subtitles
        ".vtt": DoclingVTTParser(),
        **_build_audio_parser_mapping(),
        # Specialized XML formats
        ".xml": DoclingXMLParser(),
        # Formats docling doesn't support - use standard parsers
        ".epub": EpubParser(),
        # Formats only anydoc reads (legacy/macro Office, OpenDocument, RTF)
        **_gained_format_entries(),
    }


def _anydoc_file_extractor(ocr_enabled: bool, pdf_text_fast_path: bool = False) -> Dict[str, BaseParser]:
    """anydoc parser map, layered over the docling (or legacy) map.

    anydoc takes every format it converts; each of those parsers gets the
    base map's parser for the same suffix as ``fallback_parser``, so a
    scanned PDF still reaches OCR — docling's when it is installed and
    selected, the native OCR parser otherwise — and the legacy parser when
    OCR is off. docling, when installed, also keeps serving what anydoc
    cannot: ``.adoc``/``.vtt``/``.xml``. Images go to whichever OCR backend
    is active. HTML goes to the markdownify-based ``HTMLMarkdownParser``.

    ``pdf_text_fast_path`` is deliberately ignored here: anydoc already reads
    the text layer in milliseconds *and* keeps headings/tables, and does its
    own scanned-PDF detection, so putting pypdfium2 in front of it would
    only lose structure.

    Args:
        ocr_enabled: Enable OCR in the docling fallback/image parsers.
        pdf_text_fast_path: Honored only when anydoc is not installed and the
            map degrades to the base engine.

    Returns:
        Dict[str, BaseParser]: Parser keyed by lower-case file suffix.
    """
    from docsgpt.parser.file.anydoc_parser import (
        ANYDOC_SUFFIXES,
        AnydocParser,
        anydoc_available,
    )
    from docsgpt.parser.file.html_parser import HTMLMarkdownParser

    if not anydoc_available():
        logging.warning(
            "firecrawl-anydoc is not installed; DOC_PARSER_ENGINE=anydoc is using "
            "the %s parsers instead. Install with: pip install firecrawl-anydoc",
            "docling" if module_available("docling") else "standard",
        )
        return _docling_file_extractor(ocr_enabled, pdf_text_fast_path)

    base = _docling_file_extractor(
        ocr_enabled, pdf_text_fast_path=False, missing_log_level=logging.INFO
    )
    extractor = dict(base)
    for suffix in ANYDOC_SUFFIXES:
        fallback = base.get(suffix)
        if isinstance(fallback, AnydocParser):
            # A gained-format entry from the base map is already a
            # fallback-less AnydocParser — anydoc delegating to anydoc would
            # just repeat the same failure.
            continue
        extractor[suffix] = AnydocParser(fallback_parser=fallback)
    extractor[".html"] = HTMLMarkdownParser()
    extractor[".xhtml"] = HTMLMarkdownParser()
    return extractor


def get_default_file_extractor(
    ocr_enabled: Optional[bool] = None,
    pdf_text_fast_path: bool = False,
    engine: Optional[str] = None,
) -> Dict[str, BaseParser]:
    """Get the default file extractor.

    The engine is ``settings.DOC_PARSER_ENGINE`` unless overridden:

    * ``anydoc`` (default): firecrawl-anydoc for office/PDF/tabular formats,
      markdownify for HTML, the active OCR backend for images and as the
      fallback for scanned PDFs; docling (if installed) for the rest anydoc
      rejects, legacy parsers otherwise.
    * ``docling``: the docling map, with the legacy parsers when docling is
      not installed.

    Args:
        ocr_enabled: Enable OCR for scanned PDFs and images, through the
            backend ``OCR_BACKEND`` resolves to. Defaults to
            ``settings.OCR_ENABLED``.
        pdf_text_fast_path: Read PDFs via their embedded text layer
            (pypdfium2) instead of docling, falling back to docling for scans.
            Off by default: it trades docling's structural markdown for speed,
            which suits attachments (read into a prompt) but not source
            ingestion (chunked and embedded for retrieval). A no-op under the
            anydoc engine, which is already that fast and keeps structure.
        engine: ``"anydoc"`` or ``"docling"``; ``None`` reads the setting.

    Returns:
        Dict[str, BaseParser]: Parser keyed by lower-case file suffix.
    """
    if ocr_enabled is None:
        ocr_enabled = settings.OCR_ENABLED
    selected = (engine or settings.DOC_PARSER_ENGINE or "anydoc")
    selected = str(selected).strip().lower()
    if selected == "docling":
        return _docling_file_extractor(ocr_enabled, pdf_text_fast_path)
    if selected != "anydoc":
        logging.warning("Unknown DOC_PARSER_ENGINE %r; using anydoc", selected)
    return _anydoc_file_extractor(ocr_enabled, pdf_text_fast_path)


# For backwards compatibility
DEFAULT_FILE_EXTRACTOR: Dict[str, BaseParser] = get_default_file_extractor()


class SimpleDirectoryReader(BaseReader):
    """Simple directory reader.

    Can read files into separate documents, or concatenates
    files into one document text.

    Args:
        input_dir (str): Path to the directory.
        input_files (List): List of file paths to read (Optional; overrides input_dir)
        exclude_hidden (bool): Whether to exclude hidden files (dotfiles).
        errors (str): how encoding and decoding errors are to be handled,
              see https://docs.python.org/3/library/functions.html#open
        recursive (bool): Whether to recursively search in subdirectories.
            False by default.
        required_exts (Optional[List[str]]): List of required extensions.
            Default is None.
        file_extractor (Optional[Dict[str, BaseParser]]): A mapping of file
            extension to a BaseParser class that specifies how to convert that file
            to text. See DEFAULT_FILE_EXTRACTOR.
        num_files_limit (Optional[int]): Maximum number of files to read.
            Default is None.
        file_metadata (Optional[Callable[str, Dict]]): A function that takes
            in a filename and returns a Dict of metadata for the Document.
            Default is None.
        parse_cache_user (Optional[str]): The user whose stored parses
            (``docsgpt.parser.parse_cache``) are reused and added to: a file
            whose bytes and parser settings match one they already parsed is
            not parsed again. None, or ``PARSE_CACHE_ENABLED`` off, reads and
            writes no cache.
    """

    def __init__(
            self,
            input_dir: Optional[str] = None,
            input_files: Optional[List] = None,
            exclude_hidden: bool = True,
            errors: str = "ignore",
            recursive: bool = True,
            required_exts: Optional[List[str]] = None,
            file_extractor: Optional[Dict[str, BaseParser]] = None,
            num_files_limit: Optional[int] = None,
            file_metadata: Optional[Callable[[str], Dict]] = None,
            parse_cache_user: Optional[str] = None,
    ) -> None:
        """Initialize with parameters."""
        super().__init__()

        if not input_dir and not input_files:
            raise ValueError("Must provide either `input_dir` or `input_files`.")

        self.errors = errors

        self.recursive = recursive
        self.exclude_hidden = exclude_hidden
        # Normalize extensions to lowercase for case-insensitive matching
        self.required_exts = (
            [ext.lower() for ext in required_exts] if required_exts else None
        )
        self.num_files_limit = num_files_limit

        if input_files:
            self.input_files = []
            for path in input_files:
                print(path)
                input_file = Path(path)
                self.input_files.append(input_file)
        elif input_dir:
            self.input_dir = Path(input_dir)
            self.input_files = self._add_files(self.input_dir)

        self.file_extractor = file_extractor or DEFAULT_FILE_EXTRACTOR
        self.file_metadata = file_metadata
        # (path, message) per file skipped by ``load_data`` as unparseable.
        self.failed_files: List[Tuple[Path, str]] = []
        # The paths in ``failed_files`` whose failure may pass on a later try
        # (``TransientParseError``: a rate limit, a 5xx, a timeout).
        self.transient_failures: Set[Path] = set()
        self._parse_cache = None
        if parse_cache_user:
            from docsgpt.parser import parse_cache

            if parse_cache.cache_enabled():
                self._parse_cache = parse_cache.ParseCache(parse_cache_user)
        # Files answered from the parse cache instead of a parser, per ``load_data``.
        self.cache_hits = 0
        # SHA-256 per resolved file path, so a file hashed for the cache is
        # not read again for ``directory_structure``.
        self._file_hashes: Dict[str, str] = {}

    def _add_files(self, input_dir: Path) -> List[Path]:
        """Add files."""
        input_files = sorted(input_dir.iterdir())
        new_input_files = []
        dirs_to_explore = []
        for input_file in input_files:
            if input_file.is_dir():
                if self.recursive:
                    dirs_to_explore.append(input_file)
            elif self.exclude_hidden and input_file.name.startswith("."):
                continue
            elif (
                    self.required_exts is not None
                    and input_file.suffix.lower() not in self.required_exts
            ):
                continue
            else:
                new_input_files.append(input_file)

        for dir_to_explore in dirs_to_explore:
            sub_input_files = self._add_files(dir_to_explore)
            new_input_files.extend(sub_input_files)

        if self.num_files_limit is not None and self.num_files_limit > 0:
            new_input_files = new_input_files[0: self.num_files_limit]

        # print total number of files added
        logging.debug(
            f"> [SimpleDirectoryReader] Total files added: {len(new_input_files)}"
        )

        return new_input_files

    def load_data(
        self,
        concatenate: bool = False,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[Document]:
        """Load data from the input directory.

        Args:
            concatenate (bool): whether to concatenate all files into one document.
                If set to True, file metadata is ignored.
                False by default.
            progress_callback (Optional[Callable[[int, int], None]]): Called
                after each file is parsed with ``(files_done, total_files)``.
                Lets callers surface parse/OCR progress before embedding
                begins. Exceptions raised by the callback are swallowed so
                progress reporting can never fail ingestion.

        A file whose OCR ran out of its rate-limit budget
        (``OcrRateLimitedError``) is not given up on: after every other file,
        and ``OCR_RATE_LIMIT_COOLDOWN`` seconds, it is parsed again, one file
        at a time; the OCR parsers keep the pages they already recognised, so
        only the missing ones are sent. Only a file that still fails is
        listed in ``failed_files``, and in ``transient_failures`` when its
        failure may pass later.

        Returns:
            List[Document]: A list of documents.

        Raises:
            DocumentParseError: if no input file could be parsed. Individual
                unreadable files are skipped and recorded in ``failed_files``
                so one corrupt document does not cost the caller the rest of
                the batch; a single-file read (the attachment path) still
                raises, since skipping there would only defer the failure to
                an empty result.
        """
        data_list: List[str] = []
        metadata_list: List[Dict[str, Any]] = []
        first_error: Optional[DocumentParseError] = None
        self.file_token_counts = {}
        self.failed_files = []
        self.transient_failures = set()
        self.cache_hits = 0
        # Files whose OCR ran out of its rate-limit budget: parsed again,
        # one at a time, after every other file and a cool-down.
        deferred: List[Path] = []

        total_files = len(self.input_files)

        def report_progress(files_done: int) -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(files_done, total_files)
            except Exception:
                logging.warning("load_data progress callback failed", exc_info=True)

        def record_failure(input_file: Path, error: DocumentParseError) -> None:
            nonlocal first_error
            logging.warning(f"Skipping unreadable file {input_file.name}: {error}")
            self.failed_files.append((input_file, str(error)))
            if isinstance(error, TransientParseError):
                self.transient_failures.add(input_file)
            first_error = first_error or error

        from docsgpt.parser.file.ocr_parser import OcrRateLimitedError

        for file_index, input_file in enumerate(self.input_files):
            try:
                data, parser_metadata = self._read_file(input_file)
            except OcrRateLimitedError as e:
                logging.info(f"OCR of {input_file.name} is rate limited; parsing it again after the other files: {e}")
                deferred.append(input_file)
            except DocumentParseError as e:
                record_failure(input_file, e)
            else:
                self._add_parsed(input_file, data, parser_metadata, data_list, metadata_list)
            report_progress(file_index + 1)

        if deferred:
            from docsgpt.core.settings import settings

            cooldown = max(0.0, float(settings.OCR_RATE_LIMIT_COOLDOWN))
            logging.info(
                f"Waiting {cooldown:.0f}s for the OCR rate limit before parsing {len(deferred)} file(s) again"
            )
            _sleep(cooldown)
            for input_file in deferred:
                try:
                    data, parser_metadata = self._read_file(input_file)
                except DocumentParseError as e:
                    record_failure(input_file, e)
                else:
                    self._add_parsed(input_file, data, parser_metadata, data_list, metadata_list)

        # Every file failed: there is nothing to ingest, so this is a failed
        # read rather than an empty one. Callers (the attachment worker, the
        # ingest tasks) treat it as terminal and tell the user.
        if self.failed_files and not data_list:
            if len(self.failed_files) == 1:
                # Single-file read (the attachment path): re-raise the parser's
                # own exception, so its message reaches the user verbatim and
                # its type (``NoTextLayerError`` for a scan) reaches the caller.
                raise first_error
            names = ", ".join(p.name for p, _ in self.failed_files[:5])
            raise DocumentParseError(
                f"None of the {len(self.failed_files)} files could be parsed: "
                f"{names}{'…' if len(self.failed_files) > 5 else ''} "
                f"({self.failed_files[0][1]})"
            )

        # Build directory structure if input_dir is provided
        if hasattr(self, 'input_dir'):
            self.directory_structure = self.build_directory_structure(self.input_dir)
            logging.info("Directory structure built successfully")
        else:
            self.directory_structure = {}

        if concatenate:
            return [Document("\n".join(data_list))]
        elif self.file_metadata is not None:
            return [Document(d, extra_info=m) for d, m in zip(data_list, metadata_list)]
        else:
            return [Document(d) for d in data_list]

    def _read_file(self, input_file: Path) -> Tuple[Union[str, List[str]], Dict[str, Any]]:
        """Parse one file with the parser for its suffix, or read it as text.

        Returns:
            ``(data, parser_metadata)``: the text (or rows) and the parser's metadata for the file.

        Raises:
            DocumentParseError: The file could not be parsed.
        """
        suffix_lower = input_file.suffix.lower()
        if suffix_lower in self.file_extractor:
            return self._parse_one(self.file_extractor[suffix_lower], input_file)
        from docsgpt.parser.file.anydoc_parser import ANYDOC_GAINED_SUFFIXES

        if suffix_lower in ANYDOC_GAINED_SUFFIXES:
            # Binary office formats only anydoc reads; without it
            # the standard read would index OLE/zip bytes as text.
            raise DocumentParseError(
                f"No parser is available for {suffix_lower} files: "
                "firecrawl-anydoc is not installed (pip install firecrawl-anydoc)"
            )
        # do standard read
        with open(input_file, "r", encoding="utf-8", errors=self.errors) as f:
            return f.read(), {}

    def _add_parsed(
        self,
        input_file: Path,
        data: Union[str, List[str]],
        parser_metadata: Dict[str, Any],
        data_list: List[str],
        metadata_list: List[Dict[str, Any]],
    ) -> None:
        """Count a parsed file's tokens and append its text and metadata to the lists ``load_data`` builds."""
        if isinstance(data, List):
            file_tokens = sum(count_tokens_windowed(str(d)) for d in data)
        else:
            file_tokens = count_tokens_windowed(str(data))

        full_path = str(input_file.resolve())
        self.file_token_counts[full_path] = file_tokens

        base_metadata = {
            'title': input_file.name,
            'token_count': file_tokens,
        }
        if parser_metadata:
            base_metadata.update(parser_metadata)

        if hasattr(self, 'input_dir'):
            try:
                relative_path = str(input_file.relative_to(self.input_dir))
                base_metadata['source'] = relative_path
            except ValueError:
                base_metadata['source'] = str(input_file)
        else:
            base_metadata['source'] = str(input_file)

        if self.file_metadata is not None:
            custom_metadata = self.file_metadata(input_file.name)
            base_metadata.update(custom_metadata)

        if isinstance(data, List):
            # Extend data_list with each item in the data list
            data_list.extend([str(d) for d in data])
            # copy(): chunking writes token_count into this dict in
            # place, so a shared reference gives every chunk the last
            # chunk's count.
            metadata_list.extend([base_metadata.copy() for _ in data])
        else:
            data_list.append(str(data))
            metadata_list.append(base_metadata.copy())

    def _file_hash(self, path: Path) -> str:
        """SHA-256 of a file's bytes, hashed once per reader."""
        hashes = self.__dict__.setdefault("_file_hashes", {})
        key = str(Path(path).resolve())
        digest = hashes.get(key)
        if digest is None:
            digest = hashes[key] = _file_sha256(Path(path))
        return digest

    def _parse_one(self, parser: BaseParser, input_file: Path) -> Tuple[Union[str, List[str]], Dict]:
        """Parse one file, or reuse the user's stored parse of the same bytes.

        A hit skips the parser entirely (no init, no OCR). A miss parses and
        stores the result when it is complete; a parser that raises stores
        nothing, and the error propagates as before.

        Args:
            parser: The parser for the file's suffix.
            input_file: The file.

        Returns:
            ``(parser output, parser metadata)``.
        """
        cache = getattr(self, "_parse_cache", None)
        content_sha256 = None
        if cache is not None:
            from docsgpt.parser.parse_cache import worth_caching

            if worth_caching(input_file):
                try:
                    content_sha256 = self._file_hash(input_file)
                except OSError:
                    content_sha256 = None
        if content_sha256 is not None:
            hit = cache.lookup(content_sha256, parser)
            if hit is not None:
                self.cache_hits = getattr(self, "cache_hits", 0) + 1
                logging.info(f"Reusing the stored parse of {input_file.name}")
                return hit
        if not parser.parser_config_set:
            parser.init_parser()
        data = parser.parse_file(input_file, errors=self.errors)
        parser_metadata = parser.get_file_metadata(input_file)
        if content_sha256 is not None:
            cache.store(content_sha256, parser, data, parser_metadata)
        return data, parser_metadata

    def scan_directory(self) -> dict:
        """Build ``directory_structure`` (each file's type, size and SHA-256) without parsing any file.

        A reingest compares it with what the index was built from and parses
        only the files that changed; entries carry no ``token_count``.

        Returns:
            The structure, also kept as ``self.directory_structure``; ``{}``
            for a reader given ``input_files`` instead of a directory.
        """
        self.directory_structure = (
            self.build_directory_structure(self.input_dir) if hasattr(self, "input_dir") else {}
        )
        return self.directory_structure

    def build_directory_structure(self, base_path):
        """Build a dictionary representing the directory structure.

        Args:
            base_path: The base path to start building the structure from.

        Returns:
            dict: A nested dictionary representing the directory structure.
        """
        import mimetypes
        
        def build_tree(path):
            """Helper function to recursively build the directory tree."""
            result = {}
            
            for item in path.iterdir():
                if self.exclude_hidden and item.name.startswith('.'):
                    continue
                    
                if item.is_dir():
                    subtree = build_tree(item)
                    if subtree:
                        result[item.name] = subtree
                else:
                    if self.required_exts is not None and item.suffix.lower() not in self.required_exts:
                        continue
                    
                    full_path = str(item.resolve())
                    file_size_bytes = item.stat().st_size
                    mime_type = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
                    
                    file_info = {
                        "type": mime_type,
                        "size_bytes": file_size_bytes,
                        # Lets a reingest tell an edited file from an unchanged one at the same path.
                        "sha256": self._file_hash(item),
                    }
                    
                    if hasattr(self, 'file_token_counts') and full_path in self.file_token_counts:
                        file_info["token_count"] = self.file_token_counts[full_path]
                        
                    result[item.name] = file_info
                    
            return result
        
        return build_tree(Path(base_path))


def _file_sha256(path: Path) -> str:
    """The SHA-256 of a file's bytes, read in blocks so a large file is never held in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
