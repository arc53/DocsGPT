from typing import List, Dict, Any
from application.parser.connectors.base import BaseConnectorLoader
from application.parser.schema.base import Document


class SharePointLoader(BaseConnectorLoader):
    def __init__(self, session_token: str):
        pass

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
