"""Tests for GoogleDriveLoader."""

import copy
import json
from unittest.mock import MagicMock, patch

import httplib2
import pytest
from googleapiclient.errors import HttpError

from tests.parser.connectors.token_patch import patch_tokens

from docsgpt.parser.schema.base import Document


def _make_loader(service=None):
    """Create a GoogleDriveLoader with mocked dependencies."""
    with patch("docsgpt.parser.connectors.google_drive.loader.GoogleDriveAuth") as MockAuth:
        mock_auth = MagicMock()
        token_info = {
            "access_token": "at",
            "refresh_token": "rt",
        }
        mock_creds = MagicMock()
        mock_creds.token = "at"
        mock_creds.expired = False
        mock_creds.refresh_token = "rt"
        mock_auth.create_credentials_from_token_info.return_value = mock_creds
        mock_auth.build_drive_service.return_value = service or MagicMock()
        MockAuth.return_value = mock_auth

        from docsgpt.parser.connectors.google_drive.loader import GoogleDriveLoader
        with patch_tokens(token_info):
            loader = GoogleDriveLoader("session_tok")
    return loader


@pytest.fixture
def mock_service():
    return MagicMock()


@pytest.fixture
def loader(mock_service):
    return _make_loader(mock_service)


class TestGoogleDriveLoaderInit:

    @pytest.mark.unit
    def test_init_sets_attributes(self, loader):
        assert loader.session_token == "session_tok"
        assert loader.credentials is not None
        assert loader.service is not None
        assert loader.next_page_token is None

    @pytest.mark.unit
    def test_init_service_failure_sets_none(self):
        with patch("docsgpt.parser.connectors.google_drive.loader.GoogleDriveAuth") as MockAuth:
            mock_auth = MagicMock()
            token_info = {
                "access_token": "at", "refresh_token": "rt"
            }
            mock_creds = MagicMock()
            mock_creds.token = "at"
            mock_auth.create_credentials_from_token_info.return_value = mock_creds
            mock_auth.build_drive_service.side_effect = Exception("service fail")
            MockAuth.return_value = mock_auth

            from docsgpt.parser.connectors.google_drive.loader import GoogleDriveLoader
            with patch_tokens(token_info):
                loader = GoogleDriveLoader("st")
            assert loader.service is None


class TestProcessFile:

    @pytest.mark.unit
    def test_supported_mime_type_with_content(self, loader):
        loader._download_file_content = MagicMock(return_value="file content")
        metadata = {
            "id": "f1",
            "name": "test.pdf",
            "mimeType": "application/pdf",
            "size": 1024,
            "createdTime": "2025-01-01T00:00:00Z",
            "modifiedTime": "2025-01-02T00:00:00Z",
            "parents": ["root"],
        }
        doc = loader._process_file(metadata, load_content=True)
        assert doc is not None
        assert doc.text == "file content"
        assert doc.doc_id == "f1"
        assert doc.extra_info["file_name"] == "test.pdf"
        assert doc.extra_info["source"] == "google_drive"

    @pytest.mark.unit
    def test_supported_mime_type_no_content(self, loader):
        metadata = {
            "id": "f1",
            "name": "test.pdf",
            "mimeType": "application/pdf",
        }
        doc = loader._process_file(metadata, load_content=False)
        assert doc is not None
        assert doc.text == ""
        assert doc.doc_id == "f1"

    @pytest.mark.unit
    def test_unsupported_mime_type_returns_none(self, loader):
        metadata = {
            "id": "f1",
            "name": "test.zip",
            "mimeType": "application/zip",
        }
        doc = loader._process_file(metadata)
        assert doc is None

    @pytest.mark.unit
    def test_download_failure_returns_none(self, loader):
        loader._download_file_content = MagicMock(return_value=None)
        metadata = {
            "id": "f1",
            "name": "test.txt",
            "mimeType": "text/plain",
        }
        doc = loader._process_file(metadata, load_content=True)
        assert doc is None

    @pytest.mark.unit
    def test_exception_returns_none(self, loader):
        loader._download_file_content = MagicMock(side_effect=Exception("fail"))
        metadata = {
            "id": "f1",
            "name": "test.txt",
            "mimeType": "text/plain",
        }
        doc = loader._process_file(metadata, load_content=True)
        assert doc is None


class TestLoadData:

    @pytest.mark.unit
    def test_load_specific_files(self, loader):
        doc = Document(text="content", doc_id="f1", extra_info={"file_name": "test.pdf"})
        loader._load_file_by_id = MagicMock(return_value=doc)

        result = loader.load_data({"file_ids": ["f1"]})
        assert len(result) == 1
        assert result[0].doc_id == "f1"

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
        result = loader.load_data({"file_ids": ["f1", "f2"]})
        assert len(result) == 0

    @pytest.mark.unit
    def test_browse_mode_uses_list_items(self, loader):
        docs = [Document(text="", doc_id="f1", extra_info={})]
        loader._list_items_in_parent = MagicMock(return_value=docs)

        result = loader.load_data({"folder_id": "folder1", "limit": 50})
        loader._list_items_in_parent.assert_called_once_with(
            "folder1", limit=50, load_content=True, page_token=None, search_query=None
        )
        assert len(result) == 1

    @pytest.mark.unit
    def test_browse_mode_defaults_to_root(self, loader):
        loader._list_items_in_parent = MagicMock(return_value=[])
        loader.load_data({})
        loader._list_items_in_parent.assert_called_once_with(
            "root", limit=100, load_content=True, page_token=None, search_query=None
        )

    @pytest.mark.unit
    def test_session_token_mismatch_logs_warning(self, loader):
        loader._list_items_in_parent = MagicMock(return_value=[])
        loader.load_data({"session_token": "different_token"})
        # Should not raise, just logs

    @pytest.mark.unit
    def test_load_data_with_list_only(self, loader):
        loader._list_items_in_parent = MagicMock(return_value=[])
        loader.load_data({"list_only": True})
        loader._list_items_in_parent.assert_called_once_with(
            "root", limit=100, load_content=False, page_token=None, search_query=None
        )

    @pytest.mark.unit
    def test_load_data_with_page_token(self, loader):
        loader._list_items_in_parent = MagicMock(return_value=[])
        loader.load_data({"page_token": "next_page"})
        loader._list_items_in_parent.assert_called_once_with(
            "root", limit=100, load_content=True, page_token="next_page", search_query=None
        )

    @pytest.mark.unit
    def test_credential_refresh_retry(self, loader):
        """When _load_file_by_id returns None and _credential_refreshed is set, retry."""
        loader._credential_refreshed = True
        call_count = [0]
        def side_effect(fid, load_content=True):
            call_count[0] += 1
            if call_count[0] == 1:
                return None
            return Document(text="c", doc_id=fid, extra_info={"file_name": "test.pdf"})

        loader._load_file_by_id = MagicMock(side_effect=side_effect)
        result = loader.load_data({"file_ids": ["f1"]})
        assert len(result) == 1

    @pytest.mark.unit
    def test_outer_exception_raises(self, loader):
        """The outer try/except in load_data re-raises unexpected errors."""
        loader._list_items_in_parent = MagicMock(side_effect=RuntimeError("unexpected"))
        with pytest.raises(RuntimeError, match="unexpected"):
            loader.load_data({})


