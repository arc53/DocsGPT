"""Base storage class for file system abstraction."""

from abc import ABC, abstractmethod
from typing import BinaryIO, List, Callable


class BaseStorage(ABC):
    """Abstract base class for storage implementations."""

    @abstractmethod
    def save_file(self, file_data: BinaryIO, path: str, **kwargs) -> dict:
        """
        Save a file to storage.

        Args:
            file_data: File-like object containing the data
            path: Path where the file should be stored

        Returns:
            dict: A dictionary containing metadata about the saved file, including:
                - 'path': The path where the file was saved
                - 'storage_type': The type of storage (e.g., 'local', 's3')
                - Other storage-specific metadata (e.g., 'uri', 'bucket_name', etc.)
        """
        pass

    @abstractmethod
    def get_file(self, path: str) -> BinaryIO:
        """
        Retrieve a file from storage.

        Args:
            path: Path to the file

        Returns:
            BinaryIO: File-like object containing the file data
        """
        pass

    @abstractmethod
    def process_file(self, path: str, processor_func: Callable, **kwargs):
        """
        Process a file using the provided processor function.

        This method handles the details of retrieving the file and providing
        it to the processor function in an appropriate way based on the storage type.

        Args:
            path: Path to the file
            processor_func: Function that processes the file
            **kwargs: Additional arguments to pass to the processor function

        Returns:
            The result of the processor function
        """
        pass

    @abstractmethod
    def delete_file(self, path: str) -> bool:
        """
        Delete a file from storage.

        Args:
            path: Path to the file

        Returns:
            bool: True if deletion was successful
        """
        pass

    @abstractmethod
    def file_exists(self, path: str) -> bool:
        """
        Check if a file exists.

        Args:
            path: Path to the file

        Returns:
            bool: True if the file exists
        """
        pass

    @abstractmethod
    def list_files(self, directory: str) -> List[str]:
        """
        List all files in a directory.

        Args:
            directory: Directory path to list

        Returns:
            List[str]: List of file paths
        """
        pass
