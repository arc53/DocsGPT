"""Local file system implementation."""
import os
import shutil
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
        """Get absolute path by combining base_dir and path."""
        if os.path.isabs(path):
            return path
        return os.path.join(self.base_dir, path)

    def save_file(self, file_data: BinaryIO, path: str) -> dict:
        """Save a file to local storage."""
        full_path = self._get_full_path(path)

        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        if hasattr(file_data, 'save'):
            file_data.save(full_path)
        else:
            with open(full_path, 'wb') as f:
                shutil.copyfileobj(file_data, f)

        return {
            'storage_type': 'local'
        }

    def get_file(self, path: str) -> BinaryIO:
        """Get a file from local storage."""
        full_path = self._get_full_path(path)

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {full_path}")

        return open(full_path, 'rb')

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
        except (OSError, PermissionError) as e:
            return False
