"""Local file system implementation."""
import os
import shutil
from typing import BinaryIO, List

from application.core.settings import settings
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
    
    def save_file(self, file_data: BinaryIO, path: str) -> str:
        """Save a file to local storage."""
        full_path = self._get_full_path(path)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Write file
        if hasattr(file_data, 'save'):
            # Handle Flask's FileStorage objects
            file_data.save(full_path)
        else:
            # Handle regular file-like objects
            with open(full_path, 'wb') as f:
                shutil.copyfileobj(file_data, f)
        
        return path
    
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
