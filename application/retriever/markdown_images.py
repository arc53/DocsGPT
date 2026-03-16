import re
from typing import List

# Matches: ![alt text](https://public.example.com/image.png "optional title")
MARKDOWN_IMAGE_URL_PATTERN = re.compile(
    r"!\[[^\]]*\]\((https?://[^\s)]+)(?:\s+\"[^\"]*\")?\)",
    re.IGNORECASE,
)


def extract_public_markdown_image_urls(markdown_text: str) -> List[str]:
    """Extract public http(s) image URLs from markdown image tags."""
    if not markdown_text:
        return []

    urls = [match.group(1).strip() for match in MARKDOWN_IMAGE_URL_PATTERN.finditer(markdown_text)]

    # Preserve order and remove duplicates
    seen = set()
    unique_urls = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    return unique_urls


def build_multimodal_rag_context(markdown_chunk: str) -> str:
    """
    Append extracted markdown image URLs to retrieved context so multimodal models
    can access referenced documentation visuals.
    """
    image_urls = extract_public_markdown_image_urls(markdown_chunk)
    if not image_urls:
        return markdown_chunk

    image_lines = "\n".join(f"- {url}" for url in image_urls)
    return (
        f"{markdown_chunk}\n\n"
        "Referenced public image URLs from this documentation chunk:\n"
        f"{image_lines}"
    )