class TestLoadFileById:

    @pytest.mark.unit
    def test_loads_file_metadata_and_processes(self, loader, mock_service):
        mock_service.files.return_value.get.return_value.execute.return_value = {
            "id": "f1", "name": "test.txt", "mimeType": "text/plain"
        }
        loader._process_file = MagicMock(return_value=Document(text="t", doc_id="f1", extra_info={}))
        doc = loader._load_file_by_id("f1")
        assert doc is not None

    @pytest.mark.unit
    def test_http_401_refreshes_credentials(self, loader, mock_service):
        from googleapiclient.errors import HttpError
        resp = MagicMock()
        resp.status = 401
        mock_service.files.return_value.get.return_value.execute.side_effect = HttpError(resp, b"unauth")

        with patch("google.auth.transport.requests.Request"):
            result = loader._load_file_by_id("f1")
        assert result is None
        loader.credentials.refresh.assert_called_once()

    @pytest.mark.unit
    def test_http_401_no_refresh_token_raises(self, loader, mock_service):
        from googleapiclient.errors import HttpError
        resp = MagicMock()
        resp.status = 401
        mock_service.files.return_value.get.return_value.execute.side_effect = HttpError(resp, b"unauth")
        loader.credentials.refresh_token = None

        with pytest.raises(ValueError, match="missing refresh_token"):
            loader._load_file_by_id("f1")

    @pytest.mark.unit
    def test_http_500_returns_none(self, loader, mock_service):
        from googleapiclient.errors import HttpError
        resp = MagicMock()
        resp.status = 500
        mock_service.files.return_value.get.return_value.execute.side_effect = HttpError(resp, b"server error")
        result = loader._load_file_by_id("f1")
        assert result is None

    @pytest.mark.unit
    def test_general_exception_returns_none(self, loader, mock_service):
        mock_service.files.return_value.get.return_value.execute.side_effect = Exception("fail")
        result = loader._load_file_by_id("f1")
        assert result is None

    @pytest.mark.unit
    def test_ensure_service_called(self, loader):
        loader.service = None
        loader.auth.build_drive_service.return_value = MagicMock()
        loader.auth.build_drive_service.return_value.files.return_value.get.return_value.execute.return_value = {
            "id": "f1", "name": "t.txt", "mimeType": "text/plain"
        }
        loader._process_file = MagicMock(return_value=None)
        loader._load_file_by_id("f1")
        loader.auth.build_drive_service.assert_called()

    @pytest.mark.unit
    def test_http_401_refresh_failure_raises(self, loader, mock_service):
        from googleapiclient.errors import HttpError
        resp = MagicMock()
        resp.status = 401
        mock_service.files.return_value.get.return_value.execute.side_effect = HttpError(resp, b"unauth")
        loader.credentials.refresh_token = "rt"

        with patch("google.auth.transport.requests.Request"):
            loader.credentials.refresh.side_effect = Exception("refresh broke")
            with pytest.raises(ValueError, match="could not be refreshed"):
                loader._load_file_by_id("f1")


class TestListItemsInParent:

    @pytest.mark.unit
    def test_lists_files_and_folders(self, loader, mock_service):
        mock_service.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "folder1", "name": "Docs", "mimeType": "application/vnd.google-apps.folder"},
                {"id": "file1", "name": "test.txt", "mimeType": "text/plain"},
            ],
            "nextPageToken": None,
        }
        loader._process_file = MagicMock(return_value=Document(text="", doc_id="file1", extra_info={}))
        docs = loader._list_items_in_parent("root", limit=100)
        assert len(docs) == 2
        assert docs[0].extra_info.get("is_folder") is True

    @pytest.mark.unit
    def test_search_query_modifies_drive_query(self, loader, mock_service):
        mock_service.files.return_value.list.return_value.execute.return_value = {
            "files": [], "nextPageToken": None
        }
        loader._list_items_in_parent("root", search_query="report")
        call_args = mock_service.files.return_value.list.call_args
        assert "name contains 'report'" in call_args.kwargs.get("q", "")

    @pytest.mark.unit
    def test_limit_stops_early(self, loader, mock_service):
        mock_service.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": f"f{i}", "name": f"file{i}.txt", "mimeType": "text/plain"} for i in range(10)
            ],
            "nextPageToken": "next",
        }
        loader._process_file = MagicMock(side_effect=lambda m, **kw: Document(text="", doc_id=m["id"], extra_info={}))
        docs = loader._list_items_in_parent("root", limit=3)
        assert len(docs) == 3

    @pytest.mark.unit
    def test_pagination_stores_next_page_token(self, loader, mock_service):
        mock_service.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "f1", "name": "f.txt", "mimeType": "text/plain"}],
            "nextPageToken": "page2",
        }
        loader._process_file = MagicMock(return_value=Document(text="", doc_id="f1", extra_info={}))
        loader._list_items_in_parent("root", limit=1)
        assert loader.next_page_token == "page2"

    @pytest.mark.unit
    def test_limit_breaks_loop_when_remaining_zero(self, loader, mock_service):
        """When limit is exactly met after first page, the while loop breaks via remaining==0."""
        call_count = [0]
        def list_side_effect(**kw):
            call_count[0] += 1
            mock = MagicMock()
            if call_count[0] == 1:
                mock.execute.return_value = {
                    "files": [
                        {"id": "f1", "name": "f1.txt", "mimeType": "text/plain"},
                        {"id": "f2", "name": "f2.txt", "mimeType": "text/plain"},
                    ],
                    "nextPageToken": "page2",
                }
            else:
                # Should not reach here if break works correctly
                mock.execute.return_value = {"files": [], "nextPageToken": None}
            return mock

        mock_service.files.return_value.list.side_effect = list_side_effect
        loader._process_file = MagicMock(side_effect=lambda m, **kw: Document(text="", doc_id=m["id"], extra_info={}))
        # limit=2, first page returns exactly 2 files with nextPageToken
        # Since items don't hit the inner limit check (it checks after each item),
        # it should loop back and break at remaining==0
        docs = loader._list_items_in_parent("root", limit=2)
        assert len(docs) == 2

    @pytest.mark.unit
    def test_exception_returns_partial_results(self, loader, mock_service):
        mock_service.files.return_value.list.return_value.execute.side_effect = Exception("api error")
        docs = loader._list_items_in_parent("root")
        assert docs == []


