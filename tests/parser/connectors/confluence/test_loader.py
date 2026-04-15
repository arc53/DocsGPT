"""Tests for application/parser/connectors/confluence/loader.py"""

import os
import tempfile
from unittest.mock import MagicMock, call, patch

import pytest
import requests

from application.parser.schema.base import Document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loader(token_info=None):
    """Create a ConfluenceLoader with mocked auth/session dependencies."""
    if token_info is None:
        token_info = {
            "access_token": "test_at",
            "refresh_token": "test_rt",
            "cloud_id": "test_cloud",
        }

    with patch("application.parser.connectors.confluence.loader.ConfluenceAuth") as MockAuth:
        mock_auth = MagicMock()
        mock_auth.get_token_info_from_session.return_value = token_info
        MockAuth.return_value = mock_auth

        from application.parser.connectors.confluence.loader import ConfluenceLoader
        loader = ConfluenceLoader("session_tok")

    loader.auth = mock_auth
    return loader


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        http_err = requests.exceptions.HTTPError(response=MagicMock(status_code=status_code))
        http_err.response = MagicMock(status_code=status_code)
        resp.raise_for_status.side_effect = http_err
    return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def loader():
    return _make_loader()


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestConfluenceLoaderInit:

    @pytest.mark.unit
    def test_init_sets_attributes(self, loader):
        assert loader.session_token == "session_tok"
        assert loader.access_token == "test_at"
        assert loader.refresh_token == "test_rt"
        assert loader.cloud_id == "test_cloud"
        assert loader.next_page_token is None
        assert "test_cloud" in loader.base_url
        assert "test_cloud" in loader.download_base

    @pytest.mark.unit
    def test_headers_include_bearer_token(self, loader):
        headers = loader._headers()
        assert headers["Authorization"] == "Bearer test_at"
        assert headers["Accept"] == "application/json"


# ---------------------------------------------------------------------------
# load_data routing
# ---------------------------------------------------------------------------


class TestLoadData:

    @pytest.mark.unit
    def test_load_data_with_file_ids(self, loader):
        loader._load_pages_by_ids = MagicMock(return_value=[MagicMock()])
        docs = loader.load_data({"file_ids": ["page1", "page2"]})
        loader._load_pages_by_ids.assert_called_once_with(
            ["page1", "page2"], False, None
        )
        assert len(docs) == 1

    @pytest.mark.unit
    def test_load_data_with_folder_id(self, loader):
        loader._list_pages_in_space = MagicMock(return_value=[MagicMock()])
        docs = loader.load_data({"folder_id": "space123"})
        loader._list_pages_in_space.assert_called_once_with(
            "space123", 100, False, None, None
        )
        assert len(docs) == 1

    @pytest.mark.unit
    def test_load_data_no_ids_lists_spaces(self, loader):
        loader._list_spaces = MagicMock(return_value=[MagicMock(), MagicMock()])
        docs = loader.load_data({})
        loader._list_spaces.assert_called_once_with(100, None, None)
        assert len(docs) == 2

    @pytest.mark.unit
    def test_load_data_resets_next_page_token(self, loader):
        loader.next_page_token = "old_token"
        loader._list_spaces = MagicMock(return_value=[])
        loader.load_data({})
        assert loader.next_page_token is None

    @pytest.mark.unit
    def test_load_data_passes_list_only(self, loader):
        loader._load_pages_by_ids = MagicMock(return_value=[])
        loader.load_data({"file_ids": ["p1"], "list_only": True})
        loader._load_pages_by_ids.assert_called_once_with(["p1"], True, None)

    @pytest.mark.unit
    def test_load_data_passes_page_token_and_search(self, loader):
        loader._list_pages_in_space = MagicMock(return_value=[])
        loader.load_data({
            "folder_id": "sp1",
            "page_token": "cursor123",
            "search_query": "test query",
        })
        loader._list_pages_in_space.assert_called_once_with(
            "sp1", 100, False, "cursor123", "test query"
        )


# ---------------------------------------------------------------------------
# _list_spaces
# ---------------------------------------------------------------------------


