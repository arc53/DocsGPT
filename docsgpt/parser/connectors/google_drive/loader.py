"""
Google Drive loader for DocsGPT.
Loads documents from Google Drive using Google Drive API.
"""

import contextlib
import hashlib
import io
import json
import logging
import os
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

from docsgpt.parser.connectors.base import BaseConnectorLoader
from docsgpt.parser.connectors.google_drive.auth import GoogleDriveAuth
from docsgpt.parser.schema.base import Document

_FOLDER_MIME = 'application/vnd.google-apps.folder'
_SHORTCUT_MIME = 'application/vnd.google-apps.shortcut'
# Metadata read for every walked item; shortcutDetails says where a shortcut points.
_ITEM_FIELDS = 'id,name,mimeType,modifiedTime,driveId,shortcutDetails(targetId,targetMimeType)'
# Retries after the first attempt. Google's client retries 5xx, 429, rate-limit
# 403s and dropped connections with exponential backoff and jitter (1s, 2s, 4s...).
_NUM_RETRIES = 5
_RATE_LIMIT_REASONS = {'rateLimitExceeded', 'userRateLimitExceeded'}
# Download refusals that follow from the file's content, which only changes
# with its modifiedTime. Other refusals (sharing, permissions) can lift
# without it changing, so they keep the selection from being fingerprinted.
_CONTENT_REFUSAL_REASONS = {'exportSizeLimitExceeded', 'fileNotDownloadable'}
# Longest file name most filesystems accept, in bytes.
_MAX_NAME_BYTES = 255


