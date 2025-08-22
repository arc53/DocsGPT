"""
Google Drive loader for DocsGPT.
Loads documents from Google Drive using Google Drive API.
"""

import io
import logging
import os
from typing import List, Dict, Any, Optional

from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

from application.parser.remote.base import BaseRemote
from application.parser.remote.google_auth import GoogleDriveAuth
from application.parser.schema.base import Document


class GoogleDriveLoader(BaseRemote):

    SUPPORTED_MIME_TYPES = {
        'application/pdf': '.pdf',
        'application/vnd.google-apps.document': '.docx',
        'application/vnd.google-apps.presentation': '.pptx',
        'application/vnd.google-apps.spreadsheet': '.xlsx',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
        'application/msword': '.doc',
        'application/vnd.ms-powerpoint': '.ppt',
        'application/vnd.ms-excel': '.xls',
        'text/plain': '.txt',
        'text/csv': '.csv',
        'text/html': '.html',
        'application/rtf': '.rtf',
        'image/jpeg': '.jpg',
        'image/jpg': '.jpg',
        'image/png': '.png',
    }

    EXPORT_FORMATS = {
        'application/vnd.google-apps.document': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.google-apps.presentation': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'application/vnd.google-apps.spreadsheet': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    }

    def __init__(self, session_token: str):
        self.auth = GoogleDriveAuth()
        self.session_token = session_token

        token_info = self.auth.get_token_info_from_session(session_token)
        self.credentials = self.auth.create_credentials_from_token_info(token_info)

        try:
            self.service = self.auth.build_drive_service(self.credentials)
        except Exception as e:
            logging.warning(f"Could not build Google Drive service: {e}")
            self.service = None



    def _process_file(self, file_metadata: Dict[str, Any], load_content: bool = True) -> Optional[Document]:
        try:
            file_id = file_metadata.get('id')
            file_name = file_metadata.get('name', 'Unknown')
            mime_type = file_metadata.get('mimeType', 'application/octet-stream')

            if mime_type not in self.SUPPORTED_MIME_TYPES and not mime_type.startswith('application/vnd.google-apps.'):
                return None
            if mime_type not in self.SUPPORTED_MIME_TYPES and not mime_type.startswith('application/vnd.google-apps.'):
                logging.info(f"Skipping unsupported file type: {mime_type} for file {file_name}")
                return None
            # Google Drive provides timezone-aware ISO8601 dates
            doc_metadata = {
                'file_name': file_name,
                'mime_type': mime_type,
                'size': file_metadata.get('size', 'Unknown'),
                'created_time': file_metadata.get('createdTime'),
                'modified_time': file_metadata.get('modifiedTime'),
                'parents': file_metadata.get('parents', []),
                'source': 'google_drive'
            }

            if not load_content:
                return Document(
                    text="",
                    doc_id=file_id,
                    extra_info=doc_metadata
                )

            content = self._download_file_content(file_id, mime_type)
            if content is None:
                logging.warning(f"Could not load content for file {file_name} ({file_id})")
                return None

            return Document(
                text=content,
                doc_id=file_id,
                extra_info=doc_metadata
            )

        except Exception as e:
            logging.error(f"Error processing file: {e}")
            return None

    def load_data(self, inputs: Dict[str, Any]) -> List[Document]:
        """
        Load items from Google Drive according to simple browsing semantics.

        Behavior:
        - If file_ids are provided: return those files (optionally with content).
        - If folder_id is provided: return the immediate children (folders and files) of that folder.
        - If no folder_id: return the immediate children (folders and files) of Drive 'root'.

        Args:
            inputs: Dictionary containing configuration:
                - folder_id: Optional Google Drive folder ID whose direct children to list
                - file_ids: Optional list of specific file IDs to load
                - limit: Maximum number of items to return
                - list_only: If True, only return metadata without content
                - session_token: Optional session token to use for authentication (backward compatibility)

        Returns:
            List of Document objects (folders are returned as metadata-only documents)
        """
        session_token = inputs.get('session_token')
        if session_token and session_token != self.session_token:
            logging.warning("Session token in inputs differs from loader's session token. Using loader's session token.")
        self.config = inputs

        try:
            documents: List[Document] = []

            folder_id = inputs.get('folder_id')
            file_ids = inputs.get('file_ids', [])
            limit = inputs.get('limit', 100)
            list_only = inputs.get('list_only', False)
            load_content = not list_only

            if file_ids:
                # Specific files requested: load them
                for file_id in file_ids:
                    try:
                        doc = self._load_file_by_id(file_id, load_content=load_content)
                        if doc:
                            documents.append(doc)
                        elif hasattr(self, '_credential_refreshed') and self._credential_refreshed:
                            self._credential_refreshed = False
                            logging.info(f"Retrying load of file {file_id} after credential refresh")
                            doc = self._load_file_by_id(file_id, load_content=load_content)
                            if doc:
                                documents.append(doc)
                    except Exception as e:
                        logging.error(f"Error loading file {file_id}: {e}")
                        continue
            else:
                # Browsing mode: list immediate children of provided folder or root
                parent_id = folder_id if folder_id else 'root'
                documents = self._list_items_in_parent(parent_id, limit=limit, load_content=load_content)

            logging.info(f"Loaded {len(documents)} documents from Google Drive")
            return documents

        except Exception as e:
            logging.error(f"Error loading data from Google Drive: {e}", exc_info=True)
            raise

    def _load_file_by_id(self, file_id: str, load_content: bool = True) -> Optional[Document]:
        self._ensure_service()

        try:
            file_metadata = self.service.files().get(
                fileId=file_id,
                fields='id,name,mimeType,size,createdTime,modifiedTime,parents'
            ).execute()

            return self._process_file(file_metadata, load_content=load_content)

        except HttpError as e:
            logging.error(f"HTTP error loading file {file_id}: {e.resp.status} - {e.content}")

            if e.resp.status in [401, 403]:
                if hasattr(self.credentials, 'refresh_token') and self.credentials.refresh_token:
                    try:
                        from google.auth.transport.requests import Request
                        self.credentials.refresh(Request())
                        self._ensure_service()
                        return None
                    except Exception as refresh_error:
                        raise ValueError(f"Authentication failed and could not be refreshed: {refresh_error}")
                else:
                    raise ValueError("Authentication failed and cannot be refreshed: missing refresh_token")

            return None
        except Exception as e:
            logging.error(f"Error loading file {file_id}: {e}")
            return None


    def _list_items_in_parent(self, parent_id: str, limit: int = 100, load_content: bool = False) -> List[Document]:
        self._ensure_service()

        documents: List[Document] = []

        try:
            query = f"'{parent_id}' in parents and trashed=false"
            page_token = None

            while True:
                page_size = 100
                if limit:
                    remaining = max(0, limit - len(documents))
                    if remaining == 0:
                        break
                    page_size = min(100, remaining)

                results = self.service.files().list(
                    q=query,
                    fields='nextPageToken,files(id,name,mimeType,size,createdTime,modifiedTime,parents)',
                    pageToken=page_token,
                    pageSize=page_size
                ).execute()

                items = results.get('files', [])
                for item in items:
                    mime_type = item.get('mimeType')
                    if mime_type == 'application/vnd.google-apps.folder':
                        doc_metadata = {
                            'file_name': item.get('name', 'Unknown'),
                            'mime_type': mime_type,
                            'size': item.get('size', 'Unknown'),
                            'created_time': item.get('createdTime'),
                            'modified_time': item.get('modifiedTime'),
                            'parents': item.get('parents', []),
                            'source': 'google_drive',
                            'is_folder': True
                        }
                        documents.append(Document(text="", doc_id=item.get('id'), extra_info=doc_metadata))
                    else:
                        doc = self._process_file(item, load_content=load_content)
                        if doc:
                            documents.append(doc)

                    if limit and len(documents) >= limit:
                        return documents

                page_token = results.get('nextPageToken')
                if not page_token:
                    break

            return documents
        except Exception as e:
            logging.error(f"Error listing items under parent {parent_id}: {e}")
            return documents




    def _download_file_content(self, file_id: str, mime_type: str) -> Optional[str]:
        if not self.credentials.token:
            logging.warning("No access token in credentials, attempting to refresh")
            if hasattr(self.credentials, 'refresh_token') and self.credentials.refresh_token:
                try:
                    from google.auth.transport.requests import Request
                    self.credentials.refresh(Request())
                    logging.info("Credentials refreshed successfully")
                    self._ensure_service()
                except Exception as e:
                    logging.error(f"Failed to refresh credentials: {e}")
                    raise ValueError("Authentication failed and cannot be refreshed: missing or invalid refresh_token")
            else:
                logging.error("No access token and no refresh_token available")
                raise ValueError("Authentication failed and cannot be refreshed: missing refresh_token")

        if self.credentials.expired:
            logging.warning("Credentials are expired, attempting to refresh")
            if hasattr(self.credentials, 'refresh_token') and self.credentials.refresh_token:
                try:
                    from google.auth.transport.requests import Request
                    self.credentials.refresh(Request())
                    logging.info("Credentials refreshed successfully")
                    self._ensure_service()
                except Exception as e:
                    logging.error(f"Failed to refresh expired credentials: {e}")
                    raise ValueError("Authentication failed and cannot be refreshed: expired credentials")
            else:
                logging.error("Credentials expired and no refresh_token available")
                raise ValueError("Authentication failed and cannot be refreshed: missing refresh_token")

        try:
            if mime_type in self.EXPORT_FORMATS:
                export_mime_type = self.EXPORT_FORMATS[mime_type]
                request = self.service.files().export_media(
                    fileId=file_id,
                    mimeType=export_mime_type
                )
            else:
                request = self.service.files().get_media(fileId=file_id)

            file_io = io.BytesIO()
            downloader = MediaIoBaseDownload(file_io, request)

            done = False
            while done is False:
                try:
                    _, done = downloader.next_chunk()
                except HttpError as e:
                    logging.error(f"HTTP error downloading file {file_id}: {e.resp.status} - {e.content}")
                    return None
                except Exception as e:
                    logging.error(f"Error during download of file {file_id}: {e}")
                    return None

            content_bytes = file_io.getvalue()

            try:
                content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    content = content_bytes.decode('latin-1')
                except UnicodeDecodeError:
                    logging.error(f"Could not decode file {file_id} as text")
                    return None

            return content

        except HttpError as e:
            logging.error(f"HTTP error downloading file {file_id}: {e.resp.status} - {e.content}")

            if e.resp.status in [401, 403]:
                logging.error(f"Authentication error downloading file {file_id}")
              
                if hasattr(self.credentials, 'refresh_token') and self.credentials.refresh_token:
                    logging.info(f"Attempting to refresh credentials for file {file_id}")
                    try:
                        from google.auth.transport.requests import Request
                        self.credentials.refresh(Request())
                        logging.info("Credentials refreshed successfully")
                        self._credential_refreshed = True
                        self._ensure_service()
                        return None
                    except Exception as refresh_error:
                        logging.error(f"Error refreshing credentials: {refresh_error}")
                        raise ValueError(f"Authentication failed and could not be refreshed: {refresh_error}")
                else:
                    logging.error("Cannot refresh credentials: missing refresh_token")
                    raise ValueError("Authentication failed and cannot be refreshed: missing refresh_token")

            return None
        except Exception as e:
            logging.error(f"Error downloading file {file_id}: {e}")
            return None


    def _download_file_to_directory(self, file_id: str, local_dir: str) -> bool:
        try:
            self._ensure_service()
            return self._download_single_file(file_id, local_dir)
        except Exception as e:
            logging.error(f"Error downloading file {file_id}: {e}", exc_info=True)
            return False

    def _ensure_service(self):
        if not self.service:
            try:
                self.service = self.auth.build_drive_service(self.credentials)
            except Exception as e:
                raise ValueError(f"Cannot access Google Drive: {e}")

    def _download_single_file(self, file_id: str, local_dir: str) -> bool:
        file_metadata = self.service.files().get(
            fileId=file_id,
            fields='name,mimeType'
        ).execute()

        file_name = file_metadata['name']
        mime_type = file_metadata['mimeType']

        if mime_type not in self.SUPPORTED_MIME_TYPES and not mime_type.startswith('application/vnd.google-apps.'):
            return False

        os.makedirs(local_dir, exist_ok=True)
        full_path = os.path.join(local_dir, file_name)

        if mime_type in self.EXPORT_FORMATS:
            export_mime_type = self.EXPORT_FORMATS[mime_type]
            request = self.service.files().export_media(
                fileId=file_id,
                mimeType=export_mime_type
            )
            extension = self._get_extension_for_mime_type(export_mime_type)
            if not full_path.endswith(extension):
                full_path += extension
        else:
            request = self.service.files().get_media(fileId=file_id)

        with open(full_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        return True

    def _download_folder_recursive(self, folder_id: str, local_dir: str, recursive: bool = True) -> int:
        files_downloaded = 0
        query = f"'{folder_id}' in parents and trashed=false"

        page_token = None
        while True:
            results = self.service.files().list(
                q=query,
                fields='nextPageToken,files(id,name,mimeType)',
                pageToken=page_token
            ).execute()

            files = results.get('files', [])

            for file_metadata in files:
                if file_metadata['mimeType'] == 'application/vnd.google-apps.folder':
                    if recursive:
                        subfolder_path = os.path.join(local_dir, file_metadata['name'])
                        os.makedirs(subfolder_path, exist_ok=True)
                        files_downloaded += self._download_folder_recursive(
                            file_metadata['id'],
                            subfolder_path,
                            recursive
                        )
                else:
                    if self._download_single_file(file_metadata['id'], local_dir):
                        files_downloaded += 1

            page_token = results.get('nextPageToken')
            if not page_token:
                break

        return files_downloaded

    def _get_extension_for_mime_type(self, mime_type: str) -> str:
        extensions = {
            'application/pdf': '.pdf',
            'text/plain': '.txt',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
            'text/html': '.html',
            'text/markdown': '.md',
        }
        return extensions.get(mime_type, '.bin')

    def _download_folder_contents(self, folder_id: str, local_dir: str, recursive: bool = True) -> int:
        try:
            self._ensure_service()
            return self._download_folder_recursive(folder_id, local_dir, recursive)
        except Exception as e:
            logging.error(f"Error downloading folder {folder_id}: {e}", exc_info=True)
            return 0

    def download_to_directory(self, local_dir: str, source_config: dict = None) -> dict:
        if source_config is None:
            source_config = {}

        config = source_config if source_config else getattr(self, 'config', {})

        files_downloaded = 0

        try:
            folder_id = config.get('folder_id')
            file_ids = config.get('file_ids', [])
            recursive = config.get('recursive', True)

            if file_ids:
                if isinstance(file_ids, str):
                    file_ids = [file_ids]

                for file_id in file_ids:
                    if self._download_file_to_directory(file_id, local_dir):
                        files_downloaded += 1

            elif folder_id:
                files_downloaded = self._download_folder_contents(folder_id, local_dir, recursive)

            else:
                raise ValueError("No folder_id or file_ids provided for download")

            return {
                "files_downloaded": files_downloaded,
                "directory_path": local_dir,
                "empty_result": files_downloaded == 0,
                "source_type": "google_drive",
                "config_used": config
            }

        except Exception as e:
            return {
                "files_downloaded": 0,
                "directory_path": local_dir,
                "empty_result": True,
                "error": str(e),
                "source_type": "google_drive"
            }