class TestListSpaces:

    @pytest.mark.unit
    def test_returns_documents_for_spaces(self, loader):
        data = {
            "results": [
                {"id": "s1", "name": "Engineering", "key": "ENG", "createdAt": "2025-01-01"},
                {"id": "s2", "name": "Design", "key": "DES", "createdAt": "2025-01-02"},
            ],
            "_links": {},
        }
        with patch("requests.get", return_value=_mock_response(data)):
            docs = loader._list_spaces(10, None, None)

        assert len(docs) == 2
        assert docs[0].doc_id == "s1"
        assert docs[0].extra_info["file_name"] == "Engineering"
        assert docs[0].extra_info["is_folder"] is True
        assert docs[0].extra_info["mime_type"] == "folder"

    @pytest.mark.unit
    def test_search_query_filters_spaces(self, loader):
        data = {
            "results": [
                {"id": "s1", "name": "Engineering", "key": "ENG"},
                {"id": "s2", "name": "Marketing", "key": "MKT"},
            ],
            "_links": {},
        }
        with patch("requests.get", return_value=_mock_response(data)):
            docs = loader._list_spaces(10, None, "marketing")

        assert len(docs) == 1
        assert docs[0].doc_id == "s2"

    @pytest.mark.unit
    def test_search_query_case_insensitive(self, loader):
        data = {
            "results": [
                {"id": "s1", "name": "Engineering", "key": "ENG"},
            ],
            "_links": {},
        }
        with patch("requests.get", return_value=_mock_response(data)):
            docs = loader._list_spaces(10, None, "ENGINEERING")

        assert len(docs) == 1

    @pytest.mark.unit
    def test_sets_next_page_token_from_links(self, loader):
        data = {
            "results": [{"id": "s1", "name": "Space1", "key": "S1"}],
            "_links": {
                "next": "/wiki/api/v2/spaces?cursor=next_cursor_val"
            },
        }
        with patch("requests.get", return_value=_mock_response(data)):
            loader._list_spaces(10, None, None)

        assert loader.next_page_token == "next_cursor_val"

    @pytest.mark.unit
    def test_no_next_link_sets_none(self, loader):
        data = {
            "results": [],
            "_links": {},
        }
        with patch("requests.get", return_value=_mock_response(data)):
            loader._list_spaces(10, None, None)

        assert loader.next_page_token is None

    @pytest.mark.unit
    def test_passes_cursor_param(self, loader):
        data = {"results": [], "_links": {}}
        with patch("requests.get", return_value=_mock_response(data)) as mock_get:
            loader._list_spaces(10, "my_cursor", None)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"].get("cursor") == "my_cursor"


# ---------------------------------------------------------------------------
# _list_pages_in_space
# ---------------------------------------------------------------------------


class TestListPagesInSpace:

    @pytest.mark.unit
    def test_returns_documents_for_pages(self, loader):
        data = {
            "results": [
                {
                    "id": "p1",
                    "title": "Getting Started",
                    "version": {"createdAt": "2025-01-01"},
                    "createdAt": "2024-12-01",
                },
            ],
            "_links": {},
        }
        with patch("requests.get", return_value=_mock_response(data)):
            docs = loader._list_pages_in_space("space1", 10, True, None, None)

        assert len(docs) == 1
        assert docs[0].doc_id == "p1"
        assert docs[0].extra_info["file_name"] == "Getting Started"
        assert docs[0].extra_info["is_folder"] is False

    @pytest.mark.unit
    def test_search_query_filters_pages(self, loader):
        data = {
            "results": [
                {"id": "p1", "title": "Getting Started"},
                {"id": "p2", "title": "Advanced Topics"},
            ],
            "_links": {},
        }
        with patch("requests.get", return_value=_mock_response(data)):
            docs = loader._list_pages_in_space("space1", 10, True, None, "advanced")

        assert len(docs) == 1
        assert docs[0].doc_id == "p2"

    @pytest.mark.unit
    def test_sets_next_page_token(self, loader):
        data = {
            "results": [],
            "_links": {"next": "/wiki/api/v2/spaces/s1/pages?cursor=pagetoken"},
        }
        with patch("requests.get", return_value=_mock_response(data)):
            loader._list_pages_in_space("space1", 10, True, None, None)

        assert loader.next_page_token == "pagetoken"

    @pytest.mark.unit
    def test_list_only_excludes_content(self, loader):
        data = {
            "results": [
                {"id": "p1", "title": "Page One", "body": {"storage": {"value": "CONTENT"}}},
            ],
            "_links": {},
        }
        with patch("requests.get", return_value=_mock_response(data)):
            docs = loader._list_pages_in_space("space1", 10, True, None, None)

        # list_only=True means load_content=False -> text should be ""
        assert docs[0].text == ""

    @pytest.mark.unit
    def test_passes_cursor_param(self, loader):
        data = {"results": [], "_links": {}}
        with patch("requests.get", return_value=_mock_response(data)) as mock_get:
            loader._list_pages_in_space("space1", 10, True, "my_cursor", None)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"].get("cursor") == "my_cursor"


