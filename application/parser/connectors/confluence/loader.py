import functools
import logging
import os
from typing import Any, Dict, List, Optional

import requests

from application.parser.connectors.base import BaseConnectorLoader
from application.parser.connectors.confluence.auth import ConfluenceAuth
from application.parser.schema.base import Document

logger = logging.getLogger(__name__)

API_V2 = "https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/api/v2"
DOWNLOAD_BASE = "https://api.atlassian.com/ex/confluence/{cloud_id}/wiki"

SUPPORTED_ATTACHMENT_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/msword": ".doc",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.ms-excel": ".xls",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/html": ".html",
    "text/markdown": ".md",
    "application/json": ".json",
    "application/epub+zip": ".epub",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


def _retry_on_auth_failure(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                logger.info(
                    "Auth failure in %s, refreshing token and retrying", func.__name__
                )
                try:
                    new_token_info = self.auth.refresh_access_token(self.refresh_token)
                    self.access_token = new_token_info["access_token"]
                    self.refresh_token = new_token_info.get(
                        "refresh_token", self.refresh_token
                    )
                    self._persist_refreshed_tokens(new_token_info)
                except Exception as refresh_err:
                    raise ValueError(
                        f"Authentication failed and could not be refreshed: {refresh_err}"
                    ) from e
                return func(self, *args, **kwargs)
            raise

    return wrapper


class ConfluenceLoader(BaseConnectorLoader):

    def __init__(self, session_token: str):
        self.auth = ConfluenceAuth()
        self.session_token = session_token

        token_info = self.auth.get_token_info_from_session(session_token)
        self.access_token = token_info["access_token"]
        self.refresh_token = token_info["refresh_token"]
        self.cloud_id = token_info["cloud_id"]

        self.base_url = API_V2.format(cloud_id=self.cloud_id)
        self.download_base = DOWNLOAD_BASE.format(cloud_id=self.cloud_id)
        self.next_page_token = None

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    def _persist_refreshed_tokens(self, token_info: Dict[str, Any]) -> None:
        try:
            from application.storage.db.repositories.connector_sessions import (
                ConnectorSessionsRepository,
            )
            from application.storage.db.session import db_session

            sanitized = self.auth.sanitize_token_info(token_info)
            with db_session() as conn:
                repo = ConnectorSessionsRepository(conn)
                session = repo.get_by_session_token(self.session_token)
                if session:
                    repo.update(str(session["id"]), {"token_info": sanitized})
        except Exception as e:
            logger.warning("Failed to persist refreshed tokens: %s", e)

    @_retry_on_auth_failure
    def load_data(self, inputs: Dict[str, Any]) -> List[Document]:
        folder_id = inputs.get("folder_id")
        file_ids = inputs.get("file_ids", [])
        limit = inputs.get("limit", 100)
        list_only = inputs.get("list_only", False)
        page_token = inputs.get("page_token")
        search_query = inputs.get("search_query")
        self.next_page_token = None

        if file_ids:
            return self._load_pages_by_ids(file_ids, list_only, search_query)

        if folder_id:
            return self._list_pages_in_space(
                folder_id, limit, list_only, page_token, search_query
            )

        return self._list_spaces(limit, page_token, search_query)

    @_retry_on_auth_failure
    def download_to_directory(self, local_dir: str, source_config: dict = None) -> dict:
        config = source_config or getattr(self, "config", {})
        file_ids = config.get("file_ids", [])
        folder_ids = config.get("folder_ids", [])
        files_downloaded = 0

        os.makedirs(local_dir, exist_ok=True)

        if isinstance(file_ids, str):
            file_ids = [file_ids]
        if isinstance(folder_ids, str):
            folder_ids = [folder_ids]

        for page_id in file_ids:
            if self._download_page(page_id, local_dir):
                files_downloaded += 1
            files_downloaded += self._download_page_attachments(page_id, local_dir)

        for space_id in folder_ids:
            files_downloaded += self._download_space(space_id, local_dir)

        return {
            "files_downloaded": files_downloaded,
            "directory_path": local_dir,
            "empty_result": files_downloaded == 0,
            "source_type": "confluence",
            "config_used": config,
        }

    def _list_spaces(
        self, limit: int, cursor: Optional[str], search_query: Optional[str]
    ) -> List[Document]:
        documents: List[Document] = []
        params: Dict[str, Any] = {"limit": min(limit, 250)}
        if cursor:
            params["cursor"] = cursor

        response = requests.get(
            f"{self.base_url}/spaces",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        for space in data.get("results", []):
            name = space.get("name", "")
            if search_query and search_query.lower() not in name.lower():
                continue

            documents.append(
                Document(
                    text="",
                    doc_id=space["id"],
                    extra_info={
                        "file_name": name,
                        "mime_type": "folder",
                        "size": None,
                        "created_time": space.get("createdAt"),
                        "modified_time": None,
                        "source": "confluence",
                        "is_folder": True,
                        "space_key": space.get("key"),
                    },
                )
            )

        next_link = data.get("_links", {}).get("next")
        self.next_page_token = self._extract_cursor(next_link)
        return documents

    def _list_pages_in_space(
        self,
        space_id: str,
        limit: int,
        list_only: bool,
        cursor: Optional[str],
        search_query: Optional[str],
    ) -> List[Document]:
        documents: List[Document] = []
        params: Dict[str, Any] = {"limit": min(limit, 250)}
        if cursor:
            params["cursor"] = cursor

        response = requests.get(
            f"{self.base_url}/spaces/{space_id}/pages",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        for page in data.get("results", []):
            title = page.get("title", "")
            if search_query and search_query.lower() not in title.lower():
                continue

            doc = self._page_to_document(
                page, load_content=not list_only, space_id=space_id
            )
            if doc:
                documents.append(doc)

        next_link = data.get("_links", {}).get("next")
        self.next_page_token = self._extract_cursor(next_link)
        return documents

    def _load_pages_by_ids(
        self, page_ids: List[str], list_only: bool, search_query: Optional[str]
    ) -> List[Document]:
        documents: List[Document] = []
        for page_id in page_ids:
            try:
                params: Dict[str, str] = {}
                if not list_only:
                    params["body-format"] = "storage"

                response = requests.get(
                    f"{self.base_url}/pages/{page_id}",
                    headers=self._headers(),
                    params=params,
                    timeout=30,
                )
                response.raise_for_status()
                page = response.json()

                title = page.get("title", "")
                if search_query and search_query.lower() not in title.lower():
                    continue

                doc = self._page_to_document(page, load_content=not list_only)
                if doc:
                    documents.append(doc)
            except Exception as e:
                logger.error("Error loading page %s: %s", page_id, e)
        return documents

    def _page_to_document(
        self,
        page: Dict[str, Any],
        load_content: bool = False,
        space_id: Optional[str] = None,
    ) -> Optional[Document]:
        page_id = page.get("id")
        title = page.get("title", "Unknown")
        version = page.get("version", {})
        modified_time = version.get("createdAt") if isinstance(version, dict) else None
        created_time = page.get("createdAt")
        resolved_space_id = space_id or page.get("spaceId")

        text = ""
        if load_content:
            body = page.get("body", {})
            storage = body.get("storage", {}) if isinstance(body, dict) else {}
            text = storage.get("value", "") if isinstance(storage, dict) else ""

        return Document(
            text=text,
            doc_id=str(page_id),
            extra_info={
                "file_name": title,
                "mime_type": "text/html",
                "size": len(text) if text else None,
                "created_time": created_time,
                "modified_time": modified_time,
                "source": "confluence",
                "is_folder": False,
                "page_id": str(page_id),
                "space_id": resolved_space_id,
                "cloud_id": self.cloud_id,
            },
        )

    def _download_page(self, page_id: str, local_dir: str) -> bool:
        try:
            response = requests.get(
                f"{self.base_url}/pages/{page_id}",
                headers=self._headers(),
                params={"body-format": "storage"},
                timeout=30,
            )
            response.raise_for_status()
            page = response.json()

            title = page.get("title", page_id)
            safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
            body = page.get("body", {}).get("storage", {}).get("value", "")

            file_path = os.path.join(local_dir, f"{safe_name}.html")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(body)

            return True
        except Exception as e:
            logger.error("Error downloading page %s: %s", page_id, e)
            return False

    def _download_page_attachments(self, page_id: str, local_dir: str) -> int:
        downloaded = 0
        try:
            cursor = None
            while True:
                params: Dict[str, Any] = {"limit": 100}
                if cursor:
                    params["cursor"] = cursor

                response = requests.get(
                    f"{self.base_url}/pages/{page_id}/attachments",
                    headers=self._headers(),
                    params=params,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()

                for att in data.get("results", []):
                    media_type = att.get("mediaType", "")
                    if media_type not in SUPPORTED_ATTACHMENT_TYPES:
                        continue

                    download_link = att.get("_links", {}).get("download")
                    if not download_link:
                        continue

                    raw_name = att.get("title", att.get("id", "attachment"))
                    file_name = "".join(
                        c if c.isalnum() or c in " -_." else "_"
                        for c in os.path.basename(raw_name)
                    ) or "attachment"
                    file_path = os.path.join(local_dir, file_name)

                    url = f"{self.download_base}{download_link}"
                    file_resp = requests.get(
                        url, headers=self._headers(), timeout=60, stream=True
                    )
                    file_resp.raise_for_status()

                    with open(file_path, "wb") as f:
                        for chunk in file_resp.iter_content(chunk_size=8192):
                            f.write(chunk)

                    downloaded += 1

                next_link = data.get("_links", {}).get("next")
                cursor = self._extract_cursor(next_link)
                if not cursor:
                    break

        except Exception as e:
            logger.error("Error downloading attachments for page %s: %s", page_id, e)
        return downloaded

    def _download_space(self, space_id: str, local_dir: str) -> int:
        downloaded = 0
        cursor = None
        while True:
            params: Dict[str, Any] = {"limit": 250}
            if cursor:
                params["cursor"] = cursor

            try:
                response = requests.get(
                    f"{self.base_url}/spaces/{space_id}/pages",
                    headers=self._headers(),
                    params=params,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.error("Error listing pages in space %s: %s", space_id, e)
                break

            for page in data.get("results", []):
                page_id = page.get("id")
                if self._download_page(str(page_id), local_dir):
                    downloaded += 1
                downloaded += self._download_page_attachments(str(page_id), local_dir)

            next_link = data.get("_links", {}).get("next")
            cursor = self._extract_cursor(next_link)
            if not cursor:
                break

        return downloaded

    @staticmethod
    def _extract_cursor(next_link: Optional[str]) -> Optional[str]:
        if not next_link:
            return None
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(next_link)
        cursors = parse_qs(parsed.query).get("cursor")
        return cursors[0] if cursors else None