class GoogleDriveLoader(BaseConnectorLoader):

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
        'text/markdown': '.md',
        'text/x-rst': '.rst',
        'application/json': '.json',
        'application/epub+zip': '.epub',
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

    def __init__(self, session_token: Optional[str] = None, *, connection_id: Optional[str] = None):
        self.auth = GoogleDriveAuth()
        self.session_token = session_token

        _, token_info = self._load_token_info(session_token, connection_id)
        # Google refresh tokens do not rotate, so the credentials object may
        # renew the access token in memory for the rest of this run.
        self.credentials = self.auth.create_credentials_from_token_info(token_info)

        try:
            self.service = self.auth.build_drive_service(self.credentials)
        except Exception as e:
            logging.warning(f"Could not build Google Drive service: {e}")
            self.service = None

        self.next_page_token = None



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
                'size': file_metadata.get('size', None),
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
            page_token = inputs.get('page_token')
            search_query = inputs.get('search_query')
            self.next_page_token = None

            if file_ids:
                # Specific files requested: load them
                for file_id in file_ids:
                    try:
                        doc = self._load_file_by_id(file_id, load_content=load_content)
                        if doc:
                            if not search_query or (
                                search_query.lower() in doc.extra_info.get('file_name', '').lower()
                            ):
                                documents.append(doc)
                        elif hasattr(self, '_credential_refreshed') and self._credential_refreshed:
                            self._credential_refreshed = False
                            logging.info(f"Retrying load of file {file_id} after credential refresh")
                            doc = self._load_file_by_id(file_id, load_content=load_content)
                            if doc and (
                                not search_query or 
                                search_query.lower() in doc.extra_info.get('file_name', '').lower()
                            ):
                                documents.append(doc)
                    except Exception as e:
                        logging.error(f"Error loading file {file_id}: {e}")
                        continue
            else:
                # Browsing mode: list immediate children of provided folder or root
                parent_id = folder_id if folder_id else 'root'
                # The top level also offers the user's shared drives, as
                # folders listed ahead of My Drive on the first page.
                shared_drives: List[Document] = []
                if not folder_id and not page_token and not search_query:
                    shared_drives = self._list_shared_drives(limit - 1 if limit else 100)
                documents = shared_drives + self._list_items_in_parent(
                    parent_id,
                    limit=limit - len(shared_drives) if limit else limit,
                    load_content=load_content,
                    page_token=page_token,
                    search_query=search_query
                )

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
                fields='id,name,mimeType,size,createdTime,modifiedTime,parents',
                supportsAllDrives=True
            ).execute(num_retries=_NUM_RETRIES)

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


    def _list_items_in_parent(self, parent_id: str, limit: int = 100, load_content: bool = False, page_token: Optional[str] = None, search_query: Optional[str] = None) -> List[Document]:
        self._ensure_service()

        documents: List[Document] = []

        try:
            query = f"'{parent_id}' in parents and trashed=false"

            if search_query:
                safe_search = search_query.replace("'", "\\'")
                query += f" and name contains '{safe_search}'"

            next_token_out: Optional[str] = None
            drive_scope = self._drive_scope(parent_id)

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
                    pageSize=page_size,
                    orderBy='name',
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    **drive_scope
                ).execute(num_retries=_NUM_RETRIES)

                items = results.get('files', [])
                for item in items:
                    mime_type = item.get('mimeType')
                    if mime_type == 'application/vnd.google-apps.folder':
                        doc_metadata = {
                            'file_name': item.get('name', 'Unknown'),
                            'mime_type': mime_type,
                            'size': item.get('size', None),
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
                        self.next_page_token = results.get('nextPageToken')
                        return documents

                page_token = results.get('nextPageToken')
                next_token_out = page_token
                if not page_token:
                    break

            self.next_page_token = next_token_out
            return documents
        except Exception as e:
            logging.error(f"Error listing items under parent {parent_id}: {e}")
            return documents




    def _list_shared_drives(self, limit: int) -> List[Document]:
        """The shared drives the user is a member of, as folders to browse into.

        Args:
            limit: The most drives to return.
        """
        if limit <= 0:
            return []
        try:
            results = self.service.drives().list(
                pageSize=min(100, limit),
                fields='drives(id,name)',
            ).execute(num_retries=_NUM_RETRIES)
        except Exception as e:
            logging.warning(f"Could not list shared drives: {e}")
            return []
        return [
            Document(
                text="",
                doc_id=drive['id'],
                extra_info={
                    'file_name': drive.get('name', 'Unknown'),
                    'mime_type': _FOLDER_MIME,
                    'source': 'google_drive',
                    'is_folder': True,
                    'shared_drive': True,
                },
            )
            for drive in results.get('drives', [])
        ]

    def _drive_scope(self, folder_id: str) -> Dict[str, str]:
        """``files.list`` arguments that list a folder within its shared drive.

        The default corpus only holds files the user owns or was shared
        directly, so a shared drive's folders are listed within that drive.
        Empty for My Drive, or when the folder cannot be read.
        """
        if folder_id == 'root':
            return {}
        try:
            drive_id = self.service.files().get(
                fileId=folder_id,
                fields='driveId',
                supportsAllDrives=True,
            ).execute(num_retries=_NUM_RETRIES).get('driveId')
        except Exception as e:
            logging.warning(f"Could not read folder {folder_id}: {e}")
            return {}
        return {'corpora': 'drive', 'driveId': drive_id} if drive_id else {}

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
                request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)

            file_io = io.BytesIO()
            downloader = MediaIoBaseDownload(file_io, request)

            done = False
            while done is False:
                try:
                    _, done = downloader.next_chunk(num_retries=_NUM_RETRIES)
                except HttpError as e:
                    logging.error(f"HTTP error downloading file {file_id}: {e.resp.status} - {e.content}")
                    return None
                except Exception as e:
                    logging.error(f"Error during download of file {file_id}: {e}")
                    return None

            content_bytes = file_io.getvalue()

            try:
                return content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                logging.error(f"Could not decode file {file_id} as text")
                return None

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

    def _ensure_service(self):
        if not self.service:
            try:
                self.service = self.auth.build_drive_service(self.credentials)
            except Exception as e:
                raise ValueError(f"Cannot access Google Drive: {e}")

    def _get_item(self, item_id: str) -> Dict[str, Any]:
        """Fetch one item's metadata, retrying rate limits and server errors."""
        return self.service.files().get(
            fileId=item_id,
            fields=_ITEM_FIELDS,
            supportsAllDrives=True,
        ).execute(num_retries=_NUM_RETRIES)

    def _list_children(self, folder: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """Yield every untrashed child of ``folder``, page by page.

        Items in a shared drive are listed within that drive (``corpora=drive``);
        the default corpus only holds files the user owns or was shared directly.
        """
        params: Dict[str, Any] = {
            'q': f"'{folder['id']}' in parents and trashed=false",
            'fields': f'nextPageToken,files({_ITEM_FIELDS})',
            'pageSize': 1000,
            'supportsAllDrives': True,
            'includeItemsFromAllDrives': True,
        }
        if folder.get('driveId'):
            params['corpora'] = 'drive'
            params['driveId'] = folder['driveId']
        page_token = None
        while True:
            results = self.service.files().list(
                pageToken=page_token, **params
            ).execute(num_retries=_NUM_RETRIES)
            yield from results.get('files', [])
            page_token = results.get('nextPageToken')
            if not page_token:
                return

    def _resolve_shortcut(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the item a shortcut points to, under the shortcut's own name.

        Items that are not shortcuts come back unchanged. ``None`` when the
        target was deleted or is no longer shared with the user.
        """
        if item.get('mimeType') != _SHORTCUT_MIME:
            return item
        target_id = (item.get('shortcutDetails') or {}).get('targetId')
        if not target_id:
            return None
        try:
            target = self._get_item(target_id)
        except HttpError as e:
            if _is_permanent_error(e):
                logging.info(f"Skipping shortcut {item.get('name')!r}: its target is not available")
                return None
            raise
        return {**target, 'name': item.get('name') or target.get('name')}

    def _walk_selection(
        self, config: Dict[str, Any], stats: '_WalkStats'
    ) -> Iterator[Tuple[Dict[str, Any], Tuple[str, ...]]]:
        """Yield ``(file_metadata, relative_path_parts)`` for every file in a selection.

        Selected folders become top-level directories and their subfolders are
        walked when ``recursive`` is set. Shortcuts are followed; a folder or
        file reached twice (a shortcut to an ancestor, or to a file that is also
        selected) is visited once. Each path part is a sanitized, de-duplicated
        file name, so two items called ``report.pdf`` become ``report.pdf`` and
        ``report_1.pdf`` instead of one overwriting the other.

        An item that cannot be read is logged and counted in ``stats``; the walk
        carries on with the rest.

        Args:
            config: ``file_ids``, ``folder_ids`` (lists or single ids) and ``recursive``.
            stats: Collects counts of failed and skipped items.
        """
        recursive = config.get('recursive', True)
        seen_folders: Set[str] = set()
        seen_files: Set[str] = set()
        taken: Set[Tuple[Tuple[str, ...], str]] = set()

        def visit(item: Dict[str, Any], parent: Tuple[str, ...], top_level: bool):
            try:
                resolved = self._resolve_shortcut(item)
            except Exception as e:
                stats.record_failure(item.get('name') or item.get('id'), e)
                return
            if resolved is None:
                stats.skipped += 1
                return
            item_id = resolved.get('id')
            mime_type = resolved.get('mimeType')
            if mime_type == _FOLDER_MIME:
                if item_id in seen_folders or not (top_level or recursive):
                    return
                seen_folders.add(item_id)
                folder_parts = parent + (_unique_name(taken, parent, _safe_name(resolved.get('name')), is_dir=True),)
                try:
                    children = list(self._list_children(resolved))
                except Exception as e:
                    stats.record_failure(resolved.get('name') or item_id, e)
                    return
                for child in children:
                    yield from visit(child, folder_parts, top_level=False)
                return
            if item_id in seen_files:
                return
            if mime_type not in self.SUPPORTED_MIME_TYPES:
                stats.skipped += 1
                return
            seen_files.add(item_id)
            name = _unique_name(taken, parent, self._local_file_name(resolved), is_dir=False)
            yield resolved, parent + (name,)

        for key in ('file_ids', 'folder_ids'):
            ids = config.get(key) or []
            if isinstance(ids, str):
                ids = [ids]
            for item_id in ids:
                try:
                    item = self._get_item(item_id)
                except Exception as e:
                    stats.record_failure(item_id, e)
                    continue
                yield from visit(item, (), top_level=True)

    def _local_file_name(self, file_metadata: Dict[str, Any]) -> str:
        """The sanitized name a file is saved under, with an extension its parser recognizes."""
        name = _safe_name(file_metadata.get('name'))
        mime_type = file_metadata.get('mimeType')
        if mime_type in self.EXPORT_FORMATS:
            extension = self.SUPPORTED_MIME_TYPES[mime_type]
            if not name.lower().endswith(extension):
                name += extension
        elif not os.path.splitext(name)[1]:
            name += self.SUPPORTED_MIME_TYPES.get(mime_type, '')
        return _fit_name(name)

    def _download_file(self, file_metadata: Dict[str, Any], path: str) -> None:
        """Download (or export, for Google Docs, Sheets and Slides) one file to ``path``.

        A partly written file is removed when the download fails.
        """
        file_id = file_metadata['id']
        mime_type = file_metadata['mimeType']
        if mime_type in self.EXPORT_FORMATS:
            request = self.service.files().export_media(
                fileId=file_id,
                mimeType=self.EXPORT_FORMATS[mime_type]
            )
        else:
            request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)

        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, 'wb') as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk(num_retries=_NUM_RETRIES)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(path)
            raise

    def sync_fingerprint(self, source_config: Dict[str, Any]) -> Optional[str]:
        """Fingerprint the selection from file metadata alone, without downloading.

        Changes when a file is added, removed, renamed, moved or modified.
        ``None`` when part of the selection could not be read, since the
        fingerprint would then not describe all of it.
        """
        self._ensure_service()
        stats = _WalkStats()
        entries = [
            (parts, meta.get('id'), meta.get('modifiedTime'))
            for meta, parts in self._walk_selection(source_config, stats)
        ]
        return None if stats.failed else _fingerprint(entries)

    def download_to_directory(self, local_dir: str, source_config: dict = None) -> dict:
        """Download the selected files and folders into ``local_dir``.

        Each file is downloaded on its own: one that fails (an export over
        Google's size limit, a file type Google cannot download) is logged and
        counted, and the rest still arrive.

        Args:
            local_dir: Directory to write into; nothing is written outside it.
            source_config: ``file_ids``, ``folder_ids`` and ``recursive``.

        Returns:
            The download summary: ``files_downloaded``, ``files_failed``,
            ``files_skipped``, ``sync_fingerprint``, ``directory_path``,
            ``empty_result``, ``source_type`` and ``config_used``, plus
            ``error`` when the download could not run. ``sync_fingerprint``
            is ``None`` when a file or folder failed, or a file was refused
            for a reason other than its content (sharing, permissions), since
            that can change without the file's ``modifiedTime`` changing.
        """
        if source_config is None:
            source_config = {}

        config = source_config if source_config else getattr(self, 'config', {})
        stats = _WalkStats()
        files_downloaded = 0
        entries = []
        fingerprintable = True

        try:
            if not config.get('file_ids') and not config.get('folder_ids'):
                raise ValueError("No folder_ids or file_ids provided for download")

            self._ensure_service()
            os.makedirs(local_dir, exist_ok=True)

            for file_metadata, parts in self._walk_selection(config, stats):
                entries.append((parts, file_metadata.get('id'), file_metadata.get('modifiedTime')))
                try:
                    self._download_file(file_metadata, _safe_join(local_dir, parts))
                    files_downloaded += 1
                except Exception as e:
                    stats.record_failure(file_metadata.get('name'), e)
                    if not _error_reasons(e) & _CONTENT_REFUSAL_REASONS:
                        fingerprintable = False

            return {
                "files_downloaded": files_downloaded,
                "files_failed": stats.failed,
                "files_skipped": stats.skipped,
                "sync_fingerprint": _fingerprint(entries) if fingerprintable and not stats.failed else None,
                "directory_path": local_dir,
                "empty_result": files_downloaded == 0,
                "source_type": "google_drive",
                "config_used": config
            }

        except Exception as e:
            return {
                "files_downloaded": files_downloaded,
                "files_failed": stats.failed,
                "files_skipped": stats.skipped,
                "sync_fingerprint": None,
                "directory_path": local_dir,
                "empty_result": True,
                "source_type": "google_drive",
                "config_used": config,
                "error": str(e)
            }


class _WalkStats:
    """Counts the items a walk could not read (``failed``) or left out on purpose (``skipped``).

    Refusals that retrying would not change (a deleted item, an unreadable
    folder, an export over Google's size limit) count as skipped and do not
    block the sync fingerprint on their own. An item the walk could not read
    is absent from the fingerprint, and every sync walks again, so its files
    change the fingerprint once it can be read. A refused *download* is
    different, since the fingerprint walk never downloads: ``download_to_directory``
    withholds the fingerprint unless the refusal is about the file's content.
    """

    def __init__(self) -> None:
        self.failed = 0
        self.skipped = 0

    def record_failure(self, name: Any, error: Exception) -> None:
        if _is_permanent_error(error):
            self.skipped += 1
            logging.info(f"Skipping Google Drive item {name!r}: {error}")
        else:
            self.failed += 1
            logging.warning(f"Could not download Google Drive item {name!r}: {error}")


def _is_permanent_error(error: Exception) -> bool:
    """Whether Google refused for good, rather than for now (rate limit, outage, expired sign-in)."""
    if not isinstance(error, HttpError):
        return False
    status = error.resp.status
    if status in (401, 429) or status >= 500:
        return False
    return not _error_reasons(error) & _RATE_LIMIT_REASONS


def _error_reasons(error: Exception) -> Set[str]:
    """The ``reason`` codes of a Drive API error (``exportSizeLimitExceeded``...); empty for other errors."""
    details = getattr(error, 'error_details', None)
    if not isinstance(error, HttpError) or not isinstance(details, list):
        return set()
    return {d.get('reason') for d in details if isinstance(d, dict) and d.get('reason')}


def _safe_name(name: Optional[str]) -> str:
    """A Drive name made safe as one path part: no separators, no ``.``/``..``, no NUL."""
    cleaned = (name or '').replace('\x00', '').replace('/', '_').replace('\\', '_').strip()
    return '_' if cleaned in ('', '.', '..') else cleaned


def _fit_name(name: str, suffix: str = '', is_dir: bool = False) -> str:
    """``name`` with ``suffix`` added before its extension, cut to the filesystem's name limit."""
    stem, extension = (name, '') if is_dir else os.path.splitext(name)
    if len(extension.encode('utf-8')) > 32:
        stem, extension = name, ''
    budget = _MAX_NAME_BYTES - len(suffix.encode('utf-8')) - len(extension.encode('utf-8'))
    stem = stem.encode('utf-8')[:budget].decode('utf-8', 'ignore') or '_'
    return f"{stem}{suffix}{extension}"


def _unique_name(
    taken: Set[Tuple[Tuple[str, ...], str]], parent: Tuple[str, ...], name: str, is_dir: bool
) -> str:
    """Claim ``name`` in ``parent``, numbering it ``name_1``, ``name_2``... when already used.

    Names compare case-insensitively, so they stay distinct on a
    case-insensitive filesystem too.
    """
    candidate = _fit_name(name, is_dir=is_dir)
    counter = 0
    while (parent, candidate.casefold()) in taken:
        counter += 1
        candidate = _fit_name(name, f'_{counter}', is_dir=is_dir)
    taken.add((parent, candidate.casefold()))
    return candidate


def _safe_join(root: str, parts: Tuple[str, ...]) -> str:
    """Join ``parts`` under ``root``, refusing any path that would land outside it."""
    root_real = os.path.realpath(root)
    path = os.path.realpath(os.path.join(root_real, *parts))
    if os.path.commonpath([root_real, path]) != root_real or path == root_real:
        raise ValueError(f"Refusing to write outside the download directory: {parts!r}")
    return path


def _fingerprint(entries: List[Tuple[Tuple[str, ...], Optional[str], Optional[str]]]) -> str:
    """A stable hash of ``(path, id, modifiedTime)`` for every file in a selection."""
    payload = json.dumps(sorted([list(parts), file_id, modified] for parts, file_id, modified in entries))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