# ---------------------------------------------------------------------------
# _load_pages_by_ids
# ---------------------------------------------------------------------------


class TestLoadPagesByIds:

    @pytest.mark.unit
    def test_loads_single_page(self, loader):
        page_data = {
            "id": "p1",
            "title": "My Page",
            "body": {"storage": {"value": "<p>Hello</p>"}},
            "version": {"createdAt": "2025-01-01"},
        }
        with patch("requests.get", return_value=_mock_response(page_data)):
            docs = loader._load_pages_by_ids(["p1"], False, None)

        assert len(docs) == 1
        assert docs[0].doc_id == "p1"
        assert docs[0].text == "<p>Hello</p>"

    @pytest.mark.unit
    def test_list_only_returns_empty_text(self, loader):
        page_data = {
            "id": "p1",
            "title": "My Page",
            "body": {"storage": {"value": "<p>Hello</p>"}},
        }
        with patch("requests.get", return_value=_mock_response(page_data)):
            docs = loader._load_pages_by_ids(["p1"], True, None)

        assert docs[0].text == ""

    @pytest.mark.unit
    def test_search_query_filters_pages(self, loader):
        page1 = {"id": "p1", "title": "Getting Started"}
        page2 = {"id": "p2", "title": "Advanced Guide"}

        with patch("requests.get", side_effect=[_mock_response(page1), _mock_response(page2)]):
            docs = loader._load_pages_by_ids(["p1", "p2"], True, "advanced")

        assert len(docs) == 1
        assert docs[0].doc_id == "p2"

    @pytest.mark.unit
    def test_http_error_skips_page(self, loader):
        err_resp = _mock_response({}, status_code=404)

        with patch("requests.get", return_value=err_resp):
            docs = loader._load_pages_by_ids(["bad_id"], False, None)

        assert docs == []

    @pytest.mark.unit
    def test_loads_multiple_pages(self, loader):
        page1 = {"id": "p1", "title": "Page 1", "body": {"storage": {"value": "text1"}}}
        page2 = {"id": "p2", "title": "Page 2", "body": {"storage": {"value": "text2"}}}

        with patch("requests.get", side_effect=[_mock_response(page1), _mock_response(page2)]):
            docs = loader._load_pages_by_ids(["p1", "p2"], False, None)

        assert len(docs) == 2


# ---------------------------------------------------------------------------
# _page_to_document
# ---------------------------------------------------------------------------