class TestBrowseSharedDrives:

    @pytest.mark.unit
    def test_top_level_lists_shared_drives_first(self, loader, mock_service):
        mock_service.drives.return_value.list.return_value.execute.return_value = {
            "drives": [{"id": "drive-1", "name": "Engineering"}],
        }
        my_drive = [Document(text="", doc_id="f1", extra_info={"file_name": "a.txt"})]
        loader._list_items_in_parent = MagicMock(return_value=my_drive)

        result = loader.load_data({"limit": 10})

        assert [d.doc_id for d in result] == ["drive-1", "f1"]
        assert result[0].extra_info["is_folder"] is True
        assert result[0].extra_info["file_name"] == "Engineering"
        loader._list_items_in_parent.assert_called_once_with(
            "root", limit=9, load_content=True, page_token=None, search_query=None
        )
        assert mock_service.drives.return_value.list.call_args.kwargs["pageSize"] == 9

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "inputs",
        [{"folder_id": "folder1"}, {"page_token": "next"}, {"search_query": "report"}],
    )
    def test_shared_drives_only_on_the_first_top_level_page(self, loader, mock_service, inputs):
        loader._list_items_in_parent = MagicMock(return_value=[])
        loader.load_data(inputs)
        mock_service.drives.return_value.list.assert_not_called()

    @pytest.mark.unit
    def test_shared_drive_listing_failure_still_lists_my_drive(self, loader, mock_service):
        mock_service.drives.return_value.list.return_value.execute.side_effect = Exception("403")
        my_drive = [Document(text="", doc_id="f1", extra_info={})]
        loader._list_items_in_parent = MagicMock(return_value=my_drive)
        assert loader.load_data({}) == my_drive

    @pytest.mark.unit
    def test_folder_in_shared_drive_listed_within_its_drive(self, loader, mock_service):
        mock_service.files.return_value.get.return_value.execute.return_value = {"driveId": "drive-1"}
        mock_service.files.return_value.list.return_value.execute.return_value = {"files": []}
        loader._list_items_in_parent("drive-1")
        kwargs = mock_service.files.return_value.list.call_args.kwargs
        assert kwargs["corpora"] == "drive"
        assert kwargs["driveId"] == "drive-1"

    @pytest.mark.unit
    @pytest.mark.parametrize("folder, metadata", [("root", None), ("folder1", {})])
    def test_my_drive_listing_uses_default_corpus(self, loader, mock_service, folder, metadata):
        mock_service.files.return_value.get.return_value.execute.return_value = metadata
        mock_service.files.return_value.list.return_value.execute.return_value = {"files": []}
        loader._list_items_in_parent(folder)
        assert "corpora" not in mock_service.files.return_value.list.call_args.kwargs

    @pytest.mark.unit
    def test_unreadable_folder_scope_falls_back_to_default(self, loader, mock_service):
        mock_service.files.return_value.get.return_value.execute.side_effect = Exception("404")
        mock_service.files.return_value.list.return_value.execute.return_value = {"files": []}
        loader._list_items_in_parent("folder1")
        assert "corpora" not in mock_service.files.return_value.list.call_args.kwargs


