import functools
import logging
import os
from typing import Any, Dict, Iterable, List, Optional

import requests

from docsgpt.parser.connectors.base import BaseConnectorLoader, FileEntry, SelectionListing
from docsgpt.parser.connectors.confluence.auth import ConfluenceAuth
from docsgpt.parser.schema.base import Document

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


def _page_file_name(title: Any) -> str:
    """The file a page is saved as: its title with unsafe characters replaced, plus ``.html``."""
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in str(title))
    return f"{safe_name}.html"


def _attachment_file_name(raw_name: Any) -> str:
    """The file an attachment is saved as: its base name with unsafe characters replaced."""
    return "".join(
        c if c.isalnum() or c in " -_." else "_"
        for c in os.path.basename(str(raw_name))
    ) or "attachment"


def _version_number(item: Dict[str, Any]) -> Optional[str]:
    """A page's or attachment's ``version.number`` as a string; ``None`` when Confluence gave none."""
    number = (item.get("version") or {}).get("number") if isinstance(item.get("version"), dict) else None
    return str(number) if number is not None else None


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
                    new_token_info = self._refresh_rejected_token(self.access_token)
                    self.access_token = new_token_info["access_token"]
                except Exception as refresh_err:
                    raise ValueError(
                        f"Authentication failed and could not be refreshed: {refresh_err}"
                    ) from e
                return func(self, *args, **kwargs)
            raise

    return wrapper


