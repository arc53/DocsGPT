from pathlib import Path
from typing import Optional


def validate_tool_path(path: str) -> Optional[str]:
    """Validate and normalize a tool file path, or return None if invalid.

    Shared by MemoryTool and WikiTool. Strips whitespace, ensures a leading
    slash, rejects directory traversal (``..`` or ``//``), and preserves a
    trailing slash to mark directories.

    Args:
        path: User-provided path.

    Returns:
        Normalized path, or None if the path is empty or invalid.
    """
    if not path:
        return None
    path = path.strip()
    is_directory = path.endswith("/")
    if not path.startswith("/"):
        path = "/" + path
    if ".." in path or path.count("//") > 0:
        return None
    try:
        normalized = str(Path(path).as_posix())
        if not normalized.startswith("/"):
            return None
        if is_directory and not normalized.endswith("/") and normalized != "/":
            normalized = normalized + "/"
        return normalized
    except Exception:
        return None
