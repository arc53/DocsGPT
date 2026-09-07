"""
Google Drive connector for DocsGPT.

This module provides authentication and document loading capabilities for Google Drive.
"""

from .auth import GoogleDriveAuth
from .loader import GoogleDriveLoader

__all__ = ['GoogleDriveAuth', 'GoogleDriveLoader']