class TestDownloadFileContent:

    @pytest.mark.unit
    def test_download_regular_file(self, loader, mock_service):
        mock_request = MagicMock()
        mock_service.files.return_value.get_media.return_value = mock_request

        with patch("docsgpt.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
            mock_dl = MagicMock()
            mock_dl.next_chunk.side_effect = [(None, False), (None, True)]
            MockDownload.return_value = mock_dl

            with patch("io.BytesIO") as MockBytesIO:
                mock_bio = MagicMock()
                mock_bio.getvalue.return_value = b"file content"
                MockBytesIO.return_value = mock_bio

                content = loader._download_file_content("f1", "text/plain")

        assert content == "file content"

    @pytest.mark.unit
    def test_download_google_workspace_file_uses_export(self, loader, mock_service):
        mock_request = MagicMock()
        mock_service.files.return_value.export_media.return_value = mock_request

        with patch("docsgpt.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
            mock_dl = MagicMock()
            mock_dl.next_chunk.return_value = (None, True)
            MockDownload.return_value = mock_dl

            with patch("io.BytesIO") as MockBytesIO:
                mock_bio = MagicMock()
                mock_bio.getvalue.return_value = b"exported"
                MockBytesIO.return_value = mock_bio

                content = loader._download_file_content("f1", "application/vnd.google-apps.document")

        mock_service.files.return_value.export_media.assert_called_once()
        assert content == "exported"

    @pytest.mark.unit
    def test_unicode_decode_error_returns_none(self, loader, mock_service):
        mock_request = MagicMock()
        mock_service.files.return_value.get_media.return_value = mock_request

        with patch("docsgpt.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
            mock_dl = MagicMock()
            mock_dl.next_chunk.return_value = (None, True)
            MockDownload.return_value = mock_dl

            with patch("io.BytesIO") as MockBytesIO:
                mock_bio = MagicMock()
                mock_bio.getvalue.return_value = MagicMock()
                mock_bio.getvalue.return_value.decode.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "bad")
                MockBytesIO.return_value = mock_bio

                result = loader._download_file_content("f1", "application/pdf")
        assert result is None

    @pytest.mark.unit
    def test_no_access_token_with_refresh(self, loader):
        loader.credentials.token = None
        loader.credentials.refresh_token = "rt"
        loader.credentials.expired = False

        with patch("google.auth.transport.requests.Request"):
            loader.credentials.refresh = MagicMock()
            # After refresh, set token
            def set_token(req):
                loader.credentials.token = "new_at"
            loader.credentials.refresh.side_effect = set_token
            loader._ensure_service = MagicMock()
            loader.service.files.return_value.get_media.return_value = MagicMock()

            with patch("docsgpt.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
                mock_dl = MagicMock()
                mock_dl.next_chunk.return_value = (None, True)
                MockDownload.return_value = mock_dl
                with patch("io.BytesIO") as MockBytesIO:
                    mock_bio = MagicMock()
                    mock_bio.getvalue.return_value = b"data"
                    MockBytesIO.return_value = mock_bio
                    content = loader._download_file_content("f1", "text/plain")

        assert content == "data"

    @pytest.mark.unit
    def test_no_access_token_no_refresh_raises(self, loader):
        loader.credentials.token = None
        loader.credentials.refresh_token = None
        with pytest.raises(ValueError, match="missing refresh_token"):
            loader._download_file_content("f1", "text/plain")

    @pytest.mark.unit
    def test_no_token_refresh_fails_raises(self, loader):
        loader.credentials.token = None
        loader.credentials.refresh_token = "rt"
        with patch("google.auth.transport.requests.Request"):
            loader.credentials.refresh.side_effect = Exception("fail")
            with pytest.raises(ValueError, match="missing or invalid refresh_token"):
                loader._download_file_content("f1", "text/plain")

    @pytest.mark.unit
    def test_expired_credentials_refresh(self, loader):
        loader.credentials.token = "at"
        loader.credentials.expired = True
        loader.credentials.refresh_token = "rt"

        with patch("google.auth.transport.requests.Request"):
            loader.credentials.refresh = MagicMock()
            def fix_expired(req):
                loader.credentials.expired = False
            loader.credentials.refresh.side_effect = fix_expired
            loader._ensure_service = MagicMock()
            loader.service.files.return_value.get_media.return_value = MagicMock()

            with patch("docsgpt.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
                mock_dl = MagicMock()
                mock_dl.next_chunk.return_value = (None, True)
                MockDownload.return_value = mock_dl
                with patch("io.BytesIO") as MockBytesIO:
                    mock_bio = MagicMock()
                    mock_bio.getvalue.return_value = b"ok"
                    MockBytesIO.return_value = mock_bio
                    content = loader._download_file_content("f1", "text/plain")

        assert content == "ok"

    @pytest.mark.unit
    def test_expired_no_refresh_token_raises(self, loader):
        loader.credentials.token = "at"
        loader.credentials.expired = True
        loader.credentials.refresh_token = None
        with pytest.raises(ValueError, match="missing refresh_token"):
            loader._download_file_content("f1", "text/plain")

    @pytest.mark.unit
    def test_expired_refresh_fails_raises(self, loader):
        loader.credentials.token = "at"
        loader.credentials.expired = True
        loader.credentials.refresh_token = "rt"
        with patch("google.auth.transport.requests.Request"):
            loader.credentials.refresh.side_effect = Exception("fail")
            with pytest.raises(ValueError, match="expired credentials"):
                loader._download_file_content("f1", "text/plain")

    @pytest.mark.unit
    def test_http_error_during_download_chunk_returns_none(self, loader, mock_service):
        from googleapiclient.errors import HttpError
        mock_request = MagicMock()
        mock_service.files.return_value.get_media.return_value = mock_request

        resp = MagicMock()
        resp.status = 500

        with patch("docsgpt.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
            mock_dl = MagicMock()
            mock_dl.next_chunk.side_effect = HttpError(resp, b"server error")
            MockDownload.return_value = mock_dl
            with patch("io.BytesIO") as MockBytesIO:
                MockBytesIO.return_value = MagicMock()
                result = loader._download_file_content("f1", "text/plain")
        assert result is None

    @pytest.mark.unit
    def test_general_error_during_download_chunk_returns_none(self, loader, mock_service):
        mock_request = MagicMock()
        mock_service.files.return_value.get_media.return_value = mock_request

        with patch("docsgpt.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
            mock_dl = MagicMock()
            mock_dl.next_chunk.side_effect = RuntimeError("chunk fail")
            MockDownload.return_value = mock_dl
            with patch("io.BytesIO") as MockBytesIO:
                MockBytesIO.return_value = MagicMock()
                result = loader._download_file_content("f1", "text/plain")
        assert result is None

    @pytest.mark.unit
    def test_http_401_during_download_refreshes_and_returns_none(self, loader, mock_service):
        from googleapiclient.errors import HttpError
        resp = MagicMock()
        resp.status = 401

        mock_service.files.return_value.get_media.side_effect = HttpError(resp, b"unauth")
        loader.credentials.refresh_token = "rt"

        with patch("google.auth.transport.requests.Request"):
            loader.credentials.refresh = MagicMock()
            loader._ensure_service = MagicMock()
            result = loader._download_file_content("f1", "text/plain")

        assert result is None
        assert loader._credential_refreshed is True

    @pytest.mark.unit
    def test_http_401_no_refresh_token_raises(self, loader, mock_service):
        from googleapiclient.errors import HttpError
        resp = MagicMock()
        resp.status = 401
        mock_service.files.return_value.get_media.side_effect = HttpError(resp, b"unauth")
        loader.credentials.refresh_token = None

        with pytest.raises(ValueError, match="missing refresh_token"):
            loader._download_file_content("f1", "text/plain")

    @pytest.mark.unit
    def test_http_401_refresh_fails_raises(self, loader, mock_service):
        from googleapiclient.errors import HttpError
        resp = MagicMock()
        resp.status = 401
        mock_service.files.return_value.get_media.side_effect = HttpError(resp, b"unauth")
        loader.credentials.refresh_token = "rt"

        with patch("google.auth.transport.requests.Request"):
            loader.credentials.refresh.side_effect = Exception("refresh fail")
            with pytest.raises(ValueError, match="could not be refreshed"):
                loader._download_file_content("f1", "text/plain")

    @pytest.mark.unit
    def test_http_500_returns_none(self, loader, mock_service):
        from googleapiclient.errors import HttpError
        resp = MagicMock()
        resp.status = 500
        mock_service.files.return_value.get_media.side_effect = HttpError(resp, b"error")
        result = loader._download_file_content("f1", "text/plain")
        assert result is None

    @pytest.mark.unit
    def test_general_exception_returns_none(self, loader, mock_service):
        mock_service.files.return_value.get_media.side_effect = RuntimeError("fail")
        result = loader._download_file_content("f1", "text/plain")
        assert result is None


FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
GDOC = "application/vnd.google-apps.document"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _http_error(status, reason="forbidden"):
    body = json.dumps({"error": {"message": reason, "errors": [{"reason": reason}]}}).encode()
    return HttpError(httplib2.Response({"status": status}), body)


class _Request:
    def __init__(self, fn, calls):
        self._fn = fn
        self._calls = calls

    def execute(self, num_retries=0):
        self._calls.append(num_retries)
        return self._fn()


class FakeDrive:
    """A Drive ``files()`` resource over an in-memory tree.

    ``items`` maps id → metadata (with a ``parent``), ``contents`` maps id →
    bytes served by downloads, and ``errors`` maps id → the exception a
    download (or, for ``get_errors``, a metadata read) raises.
    """

    def __init__(self, items, contents=None, errors=None, get_errors=None):
        self.items = items
        self.contents = contents or {}
        self.errors = errors or {}
        self.get_errors = get_errors or {}
        self.retries = []
        self.list_calls = []
        self.service = MagicMock()
        self.service.files.return_value = self

    def _meta(self, item_id):
        meta = {k: v for k, v in self.items[item_id].items() if k != "parent"}
        return {"id": item_id, **meta}

    def get(self, fileId, fields, supportsAllDrives):
        def run():
            if fileId in self.get_errors:
                raise self.get_errors[fileId]
            if fileId not in self.items:
                raise _http_error(404, "notFound")
            return self._meta(fileId)
        return _Request(run, self.retries)

    def list(self, q, fields, pageToken, pageSize, supportsAllDrives, includeItemsFromAllDrives, **kwargs):
        parent = q.split("'")[1]
        self.list_calls.append({"parent": parent, **kwargs})
        children = [self._meta(i) for i, m in self.items.items() if m.get("parent") == parent]
        return _Request(lambda: {"files": children}, self.retries)

    def get_media(self, fileId, supportsAllDrives):
        return ("media", fileId)

    def export_media(self, fileId, mimeType):
        return ("export", fileId)


class FakeDownloader:
    drive = None

    def __init__(self, fh, request):
        self.fh = fh
        self.file_id = request[1]

    def next_chunk(self, num_retries=0):
        self.drive.retries.append(num_retries)
        self.fh.write(b"partial")
        if self.file_id in self.drive.errors:
            raise self.drive.errors[self.file_id]
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write(self.drive.contents.get(self.file_id, b"data"))
        return None, True


@pytest.fixture
def drive_loader():
    def build(items, **kwargs):
        drive = FakeDrive(items, **kwargs)
        FakeDownloader.drive = drive
        return _make_loader(drive.service), drive

    with patch("docsgpt.parser.connectors.google_drive.loader.MediaIoBaseDownload", FakeDownloader):
        yield build


def _files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


class TestDownloadToDirectory:

    @pytest.mark.unit
    def test_downloads_selected_files(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "f1": {"name": "a.pdf", "mimeType": "application/pdf"},
            "f2": {"name": "b.txt", "mimeType": "text/plain"},
        })
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1", "f2"]})
        assert result["files_downloaded"] == 2
        assert result["empty_result"] is False
        assert result["source_type"] == "google_drive"
        assert _files(tmp_path) == ["a.pdf", "b.txt"]

    @pytest.mark.unit
    def test_single_id_string(self, drive_loader, tmp_path):
        loader, _ = drive_loader({"f1": {"name": "a.pdf", "mimeType": "application/pdf"}})
        result = loader.download_to_directory(str(tmp_path), {"file_ids": "f1"})
        assert result["files_downloaded"] == 1

    @pytest.mark.unit
    def test_folder_walked_recursively_into_its_own_directory(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "root": {"name": "Reports", "mimeType": FOLDER},
            "sub": {"name": "2026", "mimeType": FOLDER, "parent": "root"},
            "f1": {"name": "q1.pdf", "mimeType": "application/pdf", "parent": "root"},
            "f2": {"name": "q2.pdf", "mimeType": "application/pdf", "parent": "sub"},
        })
        result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert result["files_downloaded"] == 2
        assert _files(tmp_path) == ["Reports/2026/q2.pdf", "Reports/q1.pdf"]

    @pytest.mark.unit
    def test_non_recursive_skips_subfolders(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "root": {"name": "Reports", "mimeType": FOLDER},
            "sub": {"name": "2026", "mimeType": FOLDER, "parent": "root"},
            "f1": {"name": "q1.pdf", "mimeType": "application/pdf", "parent": "root"},
            "f2": {"name": "q2.pdf", "mimeType": "application/pdf", "parent": "sub"},
        })
        loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"], "recursive": False})
        assert _files(tmp_path) == ["Reports/q1.pdf"]

    @pytest.mark.unit
    def test_google_docs_exported_with_extension(self, drive_loader, tmp_path):
        loader, _ = drive_loader({"d1": {"name": "Plan", "mimeType": GDOC}})
        loader.download_to_directory(str(tmp_path), {"file_ids": ["d1"]})
        assert _files(tmp_path) == ["Plan.docx"]

    @pytest.mark.unit
    def test_extension_added_when_name_has_none(self, drive_loader, tmp_path):
        loader, _ = drive_loader({"f1": {"name": "invoice", "mimeType": "application/pdf"}})
        loader.download_to_directory(str(tmp_path), {"file_ids": ["f1"]})
        assert _files(tmp_path) == ["invoice.pdf"]

    @pytest.mark.unit
    def test_unsupported_types_skipped(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "root": {"name": "Mixed", "mimeType": FOLDER},
            "form": {"name": "Survey", "mimeType": "application/vnd.google-apps.form", "parent": "root"},
            "zip": {"name": "a.zip", "mimeType": "application/zip", "parent": "root"},
            "f1": {"name": "ok.txt", "mimeType": "text/plain", "parent": "root"},
        })
        result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert result["files_downloaded"] == 1
        assert result["files_skipped"] == 2
        assert result["files_failed"] == 0

    @pytest.mark.unit
    def test_no_ids_returns_error(self, drive_loader, tmp_path):
        loader, _ = drive_loader({})
        result = loader.download_to_directory(str(tmp_path), {})
        assert "error" in result
        assert result["empty_result"] is True

    @pytest.mark.unit
    def test_none_config_uses_empty(self, drive_loader, tmp_path):
        loader, _ = drive_loader({})
        result = loader.download_to_directory(str(tmp_path))
        assert "error" in result

    @pytest.mark.unit
    def test_every_call_retries(self, drive_loader, tmp_path):
        loader, drive = drive_loader({
            "root": {"name": "R", "mimeType": FOLDER},
            "f1": {"name": "a.txt", "mimeType": "text/plain", "parent": "root"},
        })
        loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert drive.retries
        assert set(drive.retries) == {5}


class TestDownloadFailureIsolation:

    @pytest.mark.unit
    def test_failed_file_does_not_stop_the_folder(self, drive_loader, tmp_path):
        loader, _ = drive_loader(
            {
                "root": {"name": "R", "mimeType": FOLDER},
                "f1": {"name": "a.txt", "mimeType": "text/plain", "parent": "root"},
                "big": {"name": "Huge", "mimeType": GDOC, "parent": "root"},
                "f2": {"name": "c.txt", "mimeType": "text/plain", "parent": "root"},
            },
            errors={"big": _http_error(403, "exportSizeLimitExceeded")},
        )
        result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert result["files_downloaded"] == 2
        assert _files(tmp_path) == ["R/a.txt", "R/c.txt"]

    @pytest.mark.unit
    def test_partial_file_removed(self, drive_loader, tmp_path):
        loader, _ = drive_loader(
            {"f1": {"name": "a.txt", "mimeType": "text/plain"}},
            errors={"f1": OSError("connection reset")},
        )
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1"]})
        assert result["files_downloaded"] == 0
        assert _files(tmp_path) == []

    @pytest.mark.unit
    def test_permanent_refusal_counts_as_skipped(self, drive_loader, tmp_path):
        loader, _ = drive_loader(
            {"big": {"name": "Huge", "mimeType": GDOC}, "f1": {"name": "a.txt", "mimeType": "text/plain"}},
            errors={"big": _http_error(403, "exportSizeLimitExceeded")},
        )
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["big", "f1"]})
        assert result["files_skipped"] == 1
        assert result["files_failed"] == 0
        assert result["sync_fingerprint"]

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "status, reason",
        [(403, "cannotDownloadFile"), (403, "insufficientFilePermissions"), (404, "notFound")],
    )
    def test_access_refusal_withholds_fingerprint(self, drive_loader, tmp_path, status, reason):
        # Sharing settings can change without touching modifiedTime, so a file
        # refused for access must not be fingerprinted as if it were indexed.
        loader, _ = drive_loader(
            {"f1": {"name": "a.pdf", "mimeType": "application/pdf"}, "f2": {"name": "b.txt", "mimeType": "text/plain"}},
            errors={"f1": _http_error(status, reason)},
        )
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1", "f2"]})
        assert result["files_downloaded"] == 1
        assert result["files_skipped"] == 1
        assert result["files_failed"] == 0
        assert result["sync_fingerprint"] is None

    @pytest.mark.unit
    def test_transient_failure_withholds_fingerprint(self, drive_loader, tmp_path):
        loader, _ = drive_loader(
            {"f1": {"name": "a.txt", "mimeType": "text/plain"}, "f2": {"name": "b.txt", "mimeType": "text/plain"}},
            errors={"f1": _http_error(403, "userRateLimitExceeded")},
        )
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1", "f2"]})
        assert result["files_downloaded"] == 1
        assert result["files_failed"] == 1
        assert result["sync_fingerprint"] is None

    @pytest.mark.unit
    def test_unreadable_subfolder_does_not_stop_siblings(self, drive_loader, tmp_path):
        loader, drive = drive_loader({
            "root": {"name": "R", "mimeType": FOLDER},
            "bad": {"name": "Locked", "mimeType": FOLDER, "parent": "root"},
            "f1": {"name": "a.txt", "mimeType": "text/plain", "parent": "root"},
        })
        original_list = drive.list

        def list_or_fail(q, **kwargs):
            if "'bad'" in q:
                raise _http_error(500, "backendError")
            return original_list(q=q, **kwargs)

        drive.list = list_or_fail
        result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert result["files_downloaded"] == 1
        assert result["files_failed"] == 1
        assert result["sync_fingerprint"] is None

    @pytest.mark.unit
    def test_missing_selected_item_skipped(self, drive_loader, tmp_path):
        loader, _ = drive_loader({"f1": {"name": "a.txt", "mimeType": "text/plain"}})
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["gone", "f1"]})
        assert result["files_downloaded"] == 1
        assert result["files_skipped"] == 1