class TestPageToDocument:

    @pytest.mark.unit
    def test_basic_page_metadata(self, loader):
        page = {
            "id": "p1",
            "title": "Test Page",
            "createdAt": "2024-01-01",
            "version": {"createdAt": "2025-01-01"},
            "spaceId": "s1",
        }
        doc = loader._page_to_document(page, load_content=False)

        assert doc.doc_id == "p1"
        assert doc.extra_info["file_name"] == "Test Page"
        assert doc.extra_info["is_folder"] is False
        assert doc.extra_info["source"] == "confluence"
        assert doc.extra_info["mime_type"] == "text/html"
        assert doc.extra_info["created_time"] == "2024-01-01"
        assert doc.extra_info["modified_time"] == "2025-01-01"
        assert doc.extra_info["cloud_id"] == "test_cloud"
        assert doc.extra_info["space_id"] == "s1"

    @pytest.mark.unit
    def test_loads_body_when_load_content_true(self, loader):
        page = {
            "id": "p1",
            "title": "Page",
            "body": {"storage": {"value": "<p>content</p>"}},
        }
        doc = loader._page_to_document(page, load_content=True)
        assert doc.text == "<p>content</p>"

    @pytest.mark.unit
    def test_empty_text_when_load_content_false(self, loader):
        page = {
            "id": "p1",
            "title": "Page",
            "body": {"storage": {"value": "<p>content</p>"}},
        }
        doc = loader._page_to_document(page, load_content=False)
        assert doc.text == ""

    @pytest.mark.unit
    def test_size_set_from_text_length(self, loader):
        text = "<p>content</p>"
        page = {
            "id": "p1",
            "title": "Page",
            "body": {"storage": {"value": text}},
        }
        doc = loader._page_to_document(page, load_content=True)
        assert doc.extra_info["size"] == len(text)

    @pytest.mark.unit
    def test_size_none_when_no_content(self, loader):
        page = {"id": "p1", "title": "Page"}
        doc = loader._page_to_document(page, load_content=False)
        assert doc.extra_info["size"] is None

    @pytest.mark.unit
    def test_space_id_from_param_takes_precedence(self, loader):
        page = {"id": "p1", "title": "Page", "spaceId": "page_space"}
        doc = loader._page_to_document(page, load_content=False, space_id="override_space")
        assert doc.extra_info["space_id"] == "override_space"

    @pytest.mark.unit
    def test_version_not_dict_sets_none_modified_time(self, loader):
        page = {"id": "p1", "title": "Page", "version": "1"}
        doc = loader._page_to_document(page, load_content=False)
        assert doc.extra_info["modified_time"] is None

    @pytest.mark.unit
    def test_body_not_dict_produces_empty_text(self, loader):
        page = {"id": "p1", "title": "Page", "body": "raw_string"}
        doc = loader._page_to_document(page, load_content=True)
        assert doc.text == ""


# ---------------------------------------------------------------------------
# _extract_cursor (static method)
# ---------------------------------------------------------------------------


class TestExtractCursor:

    @pytest.mark.unit
    def test_extracts_cursor_from_link(self):
        from application.parser.connectors.confluence.loader import ConfluenceLoader
        link = "/wiki/api/v2/spaces?limit=10&cursor=abc123"
        result = ConfluenceLoader._extract_cursor(link)
        assert result == "abc123"

    @pytest.mark.unit
    def test_returns_none_for_no_link(self):
        from application.parser.connectors.confluence.loader import ConfluenceLoader
        assert ConfluenceLoader._extract_cursor(None) is None

    @pytest.mark.unit
    def test_returns_none_for_link_without_cursor(self):
        from application.parser.connectors.confluence.loader import ConfluenceLoader
        link = "/wiki/api/v2/spaces?limit=10"
        assert ConfluenceLoader._extract_cursor(link) is None

    @pytest.mark.unit
    def test_returns_first_cursor_value(self):
        from application.parser.connectors.confluence.loader import ConfluenceLoader
        link = "/wiki/api/v2/spaces?cursor=val1&cursor=val2"
        result = ConfluenceLoader._extract_cursor(link)
        assert result == "val1"


# ---------------------------------------------------------------------------
# download_to_directory
# ---------------------------------------------------------------------------