class ConfluenceLoader(BaseConnectorLoader):

    def __init__(self, session_token: Optional[str] = None, *, connection_id: Optional[str] = None):
        self.auth = ConfluenceAuth()
        self.session_token = session_token

        _, token_info = self._load_token_info(session_token, connection_id)
        missing = [f for f in ("access_token", "cloud_id") if not token_info.get(f)]
        if missing:
            raise ValueError(f"Missing required token fields: {missing}")
        self.access_token = token_info["access_token"]
        self.cloud_id = token_info["cloud_id"]

        self.base_url = API_V2.format(cloud_id=self.cloud_id)
        self.download_base = DOWNLOAD_BASE.format(cloud_id=self.cloud_id)
        self.next_page_token = None
        # The site's web address (``https://acme.atlassian.net/wiki``), from the first response that names it.
        self._site_base: Optional[str] = None
        # Downloaded file's local path → its web UI link, relative to the site.
        self._file_links: Dict[str, str] = {}
        # The last listed selection: entries by id, and each attachment's download link.
        self._listed: Dict[str, FileEntry] = {}
        self._listed_downloads: Dict[str, str] = {}

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

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
        self._file_links = {}

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
            "file_urls": self._file_urls(local_dir),
        }

    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = requests.get(f"{self.base_url}{path}", headers=self._headers(), params=params or {}, timeout=30)
        response.raise_for_status()
        data = response.json()
        self._note_site(data.get("_links") if isinstance(data, dict) else None)
        return data if isinstance(data, dict) else {}

    def _list_page(self, page: Dict[str, Any], entries: List[FileEntry], links: Dict[str, str]) -> bool:
        """Add a page and its supported attachments to ``entries``; False when its attachments can't be listed."""
        page_id = str(page.get("id"))
        page_links = page.get("_links") if isinstance(page.get("_links"), dict) else {}
        entries.append(FileEntry(
            id=f"page:{page_id}",
            path=_page_file_name(page.get("title", page_id)),
            version=_version_number(page),
        ))
        if page_links.get("webui"):
            links[f"page:{page_id}"] = str(page_links["webui"])
        cursor = None
        try:
            while True:
                params: Dict[str, Any] = {"limit": 100}
                if cursor:
                    params["cursor"] = cursor
                data = self._get_json(f"/pages/{page_id}/attachments", params)
                for att in data.get("results", []):
                    if att.get("mediaType", "") not in SUPPORTED_ATTACHMENT_TYPES:
                        continue
                    att_links = att.get("_links") if isinstance(att.get("_links"), dict) else {}
                    if not att_links.get("download"):
                        continue
                    entry_id = f"attachment:{att.get('id')}"
                    entries.append(FileEntry(
                        id=entry_id,
                        path=_attachment_file_name(att.get("title", att.get("id", "attachment"))),
                        version=_version_number(att),
                    ))
                    self._listed_downloads[entry_id] = str(att_links["download"])
                    if att_links.get("webui"):
                        links[entry_id] = str(att_links["webui"])
                cursor = self._extract_cursor(data.get("_links", {}).get("next"))
                if not cursor:
                    return True
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                raise
            logger.warning("Could not list the attachments of page %s: %s", page_id, e)
            return False
        except Exception as e:
            logger.warning("Could not list the attachments of page %s: %s", page_id, e)
            return False

    @_retry_on_auth_failure
    def list_selection(self, source_config: Dict[str, Any]) -> SelectionListing:
        """List the selected pages and their attachments, each versioned by its ``version.number``.

        Paths match :meth:`download_to_directory`: every page and attachment
        sits at the top of the directory, and of two that share a name the
        later one is kept, as the download overwrites the earlier.
        """
        config = source_config or {}
        file_ids = config.get("file_ids") or []
        folder_ids = config.get("folder_ids") or []
        if isinstance(file_ids, str):
            file_ids = [file_ids]
        if isinstance(folder_ids, str):
            folder_ids = [folder_ids]
        entries: List[FileEntry] = []
        links: Dict[str, str] = {}
        complete = True
        self._listed_downloads = {}
        for page_id in file_ids:
            try:
                page = self._get_json(f"/pages/{page_id}")
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code in (401, 403):
                    raise
                if e.response is not None and e.response.status_code == 404:
                    continue
                logger.warning("Could not read Confluence page %s: %s", page_id, e)
                complete = False
                continue
            except Exception as e:
                logger.warning("Could not read Confluence page %s: %s", page_id, e)
                complete = False
                continue
            complete = self._list_page(page, entries, links) and complete
        for space_id in folder_ids:
            cursor = None
            while True:
                params: Dict[str, Any] = {"limit": 250}
                if cursor:
                    params["cursor"] = cursor
                try:
                    data = self._get_json(f"/spaces/{space_id}/pages", params)
                except requests.exceptions.HTTPError as e:
                    if e.response is not None and e.response.status_code in (401, 403):
                        raise
                    logger.warning("Could not list the pages of space %s: %s", space_id, e)
                    complete = False
                    break
                except Exception as e:
                    logger.warning("Could not list the pages of space %s: %s", space_id, e)
                    complete = False
                    break
                for page in data.get("results", []):
                    complete = self._list_page(page, entries, links) and complete
                cursor = self._extract_cursor(data.get("_links", {}).get("next"))
                if not cursor:
                    break
        absolute = ("https://", "http://")
        base = self._site_base
        if base is None and any(not link.startswith(absolute) for link in links.values()):
            base = self._fetch_site_base()
        resolved = {}
        for entry in entries:
            link = links.get(entry.id)
            if link and not link.startswith(absolute):
                link = f"{base.rstrip('/')}/{link.lstrip('/')}" if base else None
            resolved[entry.path] = FileEntry(id=entry.id, path=entry.path, version=entry.version, url=link)
        listing = SelectionListing(entries=list(resolved.values()), complete=complete)
        self._listed = listing.by_id()
        return listing

    def download_files(self, local_dir: str, file_ids: Iterable[str]) -> Dict[str, Any]:
        """Download the given pages and attachments of the last listed selection."""
        os.makedirs(local_dir, exist_ok=True)
        downloaded = 0
        paths: Dict[str, str] = {}
        file_urls: Dict[str, str] = {}
        failures: Dict[str, Dict[str, str]] = {}
        for file_id in dict.fromkeys(str(i) for i in file_ids):
            entry = self._listed.get(file_id)
            if entry is None:
                failures[file_id] = {"kind": "transient", "error": "not in the listed selection"}
                continue
            target = os.path.join(local_dir, entry.path)
            try:
                if file_id.startswith("page:"):
                    if not self._download_page(file_id.split(":", 1)[1], local_dir) or not os.path.isfile(target):
                        raise RuntimeError("the page could not be downloaded")
                else:
                    response = requests.get(
                        f"{self.download_base}{self._listed_downloads[file_id]}",
                        headers=self._headers(), timeout=60, stream=True,
                    )
                    response.raise_for_status()
                    with open(target, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
            except Exception as e:
                logger.warning("Could not download Confluence file %s: %s", entry.path, e)
                failures[file_id] = {"kind": "transient", "error": str(e)[:300]}
                continue
            downloaded += 1
            paths[entry.path] = file_id
            if entry.url:
                file_urls[entry.path] = entry.url
        return {
            "files_downloaded": downloaded,
            "files_failed": len(failures),
            "file_ids": paths,
            "file_urls": file_urls,
            "failures": failures,
        }

    def _note_site(self, links: Any) -> None:
        """Keep the site's web address from a response's ``_links.base``."""
        if not self._site_base and isinstance(links, dict) and links.get("base"):
            self._site_base = str(links["base"])

    def _note_link(self, path: str, links: Any) -> None:
        """Remember the web UI link of the file written at ``path``."""
        webui = links.get("webui") if isinstance(links, dict) else None
        if webui:
            self._file_links[path] = str(webui)

    def _fetch_site_base(self) -> Optional[str]:
        """Read the site's web address from a one-item space listing; ``None`` when it cannot."""
        try:
            response = requests.get(
                f"{self.base_url}/spaces", headers=self._headers(), params={"limit": 1}, timeout=30
            )
            response.raise_for_status()
            return response.json().get("_links", {}).get("base") or None
        except Exception as e:
            logger.warning("Could not read the Confluence site address: %s", e)
            return None

    def _file_urls(self, local_dir: str) -> Dict[str, str]:
        """Each downloaded file's web link, keyed by its path under ``local_dir``."""
        absolute = ("https://", "http://")
        base = self._site_base
        if base is None and any(not webui.startswith(absolute) for webui in self._file_links.values()):
            base = self._fetch_site_base()
        urls = {}
        for path, webui in self._file_links.items():
            if webui.startswith(absolute):
                urls[os.path.relpath(path, local_dir)] = webui
            elif base:
                urls[os.path.relpath(path, local_dir)] = f"{base.rstrip('/')}/{webui.lstrip('/')}"
        return urls

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
            body = page.get("body", {}).get("storage", {}).get("value", "")

            file_path = os.path.join(local_dir, _page_file_name(title))
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(body)

            self._note_site(page.get("_links"))
            self._note_link(file_path, page.get("_links"))
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
                self._note_site(data.get("_links"))

                for att in data.get("results", []):
                    media_type = att.get("mediaType", "")
                    if media_type not in SUPPORTED_ATTACHMENT_TYPES:
                        continue

                    download_link = att.get("_links", {}).get("download")
                    if not download_link:
                        continue

                    raw_name = att.get("title", att.get("id", "attachment"))
                    file_name = _attachment_file_name(raw_name)
                    file_path = os.path.join(local_dir, file_name)

                    url = f"{self.download_base}{download_link}"
                    file_resp = requests.get(
                        url, headers=self._headers(), timeout=60, stream=True
                    )
                    file_resp.raise_for_status()

                    with open(file_path, "wb") as f:
                        for chunk in file_resp.iter_content(chunk_size=8192):
                            f.write(chunk)

                    self._note_link(file_path, att.get("_links"))
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
            self._note_site(data.get("_links"))

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
