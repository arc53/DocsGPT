"""
SharePoint/OneDrive loader for DocsGPT.
Loads documents from SharePoint/OneDrive using Microsoft Graph API.
"""

import logging
import os
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import quote

import requests

from application.parser.connectors.base import BaseConnectorLoader
from application.parser.connectors.share_point.auth import SharePointAuth
from application.parser.schema.base import Document


class SharePointLoader(BaseConnectorLoader):

    SUPPORTED_MIME_TYPES = {
        'application/pdf': '.pdf',
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
        'image/png': '.png',
    }

    EXTENSION_TO_MIME = {v: k for k, v in SUPPORTED_MIME_TYPES.items()}

    GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, session_token: str):
        self.auth = SharePointAuth()
        self.session_token = session_token

        token_info = self.auth.get_token_info_from_session(session_token)
        self.access_token = token_info.get('access_token')
        self.refresh_token = token_info.get('refresh_token')
        self.allows_shared_content = token_info.get('allows_shared_content', False)

        if not self.access_token:
            raise ValueError("No access token found in session")

        self.next_page_token = None

    def _get_headers(self) -> Dict[str, str]:
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }

    def _ensure_valid_token(self):
        if not self.access_token:
            raise ValueError("No access token available")

        token_info = {'access_token': self.access_token, 'expiry': None}
        if self.auth.is_token_expired(token_info):
            logging.info("Token expired, attempting refresh")
            try:
                new_token_info = self.auth.refresh_access_token(self.refresh_token)
                self.access_token = new_token_info.get('access_token')
            except Exception:
                raise ValueError("Failed to refresh access token")

    def _get_item_url(self, item_ref: str) -> str:
        if ':' in item_ref:
            drive_id, item_id = item_ref.split(':', 1)
            return f"{self.GRAPH_API_BASE}/drives/{drive_id}/items/{item_id}"
        return f"{self.GRAPH_API_BASE}/me/drive/items/{item_ref}"

    def _process_file(self, file_metadata: Dict[str, Any], load_content: bool = True) -> Optional[Document]:
        try:
            drive_item_id = file_metadata.get('id')
            file_name = file_metadata.get('name', 'Unknown')
            file_data = file_metadata.get('file', {})
            mime_type = file_data.get('mimeType', 'application/octet-stream')

            if mime_type not in self.SUPPORTED_MIME_TYPES:
                logging.info(f"Skipping unsupported file type: {mime_type} for file {file_name}")
                return None

            doc_metadata = {
                'file_name': file_name,
                'mime_type': mime_type,
                'size': file_metadata.get('size'),
                'created_time': file_metadata.get('createdDateTime'),
                'modified_time': file_metadata.get('lastModifiedDateTime'),
                'source': 'share_point'
            }

            if not load_content:
                return Document(
                    text="",
                    doc_id=drive_item_id,
                    extra_info=doc_metadata
                )

            content = self._download_file_content(drive_item_id)
            if content is None:
                logging.warning(f"Could not load content for file {file_name} ({drive_item_id})")
                return None

            return Document(
                text=content,
                doc_id=drive_item_id,
                extra_info=doc_metadata
            )

        except Exception as e:
            logging.error(f"Error processing file: {e}")
            return None

    def load_data(self, inputs: Dict[str, Any]) -> List[Document]:
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

            shared = inputs.get('shared', False)

            if file_ids:
                for file_id in file_ids:
                    try:
                        doc = self._load_file_by_id(file_id, load_content=load_content)
                        if doc:
                            if not search_query or (
                                search_query.lower() in doc.extra_info.get('file_name', '').lower()
                            ):
                                documents.append(doc)
                    except Exception as e:
                        logging.error(f"Error loading file {file_id}: {e}")
                        continue
            elif shared:
                if not self.allows_shared_content:
                    logging.warning("Shared content is only available for work/school Microsoft accounts")
                    return []
                documents = self._list_shared_items(
                    limit=limit,
                    load_content=load_content,
                    page_token=page_token,
                    search_query=search_query
                )
            else:
                parent_id = folder_id if folder_id else 'root'
                documents = self._list_items_in_parent(
                    parent_id,
                    limit=limit,
                    load_content=load_content,
                    page_token=page_token,
                    search_query=search_query
                )

            logging.info(f"Loaded {len(documents)} documents from SharePoint/OneDrive")
            return documents

        except Exception as e:
            logging.error(f"Error loading data from SharePoint/OneDrive: {e}", exc_info=True)
            raise

    def _load_file_by_id(self, file_id: str, load_content: bool = True) -> Optional[Document]:
        self._ensure_valid_token()

        try:
            url = self._get_item_url(file_id)
            params = {'$select': 'id,name,file,createdDateTime,lastModifiedDateTime,size'}
            response = requests.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()

            file_metadata = response.json()
            return self._process_file(file_metadata, load_content=load_content)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code in [401, 403]:
                logging.error(f"Authentication error loading file {file_id}")
                try:
                    new_token_info = self.auth.refresh_access_token(self.refresh_token)
                    self.access_token = new_token_info.get('access_token')
                    response = requests.get(url, headers=self._get_headers(), params=params)
                    response.raise_for_status()
                    file_metadata = response.json()
                    return self._process_file(file_metadata, load_content=load_content)
                except Exception as refresh_error:
                    raise ValueError(f"Authentication failed and could not be refreshed: {refresh_error}")
            logging.error(f"HTTP error loading file {file_id}: {e}")
            return None
        except Exception as e:
            logging.error(f"Error loading file {file_id}: {e}")
            return None

    def _list_items_in_parent(self, parent_id: str, limit: int = 100, load_content: bool = False, page_token: Optional[str] = None, search_query: Optional[str] = None) -> List[Document]:
        self._ensure_valid_token()

        documents: List[Document] = []

        try:
            url = f"{self._get_item_url(parent_id)}/children"
            params = {'$top': min(100, limit) if limit else 100, '$select': 'id,name,file,folder,createdDateTime,lastModifiedDateTime,size'}
            if page_token:
                params['$skipToken'] = page_token

            if search_query:
                encoded_query = quote(search_query, safe='')
                if ':' in parent_id:
                    drive_id = parent_id.split(':', 1)[0]
                    search_url = f"{self.GRAPH_API_BASE}/drives/{drive_id}/root/search(q='{encoded_query}')"
                else:
                    search_url = f"{self.GRAPH_API_BASE}/me/drive/search(q='{encoded_query}')"
                response = requests.get(search_url, headers=self._get_headers(), params=params)
            else:
                response = requests.get(url, headers=self._get_headers(), params=params)

            response.raise_for_status()

            results = response.json()

            items = results.get('value', [])
            for item in items:
                if 'folder' in item:
                    doc_metadata = {
                        'file_name': item.get('name', 'Unknown'),
                        'mime_type': 'folder',
                        'size': item.get('size'),
                        'created_time': item.get('createdDateTime'),
                        'modified_time': item.get('lastModifiedDateTime'),
                        'source': 'share_point',
                        'is_folder': True
                    }
                    documents.append(Document(text="", doc_id=item.get('id'), extra_info=doc_metadata))
                else:
                    doc = self._process_file(item, load_content=load_content)
                    if doc:
                        documents.append(doc)

                if limit and len(documents) >= limit:
                    break

            next_link = results.get('@odata.nextLink')
            if next_link:
                # Extract skiptoken from the full URL
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(next_link)
                query_params = parse_qs(parsed.query)
                skiptoken_list = query_params.get('$skiptoken')
                if skiptoken_list:
                    self.next_page_token = skiptoken_list[0]
                else:
                    self.next_page_token = None
            else:
                self.next_page_token = None
            return documents

        except Exception as e:
            logging.error(f"Error listing items under parent {parent_id}: {e}")
            return documents




    def _resolve_mime_type(self, resource: Dict[str, Any]) -> Tuple[str, bool]:
        """Resolve mime type from resource, falling back to file extension."""
        file_data = resource.get('file', {})
        mime_type = file_data.get('mimeType') if file_data else None

        if mime_type and mime_type in self.SUPPORTED_MIME_TYPES:
            return mime_type, True

        name = resource.get('name', '')
        ext = os.path.splitext(name)[1].lower()
        if ext in self.EXTENSION_TO_MIME:
            return self.EXTENSION_TO_MIME[ext], True

        return mime_type or 'application/octet-stream', False

    def _get_user_drive_web_url(self) -> Optional[str]:
        """Fetch the current user's OneDrive web URL for KQL path exclusion."""
        try:
            response = requests.get(
                f"{self.GRAPH_API_BASE}/me/drive",
                headers=self._get_headers(),
                params={'$select': 'webUrl'}
            )
            response.raise_for_status()
            return response.json().get('webUrl')
        except Exception as e:
            logging.warning(f"Could not fetch user drive web URL: {e}")
            return None

    def _build_shared_kql_query(self, search_query: Optional[str], user_drive_url: Optional[str]) -> str:
        """Build KQL query string that excludes the user's own drive items."""
        base_query = search_query if search_query else "*"
        if user_drive_url:
            return f'{base_query} AND -path:"{user_drive_url}"'
        return base_query

    def _list_shared_items(self, limit: int = 100, load_content: bool = False, page_token: Optional[str] = None, search_query: Optional[str] = None) -> List[Document]:
        """Fetch shared drive items using Microsoft Graph Search API with local offset paging.

        We always fetch up to a fixed maximum number of hits from Graph (single request),
        then page through that array locally using `page_token` as a simple integer offset.
        This avoids relying on buggy or inconsistent remote `from`/`size` semantics.
        """
        self._ensure_valid_token()
        documents: List[Document] = []

        try:
            user_drive_url = self._get_user_drive_web_url()
            query_text = self._build_shared_kql_query(search_query, user_drive_url)

            url = f"{self.GRAPH_API_BASE}/search/query"
            page_size = 500  # maximum number of hits we care about for selection

            body = {
                "requests": [
                    {
                        "entityTypes": ["driveItem"],
                        "query": {"queryString": query_text},
                        "from": 0,
                        "size": page_size,
                    }
                ]
            }

            headers = self._get_headers()
            headers["Content-Type"] = "application/json"
            response = requests.post(url, headers=headers, json=body)
            response.raise_for_status()
            results = response.json()

            search_response = results.get("value", [])
            if not search_response:
                logging.warning("Search API returned empty value array")
                self.next_page_token = None
                return documents

            hits_containers = search_response[0].get("hitsContainers", [])
            if not hits_containers:
                logging.warning("Search API returned no hitsContainers")
                self.next_page_token = None
                return documents

            container = hits_containers[0]
            total = container.get("total", 0)
            raw_hits = container.get("hits", [])

            # Deduplicate by effective item ID (driveId:itemId) to avoid the same
            # resource appearing multiple times across the result set.
            deduped_hits = []
            seen_ids = set()
            for hit in raw_hits:
                resource = hit.get("resource", {})
                item_id = resource.get("id")
                drive_id = resource.get("parentReference", {}).get("driveId")
                effective_id = f"{drive_id}:{item_id}" if drive_id and item_id else item_id
                if not effective_id or effective_id in seen_ids:
                    continue
                seen_ids.add(effective_id)
                deduped_hits.append(hit)

            hits = deduped_hits
            logging.info(
                f"Search API returned {total} total results, {len(raw_hits)} raw hits, {len(hits)} unique hits in this batch"
            )
            try:
                offset = int(page_token) if page_token is not None else 0
            except (TypeError, ValueError):
                logging.warning(
                    f"Invalid page_token '{page_token}' for shared items search, defaulting to 0"
                )
                offset = 0

            if offset < 0:
                offset = 0
            if offset >= len(hits):
                self.next_page_token = None
                return documents

            end_index = offset + limit if limit else len(hits)
            end_index = min(end_index, len(hits))

            for hit in hits[offset:end_index]:
                resource = hit.get("resource", {})
                item_name = resource.get("name", "Unknown")
                item_id = resource.get("id")
                drive_id = resource.get("parentReference", {}).get("driveId")

                effective_id = f"{drive_id}:{item_id}" if drive_id and item_id else item_id

                is_folder = "folder" in resource

                if is_folder:
                    doc_metadata = {
                        "file_name": item_name,
                        "mime_type": "folder",
                        "size": resource.get("size"),
                        "created_time": resource.get("createdDateTime"),
                        "modified_time": resource.get("lastModifiedDateTime"),
                        "source": "share_point",
                        "is_folder": True,
                    }
                    documents.append(
                        Document(text="", doc_id=effective_id, extra_info=doc_metadata)
                    )
                else:
                    mime_type, supported = self._resolve_mime_type(resource)
                    if not supported:
                        logging.info(
                            f"Skipping unsupported shared file: {item_name} (mime: {mime_type})"
                        )
                        continue

                    doc_metadata = {
                        "file_name": item_name,
                        "mime_type": mime_type,
                        "size": resource.get("size"),
                        "created_time": resource.get("createdDateTime"),
                        "modified_time": resource.get("lastModifiedDateTime"),
                        "source": "share_point",
                    }

                    content = ""
                    if load_content:
                        content = self._download_file_content(effective_id) or ""

                    documents.append(
                        Document(text=content, doc_id=effective_id, extra_info=doc_metadata)
                    )

            if limit and end_index < len(hits):
                self.next_page_token = str(end_index)
            else:
                self.next_page_token = None

            return documents

        except Exception as e:
            logging.error(f"Error listing shared items via search API: {e}", exc_info=True)
            return documents

    def _download_file_content(self, file_id: str) -> Optional[str]:
        self._ensure_valid_token()

        try:
            url = f"{self._get_item_url(file_id)}/content"
            response = requests.get(url, headers=self._get_headers())
            response.raise_for_status()

            try:
                return response.content.decode('utf-8')
            except UnicodeDecodeError:
                logging.error(f"Could not decode file {file_id} as text")
                return None

        except requests.exceptions.HTTPError as e:
            if e.response.status_code in [401, 403]:
                logging.error(f"Authentication error downloading file {file_id}")
                try:
                    new_token_info = self.auth.refresh_access_token(self.refresh_token)
                    self.access_token = new_token_info.get('access_token')
                    response = requests.get(url, headers=self._get_headers())
                    response.raise_for_status()
                    try:
                        return response.content.decode('utf-8')
                    except UnicodeDecodeError:
                        logging.error(f"Could not decode file {file_id} as text")
                        return None
                except Exception as refresh_error:
                    raise ValueError(f"Authentication failed and could not be refreshed: {refresh_error}")
            logging.error(f"HTTP error downloading file {file_id}: {e}")
            return None
        except Exception as e:
            logging.error(f"Error downloading file {file_id}: {e}")
            return None

    def _download_single_file(self, file_id: str, local_dir: str) -> bool:
        try:
            url = self._get_item_url(file_id)
            params = {'$select': 'id,name,file'}
            response = requests.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()

            metadata = response.json()
            file_name = metadata.get('name', 'unknown')
            file_data = metadata.get('file', {})
            mime_type = file_data.get('mimeType', 'application/octet-stream')

            if mime_type not in self.SUPPORTED_MIME_TYPES:
                logging.info(f"Skipping unsupported file type: {mime_type}")
                return False

            os.makedirs(local_dir, exist_ok=True)
            full_path = os.path.join(local_dir, file_name)

            download_url = f"{self._get_item_url(file_id)}/content"
            download_response = requests.get(download_url, headers=self._get_headers())
            download_response.raise_for_status()

            with open(full_path, 'wb') as f:
                f.write(download_response.content)

            return True
        except Exception as e:
            logging.error(f"Error in _download_single_file: {e}")
            return False

    def _download_folder_recursive(self, folder_id: str, local_dir: str, recursive: bool = True) -> int:
        files_downloaded = 0
        try:
            os.makedirs(local_dir, exist_ok=True)

            url = f"{self._get_item_url(folder_id)}/children"
            params = {'$top': 1000}

            while url:
                response = requests.get(url, headers=self._get_headers(), params=params)
                response.raise_for_status()

                results = response.json()
                items = results.get('value', [])
                logging.info(f"Found {len(items)} items in folder {folder_id}")

                for item in items:
                    item_name = item.get('name', 'unknown')
                    item_id = item.get('id')

                    if 'folder' in item:
                        if recursive:
                            subfolder_path = os.path.join(local_dir, item_name)
                            os.makedirs(subfolder_path, exist_ok=True)
                            subfolder_files = self._download_folder_recursive(
                                item_id,
                                subfolder_path,
                                recursive
                            )
                            files_downloaded += subfolder_files
                            logging.info(f"Downloaded {subfolder_files} files from subfolder {item_name}")
                    else:
                        success = self._download_single_file(item_id, local_dir)
                        if success:
                            files_downloaded += 1
                            logging.info(f"Downloaded file: {item_name}")
                        else:
                            logging.warning(f"Failed to download file: {item_name}")

                url = results.get('@odata.nextLink')

            return files_downloaded

        except Exception as e:
            logging.error(f"Error in _download_folder_recursive for folder {folder_id}: {e}", exc_info=True)
            return files_downloaded

    def _download_folder_contents(self, folder_id: str, local_dir: str, recursive: bool = True) -> int:
        try:
            self._ensure_valid_token()
            return self._download_folder_recursive(folder_id, local_dir, recursive)
        except Exception as e:
            logging.error(f"Error downloading folder {folder_id}: {e}", exc_info=True)
            return 0

    def _download_file_to_directory(self, file_id: str, local_dir: str) -> bool:
        try:
            self._ensure_valid_token()
            return self._download_single_file(file_id, local_dir)
        except Exception as e:
            logging.error(f"Error downloading file {file_id}: {e}", exc_info=True)
            return False

    def download_to_directory(self, local_dir: str, source_config: Dict[str, Any] = None) -> Dict[str, Any]:
        if source_config is None:
            source_config = {}

        config = source_config if source_config else getattr(self, 'config', {})
        files_downloaded = 0

        try:
            folder_ids = config.get('folder_ids', [])
            file_ids = config.get('file_ids', [])
            recursive = config.get('recursive', True)

            if file_ids:
                if isinstance(file_ids, str):
                    file_ids = [file_ids]

                for file_id in file_ids:
                    if self._download_file_to_directory(file_id, local_dir):
                        files_downloaded += 1

            if folder_ids:
                if isinstance(folder_ids, str):
                    folder_ids = [folder_ids]

                for folder_id in folder_ids:
                    try:
                        url = self._get_item_url(folder_id)
                        params = {'$select': 'id,name'}
                        response = requests.get(url, headers=self._get_headers(), params=params)
                        response.raise_for_status()

                        folder_metadata = response.json()
                        folder_name = folder_metadata.get('name', '')
                        folder_path = os.path.join(local_dir, folder_name)
                        os.makedirs(folder_path, exist_ok=True)

                        folder_files = self._download_folder_recursive(
                            folder_id,
                            folder_path,
                            recursive
                        )
                        files_downloaded += folder_files
                        logging.info(f"Downloaded {folder_files} files from folder {folder_name}")
                    except Exception as e:
                        logging.error(f"Error downloading folder {folder_id}: {e}", exc_info=True)

            if not file_ids and not folder_ids:
                raise ValueError("No folder_ids or file_ids provided for download")

            return {
                "files_downloaded": files_downloaded,
                "directory_path": local_dir,
                "empty_result": files_downloaded == 0,
                "source_type": "share_point",
                "config_used": config
            }

        except Exception as e:
            return {
                "files_downloaded": files_downloaded,
                "directory_path": local_dir,
                "empty_result": True,
                "source_type": "share_point",
                "config_used": config,
                "error": str(e)
            }