class TestDownloadToDirectory:

    @pytest.mark.unit
    def test_creates_directory(self, loader):
        loader._download_page = MagicMock(return_value=True)
        loader._download_page_attachments = MagicMock(return_value=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "confluence_out")
            result = loader.download_to_directory(
                target, {"file_ids": ["p1"], "folder_ids": []}
            )

        assert result["source_type"] == "confluence"
        assert result["files_downloaded"] == 1

    @pytest.mark.unit
    def test_empty_result_when_nothing_downloaded(self, loader):
        loader._download_page = MagicMock(return_value=False)
        loader._download_page_attachments = MagicMock(return_value=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "confluence_out")
            result = loader.download_to_directory(
                target, {"file_ids": ["p1"], "folder_ids": []}
            )

        assert result["empty_result"] is True
        assert result["files_downloaded"] == 0

    @pytest.mark.unit
    def test_string_file_ids_converted_to_list(self, loader):
        loader._download_page = MagicMock(return_value=True)
        loader._download_page_attachments = MagicMock(return_value=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "out")
            result = loader.download_to_directory(
                target, {"file_ids": "p1", "folder_ids": "sp1"}
            )

        loader._download_page.assert_called_once_with("p1", target)
        assert result["files_downloaded"] == 1

    @pytest.mark.unit
    def test_folder_ids_trigger_download_space(self, loader):
        loader._download_space = MagicMock(return_value=5)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "out")
            result = loader.download_to_directory(
                target, {"file_ids": [], "folder_ids": ["space1"]}
            )

        loader._download_space.assert_called_once_with("space1", target)
        assert result["files_downloaded"] == 5

    @pytest.mark.unit
    def test_attachments_counted(self, loader):
        loader._download_page = MagicMock(return_value=True)
        loader._download_page_attachments = MagicMock(return_value=3)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "out")
            result = loader.download_to_directory(
                target, {"file_ids": ["p1"], "folder_ids": []}
            )

        assert result["files_downloaded"] == 4  # 1 page + 3 attachments

    @pytest.mark.unit
    def test_uses_self_config_when_no_source_config(self, loader):
        loader.config = {"file_ids": ["p2"], "folder_ids": []}
        loader._download_page = MagicMock(return_value=True)
        loader._download_page_attachments = MagicMock(return_value=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "out")
            loader.download_to_directory(target)

        loader._download_page.assert_called_with("p2", target)


# ---------------------------------------------------------------------------
# _download_page
# ---------------------------------------------------------------------------


class TestDownloadPage:

    @pytest.mark.unit
    def test_downloads_and_writes_file(self, loader):
        page_data = {
            "id": "p1",
            "title": "My Page",
            "body": {"storage": {"value": "<p>Content here</p>"}},
        }
        with patch("requests.get", return_value=_mock_response(page_data)):
            with tempfile.TemporaryDirectory() as tmpdir:
                result = loader._download_page("p1", tmpdir)
                assert result is True
                # Check file was created
                files = os.listdir(tmpdir)
                assert len(files) == 1
                assert files[0].endswith(".html")

    @pytest.mark.unit
    def test_returns_false_on_http_error(self, loader):
        err_resp = _mock_response({}, status_code=404)
        with patch("requests.get", return_value=err_resp):
            with tempfile.TemporaryDirectory() as tmpdir:
                result = loader._download_page("bad_id", tmpdir)
        assert result is False

    @pytest.mark.unit
    def test_sanitizes_filename(self, loader):
        page_data = {
            "id": "p1",
            "title": "File/With:Special*Chars",
            "body": {"storage": {"value": "content"}},
        }
        with patch("requests.get", return_value=_mock_response(page_data)):
            with tempfile.TemporaryDirectory() as tmpdir:
                loader._download_page("p1", tmpdir)
                files = os.listdir(tmpdir)
                assert len(files) == 1
                # Special chars should be replaced with underscores
                assert "/" not in files[0]
                assert ":" not in files[0]


# ---------------------------------------------------------------------------
# _download_page_attachments
# ---------------------------------------------------------------------------