class TestFileNames:

    @pytest.mark.unit
    def test_duplicate_names_numbered(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "root": {"name": "R", "mimeType": FOLDER},
            "f1": {"name": "report.pdf", "mimeType": "application/pdf", "parent": "root"},
            "f2": {"name": "report.pdf", "mimeType": "application/pdf", "parent": "root"},
            "f3": {"name": "Report.PDF", "mimeType": "application/pdf", "parent": "root"},
        }, contents={"f1": b"one", "f2": b"two", "f3": b"three"})
        result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert result["files_downloaded"] == 3
        assert _files(tmp_path) == ["R/Report_2.PDF", "R/report.pdf", "R/report_1.pdf"]
        contents = {(tmp_path / "R" / name).read_bytes() for name in ("report.pdf", "report_1.pdf", "Report_2.PDF")}
        assert contents == {b"one", b"two", b"three"}

    @pytest.mark.unit
    def test_export_name_collision_numbered(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "d1": {"name": "Plan", "mimeType": GDOC},
            "f1": {"name": "Plan.docx", "mimeType": DOCX},
        })
        loader.download_to_directory(str(tmp_path), {"file_ids": ["d1", "f1"]})
        assert _files(tmp_path) == ["Plan.docx", "Plan_1.docx"]

    @pytest.mark.unit
    def test_duplicate_folder_names_numbered(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "a": {"name": "Docs", "mimeType": FOLDER},
            "b": {"name": "Docs", "mimeType": FOLDER},
            "f1": {"name": "x.txt", "mimeType": "text/plain", "parent": "a"},
            "f2": {"name": "x.txt", "mimeType": "text/plain", "parent": "b"},
        })
        loader.download_to_directory(str(tmp_path), {"folder_ids": ["a", "b"]})
        assert _files(tmp_path) == ["Docs/x.txt", "Docs_1/x.txt"]

    @pytest.mark.unit
    def test_separators_and_dot_names_cannot_escape(self, drive_loader, tmp_path):
        target = tmp_path / "target"
        loader, _ = drive_loader({
            "root": {"name": "..", "mimeType": FOLDER},
            "f1": {"name": "../../escape.txt", "mimeType": "text/plain", "parent": "root"},
            "f2": {"name": "..\\win.txt", "mimeType": "text/plain", "parent": "root"},
            "f3": {"name": "a\x00b.txt", "mimeType": "text/plain", "parent": "root"},
        })
        result = loader.download_to_directory(str(target), {"folder_ids": ["root"]})
        assert result["files_downloaded"] == 3
        assert _files(tmp_path) == ["target/_/.._.._escape.txt", "target/_/.._win.txt", "target/_/ab.txt"]

    @pytest.mark.unit
    def test_long_name_truncated_keeping_extension(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "f1": {"name": "é" * 300 + ".pdf", "mimeType": "application/pdf"},
            "f2": {"name": "é" * 300 + ".pdf", "mimeType": "application/pdf"},
        })
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1", "f2"]})
        assert result["files_downloaded"] == 2
        names = _files(tmp_path)
        assert all(len(n.encode()) <= 255 and n.endswith(".pdf") for n in names)
        assert names[1].endswith("_1.pdf") or names[0].endswith("_1.pdf")

    @pytest.mark.unit
    def test_safe_join_refuses_escape(self, tmp_path):
        from docsgpt.parser.connectors.google_drive.loader import _safe_join

        with pytest.raises(ValueError):
            _safe_join(str(tmp_path), ("..", "x.txt"))
        with pytest.raises(ValueError):
            _safe_join(str(tmp_path), ())
        assert _safe_join(str(tmp_path), ("a", "b.txt")).endswith("a/b.txt")


