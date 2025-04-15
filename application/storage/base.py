"""Base storage class for file system abstraction."""
from abc import ABC, abstractmethod
from typing import BinaryIO, List


class BaseStorage(ABC):
    """Abstract base class for storage implementations."""

    @abstractmethod
    def save_file(self, file_data: BinaryIO, path: str) -> str:
        """
        Save a file to storage.
        
        Args:
            file_data: File-like object containing the data
            path: Path where the file should be stored
            
        Returns:
            str: The complete path where the file was saved
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