class TestDownloadPageAttachments:

    @pytest.mark.unit
    def test_downloads_supported_attachment(self, loader):
        att_data = {
            "results": [
                {
                    "id": "att1",
                    "title": "doc.pdf",
                    "mediaType": "application/pdf",
                    "_links": {"download": "/download/att1"},
                }
            ],
            "_links": {},  # no cursor
        }
        file_content = b"PDF content bytes"
        att_resp = _mock_response(att_data)
        file_resp = MagicMock()
        file_resp.raise_for_status = MagicMock()
        file_resp.iter_content = MagicMock(return_value=[file_content])

        with patch("requests.get", side_effect=[att_resp, file_resp]):
            with tempfile.TemporaryDirectory() as tmpdir:
                count = loader._download_page_attachments("p1", tmpdir)

        assert count == 1

    @pytest.mark.unit
    def test_skips_unsupported_media_type(self, loader):
        att_data = {
            "results": [
                {
                    "id": "att1",
                    "title": "file.xyz",
                    "mediaType": "application/unknown",
                    "_links": {"download": "/download/att1"},
                }
            ],
            "_links": {},
        }
        with patch("requests.get", return_value=_mock_response(att_data)):
            with tempfile.TemporaryDirectory() as tmpdir:
                count = loader._download_page_attachments("p1", tmpdir)

        assert count == 0

    @pytest.mark.unit
    def test_skips_attachment_without_download_link(self, loader):
        att_data = {
            "results": [
                {
                    "id": "att1",
                    "title": "doc.pdf",
                    "mediaType": "application/pdf",
                    "_links": {},  # no download key
                }
            ],
            "_links": {},
        }
        with patch("requests.get", return_value=_mock_response(att_data)):
            with tempfile.TemporaryDirectory() as tmpdir:
                count = loader._download_page_attachments("p1", tmpdir)

        assert count == 0

    @pytest.mark.unit
    def test_paginated_attachments_follows_cursor(self, loader):
        page1 = {
            "results": [
                {
                    "id": "att1",
                    "title": "doc1.pdf",
                    "mediaType": "application/pdf",
                    "_links": {"download": "/d/att1"},
                }
            ],
            "_links": {"next": "/attachments?cursor=page2_cursor"},
        }
        page2 = {
            "results": [
                {
                    "id": "att2",
                    "title": "doc2.pdf",
                    "mediaType": "application/pdf",
                    "_links": {"download": "/d/att2"},
                }
            ],
            "_links": {},  # no more pages
        }
        file_resp1 = MagicMock()
        file_resp1.raise_for_status = MagicMock()
        file_resp1.iter_content = MagicMock(return_value=[b"data1"])
        file_resp2 = MagicMock()
        file_resp2.raise_for_status = MagicMock()
        file_resp2.iter_content = MagicMock(return_value=[b"data2"])

        with patch("requests.get", side_effect=[
            _mock_response(page1), file_resp1,
            _mock_response(page2), file_resp2,
        ]):
            with tempfile.TemporaryDirectory() as tmpdir:
                count = loader._download_page_attachments("p1", tmpdir)

        assert count == 2

    @pytest.mark.unit
    def test_error_during_listing_returns_zero(self, loader):
        err_resp = _mock_response({}, status_code=500)
        with patch("requests.get", return_value=err_resp):
            with tempfile.TemporaryDirectory() as tmpdir:
                count = loader._download_page_attachments("p1", tmpdir)

        assert count == 0


# ---------------------------------------------------------------------------
# _download_space
# ---------------------------------------------------------------------------


class TestDownloadSpace:

    @pytest.mark.unit
    def test_downloads_all_pages_in_space(self, loader):
        pages_data = {
            "results": [
                {"id": "p1"},
                {"id": "p2"},
            ],
            "_links": {},  # no more pages
        }
        loader._download_page = MagicMock(return_value=True)
        loader._download_page_attachments = MagicMock(return_value=0)

        with patch("requests.get", return_value=_mock_response(pages_data)):
            with tempfile.TemporaryDirectory() as tmpdir:
                count = loader._download_space("space1", tmpdir)

        assert count == 2
        assert loader._download_page.call_count == 2

    @pytest.mark.unit
    def test_follows_pagination_cursor(self, loader):
        page1 = {
            "results": [{"id": "p1"}],
            "_links": {"next": "/spaces/s1/pages?cursor=next_page"},
        }
        page2 = {
            "results": [{"id": "p2"}],
            "_links": {},
        }
        loader._download_page = MagicMock(return_value=True)
        loader._download_page_attachments = MagicMock(return_value=0)

        with patch("requests.get", side_effect=[_mock_response(page1), _mock_response(page2)]):
            with tempfile.TemporaryDirectory() as tmpdir:
                count = loader._download_space("space1", tmpdir)

        assert count == 2

    @pytest.mark.unit
    def test_error_during_listing_breaks_loop(self, loader):
        err_resp = _mock_response({}, status_code=500)
        loader._download_page = MagicMock(return_value=False)

        with patch("requests.get", return_value=err_resp):
            with tempfile.TemporaryDirectory() as tmpdir:
                count = loader._download_space("bad_space", tmpdir)

        assert count == 0