class TestShortcuts:

    @pytest.mark.unit
    def test_file_shortcut_followed_under_its_own_name(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "root": {"name": "R", "mimeType": FOLDER},
            "s1": {
                "name": "Linked spec", "mimeType": SHORTCUT, "parent": "root",
                "shortcutDetails": {"targetId": "real", "targetMimeType": GDOC},
            },
            "real": {"name": "Spec v3", "mimeType": GDOC, "parent": "elsewhere"},
        }, contents={"real": b"spec"})
        result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert result["files_downloaded"] == 1
        assert (tmp_path / "R" / "Linked spec.docx").read_bytes() == b"spec"

    @pytest.mark.unit
    def test_folder_shortcut_walked(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "root": {"name": "R", "mimeType": FOLDER},
            "s1": {
                "name": "Team", "mimeType": SHORTCUT, "parent": "root",
                "shortcutDetails": {"targetId": "team", "targetMimeType": FOLDER},
            },
            "team": {"name": "Team folder", "mimeType": FOLDER, "parent": "elsewhere"},
            "f1": {"name": "notes.txt", "mimeType": "text/plain", "parent": "team"},
        })
        loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert _files(tmp_path) == ["R/Team/notes.txt"]

    @pytest.mark.unit
    def test_selected_shortcut_resolved(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "s1": {"name": "a.pdf", "mimeType": SHORTCUT, "shortcutDetails": {"targetId": "real"}},
            "real": {"name": "a.pdf", "mimeType": "application/pdf"},
        })
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["s1"]})
        assert result["files_downloaded"] == 1

    @pytest.mark.unit
    def test_shortcut_cycle_visited_once(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "root": {"name": "R", "mimeType": FOLDER},
            "loop": {
                "name": "Back up", "mimeType": SHORTCUT, "parent": "root",
                "shortcutDetails": {"targetId": "root", "targetMimeType": FOLDER},
            },
            "f1": {"name": "a.txt", "mimeType": "text/plain", "parent": "root"},
        })
        result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert result["files_downloaded"] == 1
        assert _files(tmp_path) == ["R/a.txt"]

    @pytest.mark.unit
    def test_file_reached_twice_downloaded_once(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "root": {"name": "R", "mimeType": FOLDER},
            "f1": {"name": "a.txt", "mimeType": "text/plain", "parent": "root"},
            "s1": {
                "name": "a link", "mimeType": SHORTCUT, "parent": "root",
                "shortcutDetails": {"targetId": "f1"},
            },
        })
        result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert result["files_downloaded"] == 1

    @pytest.mark.unit
    def test_broken_shortcut_skipped(self, drive_loader, tmp_path):
        loader, _ = drive_loader({
            "root": {"name": "R", "mimeType": FOLDER},
            "s1": {"name": "dead", "mimeType": SHORTCUT, "parent": "root", "shortcutDetails": {"targetId": "gone"}},
            "s2": {"name": "empty", "mimeType": SHORTCUT, "parent": "root", "shortcutDetails": {}},
            "f1": {"name": "a.txt", "mimeType": "text/plain", "parent": "root"},
        })
        result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert result["files_downloaded"] == 1
        assert result["files_skipped"] == 2
        assert result["files_failed"] == 0

    @pytest.mark.unit
    def test_shortcut_target_unreachable_for_now_counts_as_failure(self, drive_loader, tmp_path):
        loader, _ = drive_loader(
            {
                "s1": {"name": "x", "mimeType": SHORTCUT, "shortcutDetails": {"targetId": "real"}},
                "real": {"name": "a.pdf", "mimeType": "application/pdf"},
            },
            get_errors={"real": _http_error(503, "backendError")},
        )
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["s1"]})
        assert result["files_failed"] == 1


