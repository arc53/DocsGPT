import codecs

from markdownify import markdownify

from application.agents.tools.base import Tool
from application.security.safe_url import (
    ResponseTooLargeError,
    UnsafeUserUrlError,
    pinned_fetch_bytes,
)

# Byte ceiling for a fetched page. One uncapped response (a PDF handed to
# this tool on 07-17) produced a 634k-token "text" result that killed the
# conversation save and every other write lane downstream.
MAX_RESPONSE_BYTES = 10 * 1024 * 1024

# Non-``text/*`` content types markdownify can still meaningfully convert
# to text (any ``text/*`` is allowed by prefix). Anything else (PDFs,
# images, archives, ...) must be refused with a clear error so the model
# picks another tool instead of receiving binary-as-text.
_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/xhtml+xml",
        "application/xml",
        "application/json",
        "application/ld+json",
        "application/rss+xml",
        "application/atom+xml",
    }
)

# Magic prefixes of common binary formats, checked in case the server
# omits or lies about the Content-Type header.
_BINARY_MAGIC_PREFIXES = (
    b"%PDF-",  # PDF
    b"PK\x03\x04",  # zip / docx / xlsx
    b"\x89PNG",  # PNG
    b"GIF8",  # GIF
    b"\xff\xd8\xff",  # JPEG
    b"\x1f\x8b",  # gzip
    b"OggS",  # ogg
    b"\x00\x01\x00\x00",  # ttf
)

_UNSUPPORTED_CONTENT_HINT = (
    "read_webpage only handles HTML/text pages; use a tool suited to this "
    "file type instead."
)


def _declared_charset(content_type: str) -> str | None:
    """Extract the ``charset`` parameter from a Content-Type header value."""
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.strip().lower() == "charset" and value:
            return value.strip("\"' ")
    return None


def _usable_charset(content_type: str) -> str | None:
    """Return the declared charset if Python can actually decode with it."""
    charset = _declared_charset(content_type)
    if not charset:
        return None
    try:
        codecs.lookup(charset)
    except LookupError:
        return None
    return charset


def _is_allowed_media_type(media_type: str) -> bool:
    return media_type.startswith("text/") or media_type in _ALLOWED_CONTENT_TYPES


def _looks_binary(content: bytes, *, trust_declared_charset: bool = False) -> bool:
    """Sniff the first KB for binary magic numbers or NUL bytes.

    The magic-prefix check is unconditional — a lying charset header must
    not sneak a PDF through. The NUL check only applies when no usable
    charset was declared: legitimate UTF-16 text is NUL-dense, and a
    declared charset means the decode path (which strips NULs) handles it.
    """
    head = content[:1024]
    if head.startswith(_BINARY_MAGIC_PREFIXES):
        return True
    if trust_declared_charset:
        return False
    return b"\x00" in head


def _decode_body(content: bytes, content_type: str) -> str:
    """Decode ``content`` with the declared charset, else UTF-8.

    Never falls back to ``response.text``'s guesses: requests' RFC-2616
    ISO-8859-1 default (text/* without charset) maps every raw byte 1:1,
    which is exactly how a PDF once round-tripped into NUL-laden "text".
    NULs are stripped after decoding (NUL is valid UTF-8, and the sniff
    only sees the first KB) so the tool never returns them regardless of
    caller.
    """
    charset = _usable_charset(content_type) or "utf-8"
    return content.decode(charset, errors="replace").replace("\x00", "")


class ReadWebpageTool(Tool):
    """
    Read Webpage (browser)
    A tool to fetch the HTML content of a URL and convert it to Markdown.
    """

    def __init__(self, config=None):
        """
        Initializes the tool.
        :param config: Optional configuration dictionary. Not used by this tool.
        """
        self.config = config

    def execute_action(self, action_name: str, **kwargs) -> str:
        """
        Executes the specified action. For this tool, the only action is 'read_webpage'.

        :param action_name: The name of the action to execute. Should be 'read_webpage'.
        :param kwargs: Keyword arguments, must include 'url'.
        :return: The Markdown content of the webpage or an error message.
        """
        if action_name != "read_webpage":
            return f"Error: Unknown action '{action_name}'. This tool only supports 'read_webpage'."

        url = kwargs.get("url")
        if not url:
            return "Error: URL parameter is missing."

        try:
            content, response = pinned_fetch_bytes(
                url,
                max_bytes=MAX_RESPONSE_BYTES,
                headers={'User-Agent': 'DocsGPT-Agent/1.0'},
                timeout=10,
            )
            # Redirects are not followed (each hop would need its own SSRF
            # validation); without this the redirect body comes back as
            # near-empty markdown with no hint of where the page went.
            if 300 <= response.status_code < 400:
                location = response.headers.get("Location", "")
                if location:
                    return (
                        f"Error: URL redirects to '{location}'. "
                        "Fetch that URL directly instead."
                    )
                return "Error: URL responded with a redirect but no target location."
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            media_type = content_type.split(";")[0].strip().lower()
            if media_type and not _is_allowed_media_type(media_type):
                return (
                    f"Error: URL returned content type '{media_type}', which "
                    f"cannot be converted to text. {_UNSUPPORTED_CONTENT_HINT}"
                )
            if _looks_binary(
                content,
                trust_declared_charset=_usable_charset(content_type) is not None,
            ):
                return (
                    "Error: URL returned binary content, which cannot be "
                    f"converted to text. {_UNSUPPORTED_CONTENT_HINT}"
                )

            html_content = _decode_body(content, content_type)
            markdown_content = markdownify(html_content, heading_style="ATX", newline_style="BACKSLASH")

            return markdown_content

        except UnsafeUserUrlError as e:
            return f"Error: URL validation failed - {e}"
        except ResponseTooLargeError:
            return (
                f"Error: The page is too large to read (over "
                f"{MAX_RESPONSE_BYTES // (1024 * 1024)} MB)."
            )
        except Exception as e:
            return f"Error fetching URL {url}: {e}"

    def get_actions_metadata(self):
        """
        Returns metadata for the actions supported by this tool.
        """
        return [
            {
                "name": "read_webpage",
                "description": (
                    "Fetch a webpage and return its content as clean Markdown "
                    "text. Use it whenever the user shares a URL or the answer "
                    "depends on a specific page. Only works for HTML/text "
                    "pages — not PDFs or other binary files. Input must be a "
                    "fully qualified URL."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The fully qualified URL of the webpage to read (e.g., 'https://www.example.com').",
                        }
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
            }
        ]

    def get_config_requirements(self):
        """
        Returns a dictionary describing the configuration requirements for the tool.
        This tool does not require any specific configuration.
        """
        return {}
