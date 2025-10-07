"""
External knowledge base connectors for DocsGPT.

This module contains connectors for external knowledge bases and document storage systems
that require authentication and specialized handling, separate from simple web scrapers.
"""

from .base import BaseConnectorAuth, BaseConnectorLoader
from .connector_creator import ConnectorCreator
from .google_drive import GoogleDriveAuth, GoogleDriveLoader

__all__ = [
    'BaseConnectorAuth',
    'BaseConnectorLoader',
    'ConnectorCreator',
    'GoogleDriveAuth',
    'GoogleDriveLoader'
]
