"""Tests for SharePointLoader."""

import os
from tests.parser.connectors.token_patch import patch_tokens
from unittest.mock import MagicMock, patch

import pytest
import requests as real_requests

from docsgpt.parser.connectors.share_point.loader import DownloadCounts
from docsgpt.parser.schema.base import Document


_GRAPH_401_BODY = {
    "error": {
        "code": "InvalidAuthenticationToken",
        "message": "Lifetime validation failed, the token is expired.",
    },
}
_WWW_AUTHENTICATE = 'Bearer realm="", authorization_uri="https://login.microsoftonline.com/common/oauth2/authorize"'


def _graph_response(status=200, data=None, content=b"", headers=None):
    """A ``requests`` response as Graph would send it."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data if data is not None else {}
    resp.content = content
    resp.headers = headers if headers is not None else (
        {"WWW-Authenticate": _WWW_AUTHENTICATE} if status == 401 else {}
    )
    if status >= 400:
        resp.raise_for_status.side_effect = real_requests.exceptions.HTTPError(f"{status} Error", response=resp)
    return resp


def _make_loader(access_token="at", refresh_token="rt", allows_shared=False):
    """Create a SharePointLoader with mocked dependencies."""
    with patch("docsgpt.parser.connectors.share_point.loader.SharePointAuth") as MockAuth:
        mock_auth = MagicMock()
        token_info = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "allows_shared_content": allows_shared,
        }
        mock_auth.is_token_expired.return_value = False
        MockAuth.return_value = mock_auth

        from docsgpt.parser.connectors.share_point.loader import SharePointLoader
        with patch_tokens(token_info):
            loader = SharePointLoader("session_tok")
    return loader


@pytest.fixture
def loader():
    return _make_loader()


@pytest.fixture
def loader_shared():
    return _make_loader(allows_shared=True)


class TestSharePointLoaderInit:

    @pytest.mark.unit
    def test_init_sets_attributes(self, loader):
        assert loader.session_token == "session_tok"
        assert loader.access_token == "at"
        assert loader.connection_id == "conn-1"
        assert loader.allows_shared_content is False
        assert loader.next_page_token is None

    @pytest.mark.unit
    def test_no_access_token_raises(self):
        with patch("docsgpt.parser.connectors.share_point.loader.SharePointAuth") as MockAuth:
            mock_auth = MagicMock()
            token_info = {
                "access_token": None,
                "refresh_token": "rt",
            }
            MockAuth.return_value = mock_auth

            from docsgpt.parser.connectors.share_point.loader import SharePointLoader
            with pytest.raises(ValueError, match="No access token"):
                with patch_tokens(token_info):
                    SharePointLoader("st")


class TestGetHeaders:

    @pytest.mark.unit
    def test_returns_bearer_token(self, loader):
        headers = loader._get_headers()
        assert headers["Authorization"] == "Bearer at"
        assert headers["Accept"] == "application/json"


class TestEnsureValidToken:

    @pytest.mark.unit
    def test_valid_token_no_op(self, loader):
        loader.auth.is_token_expired.return_value = False
        loader._ensure_valid_token()

    @pytest.mark.unit
    def test_no_access_token_raises(self, loader):
        loader.access_token = None
        with pytest.raises(ValueError, match="No access token"):
            loader._ensure_valid_token()

    @pytest.mark.unit
    def test_expired_token_refreshes(self, loader):
        loader.auth.is_token_expired.return_value = True
        with patch(
            "docsgpt.connectors.service.get_valid_token_info", return_value={"access_token": "new_at"},
        ) as tokens:
            loader._ensure_valid_token()
        assert loader.access_token == "new_at"
        tokens.assert_called_once_with("conn-1")

    @pytest.mark.unit
    def test_refresh_failure_raises(self, loader):
        loader.auth.is_token_expired.return_value = True
        with patch("docsgpt.connectors.service.get_valid_token_info", side_effect=Exception("fail")):
            with pytest.raises(ValueError, match="Failed to refresh"):
                loader._ensure_valid_token()


class TestGetItemUrl:

    @pytest.mark.unit
    def test_simple_id(self, loader):
        url = loader._get_item_url("item123")
        assert url == f"{loader.GRAPH_API_BASE}/me/drive/items/item123"

    @pytest.mark.unit
    def test_drive_colon_item(self, loader):
        url = loader._get_item_url("driveABC:itemXYZ")
        assert url == f"{loader.GRAPH_API_BASE}/drives/driveABC/items/itemXYZ"


class TestResolveMimeType:

    @pytest.mark.unit
    def test_supported_mime_from_file_data(self, loader):
        resource = {"file": {"mimeType": "application/pdf"}, "name": "test.pdf"}
        mime, supported = loader._resolve_mime_type(resource)
        assert mime == "application/pdf"
        assert supported is True

    @pytest.mark.unit
    def test_fallback_to_extension(self, loader):
        resource = {"file": {"mimeType": "application/octet-stream"}, "name": "test.docx"}
        mime, supported = loader._resolve_mime_type(resource)
        assert mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert supported is True

    @pytest.mark.unit
    def test_unsupported_returns_false(self, loader):
        resource = {"file": {"mimeType": "application/zip"}, "name": "test.zip"}
        mime, supported = loader._resolve_mime_type(resource)
        assert supported is False

    @pytest.mark.unit
    def test_no_file_data_fallback_to_extension(self, loader):
        resource = {"name": "readme.txt"}
        mime, supported = loader._resolve_mime_type(resource)
        assert mime == "text/plain"
        assert supported is True

    @pytest.mark.unit
    def test_no_file_data_no_extension(self, loader):
        resource = {"name": "noext"}
        mime, supported = loader._resolve_mime_type(resource)
        assert mime == "application/octet-stream"
        assert supported is False


class TestProcessFile:

    @pytest.mark.unit
    def test_supported_file_with_content(self, loader):
        loader._download_file_content = MagicMock(return_value="content")
        metadata = {
            "id": "f1",
            "name": "test.pdf",
            "file": {"mimeType": "application/pdf"},
            "size": 1024,
            "createdDateTime": "2025-01-01",
            "lastModifiedDateTime": "2025-01-02",
        }
        doc = loader._process_file(metadata, load_content=True)
        assert doc is not None
        assert doc.text == "content"
        assert doc.extra_info["source"] == "share_point"

    @pytest.mark.unit
    def test_supported_file_no_content(self, loader):
        metadata = {
            "id": "f1",
            "name": "test.pdf",
            "file": {"mimeType": "application/pdf"},
        }
        doc = loader._process_file(metadata, load_content=False)
        assert doc.text == ""

    @pytest.mark.unit
    def test_unsupported_returns_none(self, loader):
        metadata = {
            "id": "f1",
            "name": "test.zip",
            "file": {"mimeType": "application/zip"},
        }
        doc = loader._process_file(metadata)
        assert doc is None

    @pytest.mark.unit
    def test_download_failure_returns_none(self, loader):
        loader._download_file_content = MagicMock(return_value=None)
        metadata = {
            "id": "f1",
            "name": "test.txt",
            "file": {"mimeType": "text/plain"},
        }
        doc = loader._process_file(metadata, load_content=True)
        assert doc is None

    @pytest.mark.unit
    def test_exception_returns_none(self, loader):
        loader._download_file_content = MagicMock(side_effect=Exception("fail"))
        metadata = {"id": "f1", "name": "test.txt", "file": {"mimeType": "text/plain"}}
        doc = loader._process_file(metadata, load_content=True)
        assert doc is None


class TestLoadData:

    @pytest.mark.unit
    def test_load_specific_files(self, loader):
        doc = Document(text="c", doc_id="f1", extra_info={"file_name": "test.pdf"})
        loader._load_file_by_id = MagicMock(return_value=doc)
        result = loader.load_data({"file_ids": ["f1"]})
        assert len(result) == 1

    @pytest.mark.unit
    def test_load_files_with_search_filter(self, loader):
        doc = Document(text="c", doc_id="f1", extra_info={"file_name": "report.pdf"})
        loader._load_file_by_id = MagicMock(return_value=doc)
        result = loader.load_data({"file_ids": ["f1"], "search_query": "report"})
        assert len(result) == 1
        result = loader.load_data({"file_ids": ["f1"], "search_query": "other"})
        assert len(result) == 0

    @pytest.mark.unit
    def test_load_files_error_continues(self, loader):
        loader._load_file_by_id = MagicMock(side_effect=Exception("fail"))
        result = loader.load_data({"file_ids": ["f1"]})
        assert len(result) == 0

    @pytest.mark.unit
    def test_shared_mode(self, loader_shared):
        loader_shared._list_shared_items = MagicMock(return_value=[
            Document(text="", doc_id="s1", extra_info={})
        ])
        result = loader_shared.load_data({"shared": True})
        assert len(result) == 1

    @pytest.mark.unit
    def test_shared_mode_personal_account_returns_empty(self, loader):
        result = loader.load_data({"shared": True})
        assert len(result) == 0

    @pytest.mark.unit
    def test_browse_mode_uses_list_items(self, loader):
        loader._list_items_in_parent = MagicMock(return_value=[])
        loader.load_data({"folder_id": "folder1"})
        loader._list_items_in_parent.assert_called_once()

    @pytest.mark.unit
    def test_browse_mode_defaults_to_root(self, loader):
        loader._list_items_in_parent = MagicMock(return_value=[])
        loader.load_data({})
        args = loader._list_items_in_parent.call_args
        assert args[0][0] == "root"

    @pytest.mark.unit
    def test_list_only_mode(self, loader):
        loader._list_items_in_parent = MagicMock(return_value=[])
        loader.load_data({"list_only": True})
        args = loader._list_items_in_parent.call_args
        assert args[1]["load_content"] is False

    @pytest.mark.unit
    def test_outer_exception_raises(self, loader):
        """The outer try/except in load_data re-raises unexpected errors."""
        loader._list_items_in_parent = MagicMock(side_effect=RuntimeError("unexpected"))
        with pytest.raises(RuntimeError, match="unexpected"):
            loader.load_data({})


class TestLoadFileById:

    @pytest.mark.unit
    def test_loads_and_processes(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "f1", "name": "test.pdf", "file": {"mimeType": "application/pdf"}
        }
        mock_response.raise_for_status = MagicMock()

        loader._process_file = MagicMock(return_value=Document(text="", doc_id="f1", extra_info={}))

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            doc = loader._load_file_by_id("f1")
        assert doc is not None

    @pytest.mark.unit
    def test_401_retries_with_refresh(self, loader):
        responses = [
            _graph_response(401, _GRAPH_401_BODY),
            _graph_response(data={"id": "f1", "name": "t.pdf", "file": {"mimeType": "application/pdf"}}),
        ]
        loader._process_file = MagicMock(return_value=Document(text="", doc_id="f1", extra_info={}))
        loader._refresh_rejected_token = MagicMock(return_value={"access_token": "new_at"})

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=responses) as get:
            doc = loader._load_file_by_id("f1")
        assert doc is not None
        loader._refresh_rejected_token.assert_called_once_with("at")
        assert get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer new_at"

    @pytest.mark.unit
    def test_general_exception_returns_none(self, loader):
        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
            doc = loader._load_file_by_id("f1")
        assert doc is None


class TestListItemsInParent:

    @pytest.mark.unit
    def test_lists_files_and_folders(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [
                {"id": "folder1", "name": "Docs", "folder": {}, "size": 0, "createdDateTime": "d1", "lastModifiedDateTime": "d2"},
                {"id": "file1", "name": "test.pdf", "file": {"mimeType": "application/pdf"}, "size": 100},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        loader._process_file = MagicMock(return_value=Document(text="", doc_id="file1", extra_info={}))

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            docs = loader._list_items_in_parent("root")
        assert len(docs) == 2
        assert docs[0].extra_info["is_folder"] is True

    @pytest.mark.unit
    def test_search_query_uses_search_url(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": []}
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response) as mock_get:
            loader._list_items_in_parent("root", search_query="report")
            call_url = mock_get.call_args[0][0]
            assert "search" in call_url

    @pytest.mark.unit
    def test_search_with_drive_id(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": []}
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response) as mock_get:
            loader._list_items_in_parent("drive1:folder1", search_query="test")
            call_url = mock_get.call_args[0][0]
            assert "drives/drive1" in call_url

    @pytest.mark.unit
    def test_pagination_token_stored(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [
                {"id": "f1", "name": "test.txt", "file": {"mimeType": "text/plain"}},
            ],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/items?$skiptoken=abc123",
        }
        mock_response.raise_for_status = MagicMock()
        loader._process_file = MagicMock(return_value=Document(text="", doc_id="f1", extra_info={}))

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            loader._list_items_in_parent("root")
        assert loader.next_page_token == "abc123"

    @pytest.mark.unit
    def test_no_next_link_clears_token(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": []}
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            loader._list_items_in_parent("root")
        assert loader.next_page_token is None

    @pytest.mark.unit
    def test_limit_stops_early(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [
                {"id": f"f{i}", "name": f"f{i}.txt", "file": {"mimeType": "text/plain"}} for i in range(10)
            ],
        }
        mock_response.raise_for_status = MagicMock()
        loader._process_file = MagicMock(side_effect=lambda m, **kw: Document(text="", doc_id=m["id"], extra_info={}))

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            docs = loader._list_items_in_parent("root", limit=3)
        assert len(docs) == 3

    @pytest.mark.unit
    def test_page_token_passed_as_skip_token(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": []}
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response) as mock_get:
            loader._list_items_in_parent("root", page_token="tok123")
            call_kwargs = mock_get.call_args[1]
            assert call_kwargs["params"]["$skipToken"] == "tok123"

    @pytest.mark.unit
    def test_exception_returns_partial(self, loader):
        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
            docs = loader._list_items_in_parent("root")
        assert docs == []

    @pytest.mark.unit
    def test_next_link_without_skiptoken(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/items?other=param",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            loader._list_items_in_parent("root")
        assert loader.next_page_token is None


class TestDownloadFileContent:

    @pytest.mark.unit
    def test_downloads_and_decodes(self, loader):
        mock_response = MagicMock()
        mock_response.content = b"file content"
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            content = loader._download_file_content("f1")
        assert content == "file content"

    @pytest.mark.unit
    def test_unicode_decode_error_returns_none(self, loader):
        mock_response = MagicMock()
        mock_response.content = MagicMock()
        mock_response.content.decode.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "bad")
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            result = loader._download_file_content("f1")
        assert result is None

    @pytest.mark.unit
    def test_general_exception_returns_none(self, loader):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
            result = loader._download_file_content("f1")
        assert result is None

    @pytest.mark.unit
    def test_http_401_retries_with_refresh(self, loader):
        responses = [_graph_response(401, _GRAPH_401_BODY), _graph_response(content=b"content after refresh")]
        loader._refresh_rejected_token = MagicMock(return_value={"access_token": "new_at"})

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=responses):
            content = loader._download_file_content("f1")
        assert content == "content after refresh"
        assert loader.access_token == "new_at"


class TestListSharedItems:

    @pytest.mark.unit
    def test_lists_shared_files(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value="https://user.sharepoint.com/drive")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{
                "hitsContainers": [{
                    "total": 2,
                    "hits": [
                        {
                            "resource": {
                                "id": "item1",
                                "name": "shared.pdf",
                                "file": {"mimeType": "application/pdf"},
                                "size": 100,
                                "parentReference": {"driveId": "d1"},
                            }
                        },
                        {
                            "resource": {
                                "id": "item2",
                                "name": "folder1",
                                "folder": {},
                                "parentReference": {"driveId": "d1"},
                            }
                        },
                    ],
                }]
            }]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items(limit=100, load_content=False)
        assert len(docs) == 2

    @pytest.mark.unit
    def test_deduplicates_hits(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{
                "hitsContainers": [{
                    "total": 2,
                    "hits": [
                        {"resource": {"id": "item1", "name": "f.pdf", "file": {"mimeType": "application/pdf"}, "parentReference": {"driveId": "d1"}}},
                        {"resource": {"id": "item1", "name": "f.pdf", "file": {"mimeType": "application/pdf"}, "parentReference": {"driveId": "d1"}}},
                    ],
                }]
            }]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items(limit=100, load_content=False)
        assert len(docs) == 1

    @pytest.mark.unit
    def test_pagination_with_offset(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        hits = [
            {"resource": {"id": f"item{i}", "name": f"f{i}.pdf", "file": {"mimeType": "application/pdf"}, "parentReference": {"driveId": "d1"}}}
            for i in range(5)
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{"hitsContainers": [{"total": 5, "hits": hits}]}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items(limit=2, page_token="2", load_content=False)
        assert len(docs) == 2
        assert loader_shared.next_page_token == "4"

    @pytest.mark.unit
    def test_offset_beyond_results_returns_empty(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{"hitsContainers": [{"total": 1, "hits": [
                {"resource": {"id": "item1", "name": "f.pdf", "file": {"mimeType": "application/pdf"}, "parentReference": {"driveId": "d1"}}}
            ]}]}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items(page_token="999")
        assert len(docs) == 0
        assert loader_shared.next_page_token is None

    @pytest.mark.unit
    def test_invalid_page_token_defaults_to_zero(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{"hitsContainers": [{"total": 1, "hits": [
                {"resource": {"id": "item1", "name": "f.pdf", "file": {"mimeType": "application/pdf"}, "parentReference": {"driveId": "d1"}}}
            ]}]}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items(page_token="invalid", load_content=False)
        assert len(docs) == 1

    @pytest.mark.unit
    def test_negative_page_token_defaults_to_zero(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{"hitsContainers": [{"total": 1, "hits": [
                {"resource": {"id": "item1", "name": "f.pdf", "file": {"mimeType": "application/pdf"}, "parentReference": {"driveId": "d1"}}}
            ]}]}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items(page_token="-5", load_content=False)
        assert len(docs) == 1

    @pytest.mark.unit
    def test_empty_search_response(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        mock_response = MagicMock()
        mock_response.json.return_value = {"value": []}
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items()
        assert len(docs) == 0

    @pytest.mark.unit
    def test_empty_hits_containers(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{"hitsContainers": []}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items()
        assert len(docs) == 0

    @pytest.mark.unit
    def test_unsupported_shared_file_skipped(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{"hitsContainers": [{"total": 1, "hits": [
                {"resource": {"id": "item1", "name": "f.zip", "file": {"mimeType": "application/zip"}, "parentReference": {"driveId": "d1"}}}
            ]}]}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items(load_content=False)
        assert len(docs) == 0

    @pytest.mark.unit
    def test_shared_item_with_content_download(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)
        loader_shared._download_file_content = MagicMock(return_value="content")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{"hitsContainers": [{"total": 1, "hits": [
                {"resource": {"id": "item1", "name": "f.pdf", "file": {"mimeType": "application/pdf"}, "parentReference": {"driveId": "d1"}}}
            ]}]}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items(load_content=True)
        assert len(docs) == 1
        assert docs[0].text == "content"

    @pytest.mark.unit
    def test_exception_returns_empty(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", side_effect=Exception("fail")):
            docs = loader_shared._list_shared_items()
        assert docs == []

    @pytest.mark.unit
    def test_last_page_clears_next_token(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{"hitsContainers": [{"total": 1, "hits": [
                {"resource": {"id": "item1", "name": "f.pdf", "file": {"mimeType": "application/pdf"}, "parentReference": {"driveId": "d1"}}}
            ]}]}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            loader_shared._list_shared_items(limit=100, load_content=False)
        assert loader_shared.next_page_token is None


class TestGetUserDriveWebUrl:

    @pytest.mark.unit
    def test_returns_web_url(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {"webUrl": "https://user.sharepoint.com/drive"}
        mock_response.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            url = loader._get_user_drive_web_url()
        assert url == "https://user.sharepoint.com/drive"

    @pytest.mark.unit
    def test_exception_returns_none(self, loader):
        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
            url = loader._get_user_drive_web_url()
        assert url is None


class TestBuildSharedKqlQuery:

    @pytest.mark.unit
    def test_with_search_and_drive_url(self, loader):
        query = loader._build_shared_kql_query("test", "https://drive.url")
        assert 'test AND -path:"https://drive.url"' == query

    @pytest.mark.unit
    def test_with_search_no_drive_url(self, loader):
        query = loader._build_shared_kql_query("test", None)
        assert query == "test"

    @pytest.mark.unit
    def test_no_search_with_drive_url(self, loader):
        query = loader._build_shared_kql_query(None, "https://drive.url")
        assert '* AND -path:"https://drive.url"' == query

    @pytest.mark.unit
    def test_no_search_no_drive_url(self, loader):
        query = loader._build_shared_kql_query(None, None)
        assert query == "*"


class TestDownloadToDirectory:

    @pytest.mark.unit
    def test_download_files(self, loader, tmp_path):
        loader._download_file_to_directory = MagicMock(return_value="downloaded")
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1", "f2"]})
        assert result["files_downloaded"] == 2
        assert result["source_type"] == "share_point"

    @pytest.mark.unit
    def test_download_files_string_id(self, loader, tmp_path):
        loader._download_file_to_directory = MagicMock(return_value="downloaded")
        result = loader.download_to_directory(str(tmp_path), {"file_ids": "single"})
        assert result["files_downloaded"] == 1

    @pytest.mark.unit
    def test_download_folders(self, loader, tmp_path):
        mock_response = MagicMock()
        mock_response.json.return_value = {"name": "MyFolder"}
        mock_response.raise_for_status = MagicMock()

        loader._download_folder_recursive = MagicMock(return_value=DownloadCounts(downloaded=3))

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["folder1"]})
        assert result["files_downloaded"] == 3

    @pytest.mark.unit
    def test_download_folders_string_id(self, loader, tmp_path):
        mock_response = MagicMock()
        mock_response.json.return_value = {"name": "F"}
        mock_response.raise_for_status = MagicMock()

        loader._download_folder_recursive = MagicMock(return_value=DownloadCounts(downloaded=1))

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            result = loader.download_to_directory(str(tmp_path), {"folder_ids": "single_folder"})
        assert result["files_downloaded"] == 1

    @pytest.mark.unit
    def test_no_ids_returns_error(self, loader, tmp_path):
        result = loader.download_to_directory(str(tmp_path), {})
        assert "error" in result

    @pytest.mark.unit
    def test_none_config(self, loader, tmp_path):
        result = loader.download_to_directory(str(tmp_path))
        assert "error" in result

    @pytest.mark.unit
    def test_folder_error_continues(self, loader, tmp_path):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("fail")

        loader._download_file_to_directory = MagicMock(return_value="downloaded")

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1"], "folder_ids": ["bad"]})
        assert result["files_downloaded"] == 1
        assert result["folders_failed"] == 1
        assert result["files_failed"] == 0

    @pytest.mark.unit
    def test_file_urls_name_each_downloaded_file(self, loader, tmp_path):
        def resp(data=None, content=b""):
            r = MagicMock()
            r.json.return_value = data or {}
            r.content = content
            r.raise_for_status = MagicMock()
            return r

        pdf = {"mimeType": "application/pdf"}
        responses = [
            # file_ids: the file's metadata, then its content
            resp({"name": "a.pdf", "file": pdf, "webUrl": "https://acme.sharepoint.com/a.pdf"}),
            resp(content=b"a"),
            # folder_ids: the folder, its children, then the child's metadata and content
            resp({"name": "Docs"}),
            resp({"value": [{"id": "f2", "name": "b.pdf", "file": pdf}, {"id": "f3", "name": "c.pdf", "file": pdf}]}),
            resp({"name": "b.pdf", "file": pdf, "webUrl": "https://acme.sharepoint.com/Docs/b.pdf"}),
            resp(content=b"b"),
            resp({"name": "c.pdf", "file": pdf}),
            resp(content=b"c"),
        ]
        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=responses) as get:
            result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1"], "folder_ids": ["d1"]})
        assert result["files_downloaded"] == 3
        assert result["file_urls"] == {
            "a.pdf": "https://acme.sharepoint.com/a.pdf",
            os.path.join("Docs", "b.pdf"): "https://acme.sharepoint.com/Docs/b.pdf",
        }
        assert "webUrl" in get.call_args_list[0].kwargs["params"]["$select"].split(",")

    @pytest.mark.unit
    def test_file_urls_empty_when_nothing_downloaded(self, loader, tmp_path):
        result = loader.download_to_directory(str(tmp_path), {})
        assert result["file_urls"] == {}


class TestDownloadSingleFile:

    @pytest.mark.unit
    def test_downloads_supported_file(self, loader, tmp_path):
        mock_meta_resp = MagicMock()
        mock_meta_resp.json.return_value = {
            "name": "test.pdf", "file": {"mimeType": "application/pdf"}
        }
        mock_meta_resp.raise_for_status = MagicMock()

        mock_dl_resp = MagicMock()
        mock_dl_resp.content = b"pdf content"
        mock_dl_resp.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=[mock_meta_resp, mock_dl_resp]):
            result = loader._download_single_file("f1", str(tmp_path))
        assert result == "downloaded"
        assert os.path.exists(os.path.join(str(tmp_path), "test.pdf"))

    @pytest.mark.unit
    def test_unsupported_is_skipped(self, loader, tmp_path):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "name": "test.zip", "file": {"mimeType": "application/zip"}
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_resp):
            result = loader._download_single_file("f1", str(tmp_path))
        assert result == "skipped"

    @pytest.mark.unit
    def test_exception_is_a_failure(self, loader, tmp_path):
        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
            result = loader._download_single_file("f1", str(tmp_path))
        assert result == "failed"


class TestDownloadFolderRecursive:

    @pytest.mark.unit
    def test_downloads_files_in_folder(self, loader, tmp_path):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [
                {"id": "f1", "name": "file1.txt"},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        loader._download_single_file = MagicMock(return_value="downloaded")

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            counts = loader._download_folder_recursive("folder1", str(tmp_path))
        assert counts.downloaded == 1

    @pytest.mark.unit
    def test_recurses_into_subfolders(self, loader, tmp_path):
        call_count = [0]
        def get_side_effect(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if call_count[0] == 1:
                resp.json.return_value = {
                    "value": [
                        {"id": "sub1", "name": "subfolder", "folder": {}},
                        {"id": "f1", "name": "file1.txt"},
                    ],
                }
            else:
                resp.json.return_value = {
                    "value": [
                        {"id": "f2", "name": "file2.txt"},
                    ],
                }
            return resp

        loader._download_single_file = MagicMock(return_value="downloaded")

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=get_side_effect):
            counts = loader._download_folder_recursive("folder1", str(tmp_path), recursive=True)
        assert counts.downloaded == 2

    @pytest.mark.unit
    def test_non_recursive_skips_subfolders(self, loader, tmp_path):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [
                {"id": "sub1", "name": "subfolder", "folder": {}},
                {"id": "f1", "name": "file1.txt"},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        loader._download_single_file = MagicMock(return_value="downloaded")

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            counts = loader._download_folder_recursive("folder1", str(tmp_path), recursive=False)
        assert counts.downloaded == 1

    @pytest.mark.unit
    def test_download_failure_continues(self, loader, tmp_path):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [
                {"id": "f1", "name": "fail.txt"},
                {"id": "f2", "name": "ok.txt"},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        loader._download_single_file = MagicMock(side_effect=["failed", "downloaded"])

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            counts = loader._download_folder_recursive("folder1", str(tmp_path))
        assert (counts.downloaded, counts.failed) == (1, 1)

    @pytest.mark.unit
    def test_pagination_follows_next_link(self, loader, tmp_path):
        call_count = [0]
        def get_side_effect(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if call_count[0] == 1:
                resp.json.return_value = {
                    "value": [{"id": "f1", "name": "file1.txt"}],
                    "@odata.nextLink": "https://graph.microsoft.com/next",
                }
            else:
                resp.json.return_value = {
                    "value": [{"id": "f2", "name": "file2.txt"}],
                }
            return resp

        loader._download_single_file = MagicMock(return_value="downloaded")

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=get_side_effect):
            counts = loader._download_folder_recursive("folder1", str(tmp_path))
        assert counts.downloaded == 2

    @pytest.mark.unit
    def test_a_folder_that_cannot_be_listed_is_counted(self, loader, tmp_path):
        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
            counts = loader._download_folder_recursive("folder1", str(tmp_path))
        assert (counts.downloaded, counts.folders_failed) == (0, 1)


class TestDownloadFileToDirectory:

    @pytest.mark.unit
    def test_delegates_to_download_single(self, loader, tmp_path):
        loader._download_single_file = MagicMock(return_value="downloaded")
        assert loader._download_file_to_directory("f1", str(tmp_path)) == "downloaded"

    @pytest.mark.unit
    def test_exception_is_a_failure(self, loader, tmp_path):
        loader._download_single_file = MagicMock(side_effect=Exception("fail"))
        assert loader._download_file_to_directory("f1", str(tmp_path)) == "failed"


class _FakeGraph:
    """Answers the Graph GETs of a folder download for a fixed tree, by the request's bearer token.

    ``expire_after`` makes the first token ("at") stop working after that many requests,
    as an access token does when its lifetime runs out part-way through a long download.
    """

    PDF = {"mimeType": "application/pdf"}

    def __init__(self, base, expire_after=None, rejected=()):
        self.base = f"{base}/me/drive/items/"
        self.expire_after = expire_after
        self.rejected = set(rejected)
        self.calls = []
        # Folder "d1" ("Docs"): two listing pages, the second holding subfolder "s1".
        self.pages = {
            "d1": [
                [self._file("f1"), self._file("f2")],
                [self._file("f3"), {"id": "s1", "name": "Sub", "folder": {"childCount": 2}}],
            ],
            "s1": [[self._file("f4"), self._file("f5")]],
        }

    def _file(self, item_id):
        return {"id": item_id, "name": f"{item_id}.pdf", "file": self.PDF}

    def get(self, url, headers=None, **kwargs):
        token = headers["Authorization"].removeprefix("Bearer ")
        self.calls.append((url, token))
        if self.expire_after is not None and len(self.calls) > self.expire_after:
            self.rejected.add("at")
        if token in self.rejected:
            return _graph_response(401, _GRAPH_401_BODY)
        path = url.removeprefix(self.base)
        if path.startswith("page/"):
            _, folder, index = path.split("/")
            return self._page(folder, int(index))
        item_id, _, action = path.partition("/")
        if action == "children":
            return self._page(item_id, 0)
        if action == "content":
            return _graph_response(content=f"contents of {item_id}".encode())
        if item_id in self.pages:
            return _graph_response(data={"id": item_id, "name": "Docs" if item_id == "d1" else "Sub"})
        return _graph_response(data=self._file(item_id))

    def _page(self, folder, index):
        pages = self.pages[folder]
        data = {"value": pages[index]}
        if index + 1 < len(pages):
            data["@odata.nextLink"] = f"{self.base}page/{folder}/{index + 1}"
        return _graph_response(data=data)


def _downloaded(root):
    return sorted(
        os.path.relpath(os.path.join(d, f), root) for d, _, files in os.walk(root) for f in files
    )


_ALL_FILES = sorted(
    os.path.join(*parts)
    for parts in [("Docs", "f1.pdf"), ("Docs", "f2.pdf"), ("Docs", "f3.pdf"),
                  ("Docs", "Sub", "f4.pdf"), ("Docs", "Sub", "f5.pdf")]
)


class TestTokenStaysFreshDuringDownload:

    @pytest.mark.unit
    def test_token_expiring_mid_walk_is_refreshed_before_the_next_request(self, loader, tmp_path):
        graph = _FakeGraph(loader.GRAPH_API_BASE, expire_after=4)
        # The stored expiry passes after the fourth request.
        loader.auth.is_token_expired.side_effect = (
            lambda info: info["access_token"] == "at" and len(graph.calls) >= 4
        )

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=graph.get), patch(
            "docsgpt.connectors.service.get_valid_token_info", return_value={"access_token": "at2", "expiry": 1},
        ) as tokens:
            result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["d1"]})

        tokens.assert_called_once_with("conn-1")
        assert result["files_downloaded"] == 5
        assert "error" not in result
        assert _downloaded(tmp_path) == _ALL_FILES
        assert all(token == "at2" for _, token in graph.calls[4:])

    @pytest.mark.unit
    def test_401_on_a_listing_page_refreshes_once_and_retries(self, loader, tmp_path):
        graph = _FakeGraph(loader.GRAPH_API_BASE)
        listing_pages = []

        def get(url, **kwargs):
            if "/page/" in url:
                listing_pages.append(url)
                if len(listing_pages) == 1:
                    graph.rejected.add("at")
            return graph.get(url, **kwargs)

        loader._refresh_rejected_token = MagicMock(return_value={"access_token": "at2", "expiry": 1})
        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=get):
            result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["d1"]})

        loader._refresh_rejected_token.assert_called_once_with("at")
        assert listing_pages == [f"{graph.base}page/d1/1"] * 2
        assert result["files_downloaded"] == 5
        assert _downloaded(tmp_path) == _ALL_FILES

    @pytest.mark.unit
    def test_401_on_a_file_download_refreshes_and_keeps_every_file(self, loader, tmp_path):
        graph = _FakeGraph(loader.GRAPH_API_BASE, expire_after=5)
        loader._refresh_rejected_token = MagicMock(return_value={"access_token": "at2", "expiry": 1})

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=graph.get):
            result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["d1"]})

        loader._refresh_rejected_token.assert_called_once_with("at")
        assert result["files_downloaded"] == 5
        assert _downloaded(tmp_path) == _ALL_FILES

    @pytest.mark.unit
    @pytest.mark.parametrize("config", [{"folder_ids": ["d1"]}, {"file_ids": ["f1"]}])
    def test_401_that_survives_the_refresh_raises(self, loader, tmp_path, config):
        from docsgpt.parser.connectors.base import ConnectorAuthError

        graph = _FakeGraph(loader.GRAPH_API_BASE, expire_after=3 if "folder_ids" in config else 0, rejected={"at2"})
        loader._refresh_rejected_token = MagicMock(return_value={"access_token": "at2", "expiry": 1})

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=graph.get):
            with pytest.raises(ConnectorAuthError, match="InvalidAuthenticationToken"):
                loader.download_to_directory(str(tmp_path), config)
        loader._refresh_rejected_token.assert_called_once_with("at")

    @pytest.mark.unit
    def test_failed_refresh_raises_with_the_cause(self, loader, tmp_path):
        from docsgpt.parser.connectors.base import ConnectorAuthError

        graph = _FakeGraph(loader.GRAPH_API_BASE, expire_after=3)
        refresh_error = ValueError("The provider rejected the stored sign-in")
        loader._refresh_rejected_token = MagicMock(side_effect=refresh_error)

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=graph.get):
            with pytest.raises(ConnectorAuthError) as excinfo:
                loader.download_to_directory(str(tmp_path), {"folder_ids": ["d1"]})
        assert excinfo.value.__cause__ is refresh_error

    @pytest.mark.unit
    def test_expired_token_that_cannot_be_refreshed_stops_the_walk(self, loader, tmp_path):
        from docsgpt.parser.connectors.base import ConnectorAuthError

        graph = _FakeGraph(loader.GRAPH_API_BASE)
        loader.auth.is_token_expired.side_effect = lambda info: len(graph.calls) >= 3

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=graph.get), patch(
            "docsgpt.connectors.service.get_valid_token_info", side_effect=RuntimeError("token endpoint down"),
        ):
            with pytest.raises(ConnectorAuthError):
                loader.download_to_directory(str(tmp_path), {"folder_ids": ["d1"]})
        assert len(graph.calls) == 3

    @pytest.mark.unit
    def test_other_errors_still_skip_only_that_file(self, loader, tmp_path):
        graph = _FakeGraph(loader.GRAPH_API_BASE)

        def get(url, **kwargs):
            if url.endswith("/f2/content"):
                return _graph_response(404, {"error": {"code": "itemNotFound"}})
            return graph.get(url, **kwargs)

        loader._refresh_rejected_token = MagicMock()
        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=get):
            result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["d1"]})

        loader._refresh_rejected_token.assert_not_called()
        assert result["files_downloaded"] == 4
        assert os.path.join("Docs", "f2.pdf") not in _downloaded(tmp_path)
        assert result["files_failed"] == 1

    @pytest.mark.unit
    def test_403_is_not_retried(self, loader):
        loader._refresh_rejected_token = MagicMock()
        with patch(
            "docsgpt.parser.connectors.share_point.loader.requests.get",
            return_value=_graph_response(403, {"error": {"code": "accessDenied"}}),
        ) as get:
            assert loader._download_file_content("f1") is None
        assert get.call_count == 1
        loader._refresh_rejected_token.assert_not_called()

    @pytest.mark.unit
    def test_401_logs_the_graph_error_and_challenge_without_the_token(self, loader, tmp_path, caplog):
        graph = _FakeGraph(loader.GRAPH_API_BASE, expire_after=3)
        loader._refresh_rejected_token = MagicMock(return_value={"access_token": "at2", "expiry": 1})

        with caplog.at_level("WARNING"), patch(
            "docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=graph.get,
        ):
            loader.download_to_directory(str(tmp_path), {"folder_ids": ["d1"]})

        assert "InvalidAuthenticationToken" in caplog.text
        assert "authorization_uri=" in caplog.text
        assert "Bearer at" not in caplog.text
        assert "at2" not in caplog.text

    @pytest.mark.unit
    @pytest.mark.parametrize("inputs", [
        {"file_ids": ["f1"]},
        {"folder_id": "d1"},
        {"folder_id": "d1", "search_query": "report"},
        {"shared": True},
    ])
    def test_browsing_raises_when_the_refreshed_token_is_rejected(self, loader_shared, inputs):
        from docsgpt.parser.connectors.base import ConnectorAuthError

        loader_shared._refresh_rejected_token = MagicMock(return_value={"access_token": "at2"})
        rejected = _graph_response(401, _GRAPH_401_BODY)
        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=rejected), patch(
            "docsgpt.parser.connectors.share_point.loader.requests.post", return_value=rejected,
        ):
            with pytest.raises(ConnectorAuthError):
                loader_shared.load_data(inputs)
        loader_shared._refresh_rejected_token.assert_called_once_with("at")

    @pytest.mark.unit
    def test_shared_search_post_retries_with_the_refreshed_token(self, loader_shared):
        drive = _graph_response(data={"webUrl": "https://contoso-my.sharepoint.com/personal/u"})
        search = _graph_response(data={"value": [{"hitsContainers": [{"total": 0, "hits": []}]}]})
        loader_shared._refresh_rejected_token = MagicMock(return_value={"access_token": "at2"})

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", return_value=drive), patch(
            "docsgpt.parser.connectors.share_point.loader.requests.post",
            side_effect=[_graph_response(401, _GRAPH_401_BODY), search],
        ) as post:
            assert loader_shared._list_shared_items() == []

        assert post.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer at2"
        assert post.call_args_list[1].kwargs["headers"]["Content-Type"] == "application/json"


class TestDownloadReportsWhatItLost:

    @staticmethod
    def _walk(loader, tmp_path):
        graph = _FakeGraph(loader.GRAPH_API_BASE)
        graph.pages["d1"][0].append({"id": "z1", "name": "site.zip", "file": {"mimeType": "application/zip"}})

        def get(url, **kwargs):
            if url.endswith("/z1"):
                graph.calls.append((url, None))
                return _graph_response(data={"id": "z1", "name": "site.zip", "file": {"mimeType": "application/zip"}})
            if url.endswith("/f2/content") or url.endswith("/s1/children"):
                graph.calls.append((url, None))
                return _graph_response(503, {"error": {"code": "serviceNotAvailable"}})
            return graph.get(url, **kwargs)

        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=get):
            return loader.download_to_directory(str(tmp_path), {"folder_ids": ["d1"]})

    @pytest.mark.unit
    def test_failed_files_and_folders_are_counted_apart_from_skipped_ones(self, loader, tmp_path):
        result = self._walk(loader, tmp_path)

        assert result["files_downloaded"] == 2
        assert result["files_failed"] == 1
        assert result["folders_failed"] == 1
        assert result["files_skipped"] == 1
        assert result["empty_result"] is False
        assert _downloaded(tmp_path) == [os.path.join("Docs", "f1.pdf"), os.path.join("Docs", "f3.pdf")]

    @pytest.mark.unit
    def test_an_unsupported_file_is_logged_at_info_and_the_walk_ends_with_one_summary(self, loader, tmp_path, caplog):
        with caplog.at_level("INFO"):
            self._walk(loader, tmp_path)

        zip_lines = [r for r in caplog.records if "site.zip" in r.getMessage()]
        assert zip_lines and all(r.levelname == "INFO" for r in zip_lines)
        summaries = [r.getMessage() for r in caplog.records if "downloaded=" in r.getMessage()]
        assert summaries == [
            "SharePoint/OneDrive download finished: downloaded=2 skipped=1 failed=1 folders_failed=1"
        ]

    @pytest.mark.unit
    def test_nothing_lost_reports_zero_failures(self, loader, tmp_path):
        graph = _FakeGraph(loader.GRAPH_API_BASE)
        with patch("docsgpt.parser.connectors.share_point.loader.requests.get", side_effect=graph.get):
            result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["d1"], "file_ids": ["f9"]})

        assert result["files_downloaded"] == 6
        assert (result["files_failed"], result["folders_failed"], result["files_skipped"]) == (0, 0, 0)
