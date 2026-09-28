"""
Base classes for external knowledge base connectors.

This module provides minimal abstract base classes that define the essential
interface for external knowledge base connectors.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from docsgpt.parser.schema.base import Document


class BaseConnectorAuth(ABC):
    """
    Abstract base class for connector authentication.
    
    Defines the minimal interface that all connector authentication
    implementations must follow.
    """
    
    @abstractmethod
    def get_authorization_url(self, state: Optional[str] = None) -> str:
        """
        Generate authorization URL for OAuth flows.
        
        Args:
            state: Optional state parameter for CSRF protection
            
        Returns:
            Authorization URL
        """
        pass
    
    @abstractmethod
    def exchange_code_for_tokens(self, authorization_code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access tokens.
        
        Args:
            authorization_code: Authorization code from OAuth callback
            
        Returns:
            Dictionary containing token information
        """
        pass
    
    @abstractmethod
    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh an expired access token.
        
        Args:
            refresh_token: Refresh token
            
        Returns:
            Dictionary containing refreshed token information
        """
        pass
    
    @abstractmethod
    def is_token_expired(self, token_info: Dict[str, Any]) -> bool:
        """
        Check if a token is expired.

        Args:
            token_info: Token information dictionary

        Returns:
            True if token is expired, False otherwise
        """
        pass

    def sanitize_token_info(self, token_info: Dict[str, Any], **extra_fields) -> Dict[str, Any]:
        """Extract the fields safe to persist in the session store.
        """
        return {
            "access_token": token_info.get("access_token"),
            "refresh_token": token_info.get("refresh_token"),
            "token_uri": token_info.get("token_uri"),
            "expiry": token_info.get("expiry"),
            **extra_fields,
        }


class BaseConnectorLoader(ABC):
    """
    Abstract base class for connector loaders.
    
    Defines the minimal interface that all connector loader
    implementations must follow. A loader reads its OAuth tokens through
    ``docsgpt.connectors.service`` from the connection it was built for,
    either directly (``connection_id``, what background sync uses) or through
    a legacy browser ``session_token`` that names the connection.
    """

    connection_id: Optional[str] = None

    @abstractmethod
    def __init__(self, session_token: Optional[str] = None, *, connection_id: Optional[str] = None):
        """
        Initialize the connector loader.
        
        Args:
            session_token: Legacy browser session token naming the connection.
            connection_id: The connection to read tokens from.
        """
        pass

    @classmethod
    def from_connection(cls, connection_id: str) -> "BaseConnectorLoader":
        """Build a loader that reads its tokens from ``connection_id``."""
        return cls(connection_id=connection_id)

    def _load_token_info(
        self, session_token: Optional[str], connection_id: Optional[str],
    ) -> Tuple[str, Dict[str, Any]]:
        """Resolve the connection and return ``(connection_id, token_info)``.

        Raises:
            ValueError: The connection is missing or needs reconnecting.
        """
        from docsgpt.connectors import service

        resolved = connection_id or service.connection_id_for_session_token(session_token)
        self.connection_id = resolved
        return resolved, service.get_valid_token_info(resolved)

    def _refresh_rejected_token(self, access_token: Optional[str]) -> Dict[str, Any]:
        """Token info after the provider answered 401 to ``access_token``.

        Refreshes under the connection's row lock and persists the rotated
        refresh token, or returns the token another worker already renewed.
        """
        from docsgpt.connectors import service

        if not self.connection_id:
            raise ValueError("Loader has no connection to refresh")
        return service.get_valid_token_info(self.connection_id, rejected_access_token=access_token)
    
    @abstractmethod
    def load_data(self, inputs: Dict[str, Any]) -> List[Document]:
        """
        Load documents from the external knowledge base.
        
        Args:
            inputs: Configuration dictionary containing:
                - file_ids: Optional list of specific file IDs to load
                - folder_ids: Optional list of folder IDs to browse/download
                - limit: Maximum number of items to return
                - list_only: If True, return metadata without content
                - recursive: Whether to recursively process folders
                
        Returns:
            List of Document objects
        """
        pass
    
    @abstractmethod
    def download_to_directory(self, local_dir: str, source_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Download files/folders to a local directory.
        
        Args:
            local_dir: Local directory path to download files to
            source_config: Configuration for what to download
            
        Returns:
            Dictionary containing download results:
                - files_downloaded: Number of files downloaded
                - directory_path: Path where files were downloaded
                - empty_result: Whether no files were downloaded
                - source_type: Type of connector
                - config_used: Configuration that was used
                - error: Error message if download failed (optional)
        """
        pass
