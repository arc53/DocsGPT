"""Tests for SharePointLoader."""

import os
from unittest.mock import MagicMock, patch

import pytest
import requests as real_requests

from application.parser.schema.base import Document


def _make_loader(access_token="at", refresh_token="rt", allows_shared=False):
    """Create a SharePointLoader with mocked dependencies."""
    with patch("application.parser.connectors.share_point.loader.SharePointAuth") as MockAuth:
        mock_auth = MagicMock()
        mock_auth.get_token_info_from_session.return_value = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "allows_shared_content": allows_shared,
        }
        mock_auth.is_token_expired.return_value = False
        MockAuth.return_value = mock_auth

        from application.parser.connectors.share_point.loader import SharePointLoader
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
        assert loader.refresh_token == "rt"
        assert loader.allows_shared_content is False
        assert loader.next_page_token is None

    @pytest.mark.unit
    def test_no_access_token_raises(self):
        with patch("application.parser.connectors.share_point.loader.SharePointAuth") as MockAuth:
            mock_auth = MagicMock()
            mock_auth.get_token_info_from_session.return_value = {
                "access_token": None,
                "refresh_token": "rt",
            }
            MockAuth.return_value = mock_auth

            from application.parser.connectors.share_point.loader import SharePointLoader
            with pytest.raises(ValueError, match="No access token"):
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
        loader.auth.refresh_access_token.return_value = {"access_token": "new_at"}
        loader._ensure_valid_token()
        assert loader.access_token == "new_at"

    @pytest.mark.unit
    def test_refresh_failure_raises(self, loader):
        loader.auth.is_token_expired.return_value = True
        loader.auth.refresh_access_token.side_effect = Exception("fail")
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

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            doc = loader._load_file_by_id("f1")
        assert doc is not None

    @pytest.mark.unit
    def test_http_error_retries_with_refresh(self, loader):
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401

        http_error = real_requests.exceptions.HTTPError(response=mock_resp_401)

        mock_resp_ok = MagicMock()
        mock_resp_ok.json.return_value = {"id": "f1", "name": "t.pdf", "file": {"mimeType": "application/pdf"}}
        mock_resp_ok.raise_for_status = MagicMock()

        call_count = [0]
        def get_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise http_error
            return mock_resp_ok

        loader._process_file = MagicMock(return_value=Document(text="", doc_id="f1", extra_info={}))
        loader.auth.refresh_access_token.return_value = {"access_token": "new_at"}

        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=get_side_effect):
            doc = loader._load_file_by_id("f1")
        assert doc is not None

    @pytest.mark.unit
    def test_general_exception_returns_none(self, loader):
        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
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

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            docs = loader._list_items_in_parent("root")
        assert len(docs) == 2
        assert docs[0].extra_info["is_folder"] is True

    @pytest.mark.unit
    def test_search_query_uses_search_url(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": []}
        mock_response.raise_for_status = MagicMock()

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response) as mock_get:
            loader._list_items_in_parent("root", search_query="report")
            call_url = mock_get.call_args[0][0]
            assert "search" in call_url

    @pytest.mark.unit
    def test_search_with_drive_id(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": []}
        mock_response.raise_for_status = MagicMock()

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response) as mock_get:
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

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            loader._list_items_in_parent("root")
        assert loader.next_page_token == "abc123"

    @pytest.mark.unit
    def test_no_next_link_clears_token(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": []}
        mock_response.raise_for_status = MagicMock()

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
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

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            docs = loader._list_items_in_parent("root", limit=3)
        assert len(docs) == 3

    @pytest.mark.unit
    def test_page_token_passed_as_skip_token(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": []}
        mock_response.raise_for_status = MagicMock()

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response) as mock_get:
            loader._list_items_in_parent("root", page_token="tok123")
            call_kwargs = mock_get.call_args[1]
            assert call_kwargs["params"]["$skipToken"] == "tok123"

    @pytest.mark.unit
    def test_exception_returns_partial(self, loader):
        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
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

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            loader._list_items_in_parent("root")
        assert loader.next_page_token is None


class TestDownloadFileContent:

    @pytest.mark.unit
    def test_downloads_and_decodes(self, loader):
        mock_response = MagicMock()
        mock_response.content = b"file content"
        mock_response.raise_for_status = MagicMock()

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            content = loader._download_file_content("f1")
        assert content == "file content"

    @pytest.mark.unit
    def test_unicode_decode_error_returns_none(self, loader):
        mock_response = MagicMock()
        mock_response.content = MagicMock()
        mock_response.content.decode.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "bad")
        mock_response.raise_for_status = MagicMock()

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            result = loader._download_file_content("f1")
        assert result is None

    @pytest.mark.unit
    def test_general_exception_returns_none(self, loader):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
            result = loader._download_file_content("f1")
        assert result is None

    @pytest.mark.unit
    def test_http_401_retries_with_refresh(self, loader):
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401
        http_error = real_requests.exceptions.HTTPError(response=mock_resp_401)

        mock_resp_ok = MagicMock()
        mock_resp_ok.content = b"content after refresh"
        mock_resp_ok.raise_for_status = MagicMock()

        call_count = [0]
        def get_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise http_error
            return mock_resp_ok

        loader.auth.refresh_access_token.return_value = {"access_token": "new_at"}

        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=get_side_effect):
            content = loader._download_file_content("f1")
        assert content == "content after refresh"


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

        with patch("application.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
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

        with patch("application.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
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

        with patch("application.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
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

        with patch("application.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
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

        with patch("application.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
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

        with patch("application.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items(page_token="-5", load_content=False)
        assert len(docs) == 1

    @pytest.mark.unit
    def test_empty_search_response(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        mock_response = MagicMock()
        mock_response.json.return_value = {"value": []}
        mock_response.raise_for_status = MagicMock()

        with patch("application.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
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

        with patch("application.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
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

        with patch("application.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
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

        with patch("application.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            docs = loader_shared._list_shared_items(load_content=True)
        assert len(docs) == 1
        assert docs[0].text == "content"

    @pytest.mark.unit
    def test_exception_returns_empty(self, loader_shared):
        loader_shared._get_user_drive_web_url = MagicMock(return_value=None)

        with patch("application.parser.connectors.share_point.loader.requests.post", side_effect=Exception("fail")):
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

        with patch("application.parser.connectors.share_point.loader.requests.post", return_value=mock_response):
            loader_shared._list_shared_items(limit=100, load_content=False)
        assert loader_shared.next_page_token is None


class TestGetUserDriveWebUrl:

    @pytest.mark.unit
    def test_returns_web_url(self, loader):
        mock_response = MagicMock()
        mock_response.json.return_value = {"webUrl": "https://user.sharepoint.com/drive"}
        mock_response.raise_for_status = MagicMock()

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            url = loader._get_user_drive_web_url()
        assert url == "https://user.sharepoint.com/drive"

    @pytest.mark.unit
    def test_exception_returns_none(self, loader):
        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
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
        loader._download_file_to_directory = MagicMock(return_value=True)
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1", "f2"]})
        assert result["files_downloaded"] == 2
        assert result["source_type"] == "share_point"

    @pytest.mark.unit
    def test_download_files_string_id(self, loader, tmp_path):
        loader._download_file_to_directory = MagicMock(return_value=True)
        result = loader.download_to_directory(str(tmp_path), {"file_ids": "single"})
        assert result["files_downloaded"] == 1

    @pytest.mark.unit
    def test_download_folders(self, loader, tmp_path):
        mock_response = MagicMock()
        mock_response.json.return_value = {"name": "MyFolder"}
        mock_response.raise_for_status = MagicMock()

        loader._download_folder_recursive = MagicMock(return_value=3)

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["folder1"]})
        assert result["files_downloaded"] == 3

    @pytest.mark.unit
    def test_download_folders_string_id(self, loader, tmp_path):
        mock_response = MagicMock()
        mock_response.json.return_value = {"name": "F"}
        mock_response.raise_for_status = MagicMock()

        loader._download_folder_recursive = MagicMock(return_value=1)

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
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

        loader._download_file_to_directory = MagicMock(return_value=True)

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1"], "folder_ids": ["bad"]})
        assert result["files_downloaded"] == 1


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

        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=[mock_meta_resp, mock_dl_resp]):
            result = loader._download_single_file("f1", str(tmp_path))
        assert result is True
        assert os.path.exists(os.path.join(str(tmp_path), "test.pdf"))

    @pytest.mark.unit
    def test_unsupported_returns_false(self, loader, tmp_path):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "name": "test.zip", "file": {"mimeType": "application/zip"}
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_resp):
            result = loader._download_single_file("f1", str(tmp_path))
        assert result is False

    @pytest.mark.unit
    def test_exception_returns_false(self, loader, tmp_path):
        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
            result = loader._download_single_file("f1", str(tmp_path))
        assert result is False


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

        loader._download_single_file = MagicMock(return_value=True)

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            count = loader._download_folder_recursive("folder1", str(tmp_path))
        assert count == 1

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

        loader._download_single_file = MagicMock(return_value=True)

        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=get_side_effect):
            count = loader._download_folder_recursive("folder1", str(tmp_path), recursive=True)
        assert count == 2

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

        loader._download_single_file = MagicMock(return_value=True)

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            count = loader._download_folder_recursive("folder1", str(tmp_path), recursive=False)
        assert count == 1

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

        loader._download_single_file = MagicMock(side_effect=[False, True])

        with patch("application.parser.connectors.share_point.loader.requests.get", return_value=mock_response):
            count = loader._download_folder_recursive("folder1", str(tmp_path))
        assert count == 1

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

        loader._download_single_file = MagicMock(return_value=True)

        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=get_side_effect):
            count = loader._download_folder_recursive("folder1", str(tmp_path))
        assert count == 2

    @pytest.mark.unit
    def test_exception_returns_partial(self, loader, tmp_path):
        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=Exception("fail")):
            count = loader._download_folder_recursive("folder1", str(tmp_path))
        assert count == 0


class TestDownloadFileToDirectory:

    @pytest.mark.unit
    def test_delegates_to_download_single(self, loader, tmp_path):
        loader._download_single_file = MagicMock(return_value=True)
        assert loader._download_file_to_directory("f1", str(tmp_path)) is True

    @pytest.mark.unit
    def test_exception_returns_false(self, loader, tmp_path):
        loader._download_single_file = MagicMock(side_effect=Exception("fail"))
        # _download_file_to_directory calls _ensure_valid_token first, which may raise
        # but the method wraps everything in try/except
        assert loader._download_file_to_directory("f1", str(tmp_path)) is False


class TestDownloadFolderContents:

    @pytest.mark.unit
    def test_delegates_to_recursive(self, loader, tmp_path):
        loader._download_folder_recursive = MagicMock(return_value=5)
        count = loader._download_folder_contents("folder1", str(tmp_path))
        assert count == 5

    @pytest.mark.unit
    def test_exception_returns_zero(self, loader, tmp_path):
        loader.auth.is_token_expired.side_effect = Exception("fail")
        count = loader._download_folder_contents("folder1", str(tmp_path))
        assert count == 0


class TestRetryOnAuthFailureDecorator:

    @pytest.mark.unit
    def test_retries_on_401(self, loader):
        """The _retry_on_auth_failure decorator should retry after refreshing on 401."""
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401
        http_error = real_requests.exceptions.HTTPError(response=mock_resp_401)

        mock_resp_ok = MagicMock()
        mock_resp_ok.content = b"ok"
        mock_resp_ok.raise_for_status = MagicMock()

        call_count = [0]
        def get_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise http_error
            return mock_resp_ok

        loader.auth.refresh_access_token.return_value = {"access_token": "new_at"}

        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=get_side_effect):
            content = loader._download_file_content("f1")
        assert content == "ok"
        assert loader.access_token == "new_at"

    @pytest.mark.unit
    def test_refresh_failure_raises_valueerror(self, loader):
        """If token refresh fails during retry, should raise ValueError."""
        mock_resp_403 = MagicMock()
        mock_resp_403.status_code = 403
        http_error = real_requests.exceptions.HTTPError(response=mock_resp_403)

        loader.auth.refresh_access_token.side_effect = Exception("refresh fail")

        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=http_error):
            with pytest.raises(ValueError, match="could not be refreshed"):
                loader._download_file_content("f1")

    @pytest.mark.unit
    def test_non_auth_http_error_not_retried(self, loader):
        """Non-401/403 HTTP errors should not trigger retry."""
        mock_resp_500 = MagicMock()
        mock_resp_500.status_code = 500
        http_error = real_requests.exceptions.HTTPError(response=mock_resp_500)

        with patch("application.parser.connectors.share_point.loader.requests.get", side_effect=http_error):
            with pytest.raises(real_requests.exceptions.HTTPError):
                loader._download_file_content("f1")
