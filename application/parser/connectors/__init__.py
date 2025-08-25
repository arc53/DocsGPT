"""
External knowledge base connectors for DocsGPT.

This module contains connectors for external knowledge bases and document storage systems
that require authentication and specialized handling, separate from simple web scrapers.
"""

from .connector_creator import ConnectorCreator
from .google_drive import GoogleDriveAuth, GoogleDriveLoader

__all__ = ['ConnectorCreator', 'GoogleDriveAuth', 'GoogleDriveLoader']