class TestSharedDrives:

    @pytest.mark.unit
    def test_shared_drive_folder_listed_within_its_drive(self, drive_loader, tmp_path):
        loader, drive = drive_loader({
            "sd": {"name": "Engineering", "mimeType": FOLDER, "driveId": "drive-1"},
            "f1": {"name": "a.txt", "mimeType": "text/plain", "parent": "sd", "driveId": "drive-1"},
        })
        loader.download_to_directory(str(tmp_path), {"folder_ids": ["sd"]})
        assert drive.list_calls == [{"parent": "sd", "corpora": "drive", "driveId": "drive-1"}]
        assert _files(tmp_path) == ["Engineering/a.txt"]

    @pytest.mark.unit
    def test_my_drive_folder_uses_default_corpus(self, drive_loader, tmp_path):
        loader, drive = drive_loader({"root": {"name": "R", "mimeType": FOLDER}})
        loader.download_to_directory(str(tmp_path), {"folder_ids": ["root"]})
        assert drive.list_calls == [{"parent": "root"}]


class TestSyncFingerprint:

    TREE = {
        "root": {"name": "R", "mimeType": FOLDER},
        "f1": {"name": "a.txt", "mimeType": "text/plain", "parent": "root", "modifiedTime": "2026-10-01T00:00:00Z"},
        "f2": {"name": "b.txt", "mimeType": "text/plain", "parent": "root", "modifiedTime": "2026-10-01T00:00:00Z"},
    }
    CONFIG = {"folder_ids": ["root"], "recursive": True}

    def _fingerprint(self, drive_loader, items, **kwargs):
        loader, drive = drive_loader(items, **kwargs)
        return loader.sync_fingerprint(self.CONFIG), drive

    @pytest.mark.unit
    def test_matches_download_and_downloads_nothing(self, drive_loader, tmp_path):
        loader, drive = drive_loader(copy.deepcopy(self.TREE))
        fingerprint = loader.sync_fingerprint(self.CONFIG)
        assert drive.retries and all(r == 5 for r in drive.retries)
        assert _files(tmp_path) == []
        result = loader.download_to_directory(str(tmp_path), self.CONFIG)
        assert result["sync_fingerprint"] == fingerprint

    @pytest.mark.unit
    def test_stable_when_nothing_changed(self, drive_loader):
        first, _ = self._fingerprint(drive_loader, copy.deepcopy(self.TREE))
        second, _ = self._fingerprint(drive_loader, copy.deepcopy(self.TREE))
        assert first == second

    @pytest.mark.unit
    @pytest.mark.parametrize("change", ["modified", "added", "removed", "renamed"])
    def test_changes_with_the_selection(self, drive_loader, change):
        before, _ = self._fingerprint(drive_loader, copy.deepcopy(self.TREE))
        tree = copy.deepcopy(self.TREE)
        if change == "modified":
            tree["f1"]["modifiedTime"] = "2026-10-02T00:00:00Z"
        elif change == "added":
            tree["f3"] = {"name": "c.txt", "mimeType": "text/plain", "parent": "root"}
        elif change == "removed":
            del tree["f2"]
        else:
            tree["f2"]["name"] = "renamed.txt"
        after, _ = self._fingerprint(drive_loader, tree)
        assert before != after

    @pytest.mark.unit
    def test_none_when_part_of_the_selection_unreadable(self, drive_loader):
        fingerprint, _ = self._fingerprint(
            drive_loader, copy.deepcopy(self.TREE), get_errors={"root": _http_error(500, "backendError")}
        )
        assert fingerprint is None

    @pytest.mark.unit
    def test_base_loader_has_no_fingerprint(self):
        from docsgpt.parser.connectors.base import BaseConnectorLoader

        assert BaseConnectorLoader.sync_fingerprint(MagicMock(), {}) is None


