"""
Share Point connector package for DocsGPT.

This module provides authentication and document loading capabilities for Share Point.
"""

from .auth import SharePointAuth
from .loader import SharePointLoader

__all__ = ['SharePointAuth', 'SharePointLoader']