# ---------------------------------------------------------------------------
# _retry_on_auth_failure decorator
# ---------------------------------------------------------------------------


class TestRetryOnAuthFailure:

    @pytest.mark.unit
    def test_retries_on_401(self, loader):
        """On 401, should refresh token and retry the function."""
        call_count = {"n": 0}

        def flaky_request(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                resp = MagicMock()
                resp.status_code = 401
                err = requests.exceptions.HTTPError(response=resp)
                err.response = resp
                raise err
            # Second call succeeds
            return _mock_response({"results": [], "_links": {}})

        loader.auth.refresh_access_token = MagicMock(return_value={
            "access_token": "new_at",
            "refresh_token": "new_rt",
        })
        loader._persist_refreshed_tokens = MagicMock()

        with patch("requests.get", side_effect=flaky_request):
            docs = loader.load_data({})

        assert loader.auth.refresh_access_token.called
        assert loader.access_token == "new_at"
        assert loader._persist_refreshed_tokens.called

    @pytest.mark.unit
    def test_raises_non_auth_http_error(self, loader):
        """Non-401/403 HTTP errors should propagate immediately."""
        resp = MagicMock()
        resp.status_code = 500
        err = requests.exceptions.HTTPError(response=resp)
        err.response = resp

        with patch("requests.get", side_effect=err):
            with pytest.raises(requests.exceptions.HTTPError):
                loader.load_data({})

    @pytest.mark.unit
    def test_raises_when_refresh_fails(self, loader):
        """When refresh itself fails, raise ValueError."""
        resp = MagicMock()
        resp.status_code = 401
        err = requests.exceptions.HTTPError(response=resp)
        err.response = resp

        loader.auth.refresh_access_token = MagicMock(
            side_effect=Exception("refresh failed")
        )

        with patch("requests.get", side_effect=err):
            with pytest.raises(ValueError, match="Authentication failed"):
                loader.load_data({})

    @pytest.mark.unit
    def test_retries_on_403(self, loader):
        """403 should also trigger the refresh-and-retry path."""
        call_count = {"n": 0}

        def flaky(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                resp = MagicMock()
                resp.status_code = 403
                err = requests.exceptions.HTTPError(response=resp)
                err.response = resp
                raise err
            return _mock_response({"results": [], "_links": {}})

        loader.auth.refresh_access_token = MagicMock(return_value={
            "access_token": "new_at",
            "refresh_token": "new_rt",
        })
        loader._persist_refreshed_tokens = MagicMock()

        with patch("requests.get", side_effect=flaky):
            loader.load_data({})

        assert loader.auth.refresh_access_token.called


# ---------------------------------------------------------------------------
# _persist_refreshed_tokens
# ---------------------------------------------------------------------------


class TestPersistRefreshedTokens:

    @pytest.mark.unit
    def test_updates_mongo_session(self, loader):
        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_client = {"test_db": mock_db}

        mock_settings = MagicMock()
        mock_settings.MONGO_DB_NAME = "test_db"

        loader.auth.sanitize_token_info = MagicMock(return_value={"access_token": "new"})

        with patch("application.core.mongo_db.MongoDB.get_client", return_value=mock_client), \
             patch("application.core.settings.settings", mock_settings):
            loader._persist_refreshed_tokens({"access_token": "new", "refresh_token": "rt"})

        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {"session_token": "session_tok"}

    @pytest.mark.unit
    def test_logs_warning_on_failure(self, loader):
        loader.auth.sanitize_token_info = MagicMock(side_effect=Exception("db error"))

        # Should not raise, just log a warning
        loader._persist_refreshed_tokens({"access_token": "at"})