class TestPermanentErrors:

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "error, permanent",
        [
            (_http_error(403, "exportSizeLimitExceeded"), True),
            (_http_error(403, "fileNotDownloadable"), True),
            (_http_error(404, "notFound"), True),
            (_http_error(403, "userRateLimitExceeded"), False),
            (_http_error(403, "rateLimitExceeded"), False),
            (_http_error(429, "rateLimitExceeded"), False),
            (_http_error(401, "authError"), False),
            (_http_error(503, "backendError"), False),
            (OSError("reset"), False),
        ],
    )
    def test_classification(self, error, permanent):
        from docsgpt.parser.connectors.google_drive.loader import _is_permanent_error

        assert _is_permanent_error(error) is permanent


class TestEnsureService:

    @pytest.mark.unit
    def test_builds_service_when_none(self, loader):
        loader.service = None
        mock_svc = MagicMock()
        loader.auth.build_drive_service.return_value = mock_svc
        loader._ensure_service()
        assert loader.service == mock_svc

    @pytest.mark.unit
    def test_noop_when_service_exists(self, loader, mock_service):
        loader._ensure_service()
        assert loader.service == mock_service

    @pytest.mark.unit
    def test_build_failure_raises(self, loader):
        loader.service = None
        loader.auth.build_drive_service.side_effect = Exception("fail")
        with pytest.raises(ValueError, match="Cannot access Google Drive"):
            loader._ensure_service()
