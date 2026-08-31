"""Local file system implementation."""
import os
import shutil
import tempfile
from typing import BinaryIO, List, Callable

from application.storage.base import BaseStorage


class LocalStorage(BaseStorage):
    """Local file system storage implementation."""

    def __init__(self, base_dir: str = None):
        """
        Initialize local storage.

        Args:
            base_dir: Base directory for all operations. If None, uses current directory.
        """
        self.base_dir = base_dir or os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

    def _get_full_path(self, path: str) -> str:
        """Get absolute path by combining base_dir and path.

        Raises:
            ValueError: If the resolved path escapes base_dir (path traversal).
        """
        if os.path.isabs(path):
            resolved = os.path.realpath(path)
        else:
            resolved = os.path.realpath(os.path.join(self.base_dir, path))
        base = os.path.realpath(self.base_dir)
        if not resolved.startswith(base + os.sep) and resolved != base:
            raise ValueError(f"Path traversal detected: {path}")
        return resolved

    def save_file(self, file_data: BinaryIO, path: str, **kwargs) -> dict:
        """Save a file, replacing any existing one atomically.

        The bytes land on a temporary file beside the destination and are moved
        into place with ``os.replace``, so an interrupted write leaves the
        previous file intact instead of a truncated one. Streaming straight onto
        the destination is unrecoverable for a file that is rewritten in place:
        a half-written ``index.faiss`` loads at neither the old width nor the
        new one, and ``application.scripts.reembed`` rewrites every index it
        touches.
        """
        full_path = self._get_full_path(path)
        directory = os.path.dirname(full_path)
        os.makedirs(directory, exist_ok=True)

        # Same directory as the destination, so the replace below is a rename
        # within one filesystem rather than a copy.
        fd, temp_path = tempfile.mkstemp(
            dir=directory, prefix=f".{os.path.basename(full_path)}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as f:
                if hasattr(file_data, "save"):
                    file_data.save(f)
                else:
                    shutil.copyfileobj(file_data, f)
                f.flush()
                os.fsync(f.fileno())
            # mkstemp is 0600; keep whatever the file already had, or fall back
            # to what a plain open() would have produced.
            try:
                mode = os.stat(full_path).st_mode & 0o777
            except FileNotFoundError:
                mode = 0o644
            os.chmod(temp_path, mode)
            os.replace(temp_path, full_path)
        except BaseException:
            # A successful replace consumes the temp file; every other exit
            # leaves it behind.
            try:
                os.unlink(temp_path)
            except OSError:
                # Best-effort: the write already failed, and that exception is
                # the one worth raising. A temp file we cannot remove must not
                # mask it.
                pass
            raise

        return {
            'storage_type': 'local'
        }

    def get_file(self, path: str) -> BinaryIO:
        """Get a file from local storage."""
        full_path = self._get_full_path(path)

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {full_path}")

        return open(full_path, 'rb')

    def get_file_size(self, path: str) -> int:
        """Return the size of a local file without opening and buffering it."""
        full_path = self._get_full_path(path)
        try:
            return os.path.getsize(full_path)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"File not found: {full_path}") from exc

    def delete_file(self, path: str) -> bool:
        """Delete a file from local storage."""
        full_path = self._get_full_path(path)

        if not os.path.exists(full_path):
            return False

        os.remove(full_path)
        return True

    def file_exists(self, path: str) -> bool:
        """Check if a file exists in local storage."""
        full_path = self._get_full_path(path)
        return os.path.exists(full_path)

    def list_files(self, directory: str) -> List[str]:
        """List all files in a directory in local storage."""
        full_path = self._get_full_path(directory)

        if not os.path.exists(full_path):
            return []

        result = []
        for root, _, files in os.walk(full_path):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), self.base_dir)
                result.append(rel_path)

        return result

    def process_file(self, path: str, processor_func: Callable, **kwargs):
        """
        Process a file using the provided processor function.

        For local storage, we can directly pass the full path to the processor.

        Args:
            path: Path to the file
            processor_func: Function that processes the file
            **kwargs: Additional arguments to pass to the processor function

        Returns:
            The result of the processor function
        """
        full_path = self._get_full_path(path)

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {full_path}")

        return processor_func(local_path=full_path, **kwargs)

    def is_directory(self, path: str) -> bool:
        """
        Check if a path is a directory in local storage.
        
        Args:
            path: Path to check
        
        Returns:
            bool: True if the path is a directory, False otherwise
        """
        full_path = self._get_full_path(path)
        return os.path.isdir(full_path)

    def remove_directory(self, directory: str) -> bool:
        """
        Remove a directory and all its contents from local storage.

        Args:
            directory: Directory path to remove

        Returns:
            bool: True if removal was successful, False otherwise
        """
        full_path = self._get_full_path(directory)

        if not os.path.exists(full_path):
            return False

        if not os.path.isdir(full_path):
            return False

        try:
            shutil.rmtree(full_path)
            return True
        except (OSError, PermissionError):
            return False
