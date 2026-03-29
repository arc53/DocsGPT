"""Tests for GoogleDriveLoader."""

from unittest.mock import MagicMock, patch

import pytest

from application.parser.schema.base import Document


def _make_loader(service=None):
    """Create a GoogleDriveLoader with mocked dependencies."""
    with patch("application.parser.connectors.google_drive.loader.GoogleDriveAuth") as MockAuth:
        mock_auth = MagicMock()
        mock_auth.get_token_info_from_session.return_value = {
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

        from application.parser.connectors.google_drive.loader import GoogleDriveLoader
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
        with patch("application.parser.connectors.google_drive.loader.GoogleDriveAuth") as MockAuth:
            mock_auth = MagicMock()
            mock_auth.get_token_info_from_session.return_value = {
                "access_token": "at", "refresh_token": "rt"
            }
            mock_creds = MagicMock()
            mock_creds.token = "at"
            mock_auth.create_credentials_from_token_info.return_value = mock_creds
            mock_auth.build_drive_service.side_effect = Exception("service fail")
            MockAuth.return_value = mock_auth

            from application.parser.connectors.google_drive.loader import GoogleDriveLoader
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


class TestDownloadFileContent:

    @pytest.mark.unit
    def test_download_regular_file(self, loader, mock_service):
        mock_request = MagicMock()
        mock_service.files.return_value.get_media.return_value = mock_request

        with patch("application.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
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

        with patch("application.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
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

        with patch("application.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
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

            with patch("application.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
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

            with patch("application.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
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

        with patch("application.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
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

        with patch("application.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDownload:
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


class TestDownloadToDirectory:

    @pytest.mark.unit
    def test_download_files(self, loader, tmp_path):
        loader._download_file_to_directory = MagicMock(return_value=True)
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1", "f2"]})
        assert result["files_downloaded"] == 2
        assert result["source_type"] == "google_drive"
        assert result["empty_result"] is False

    @pytest.mark.unit
    def test_download_files_string_id(self, loader, tmp_path):
        loader._download_file_to_directory = MagicMock(return_value=True)
        result = loader.download_to_directory(str(tmp_path), {"file_ids": "single_id"})
        assert result["files_downloaded"] == 1

    @pytest.mark.unit
    def test_download_folders(self, loader, tmp_path, mock_service):
        mock_service.files.return_value.get.return_value.execute.return_value = {"name": "MyFolder"}
        loader._download_folder_recursive = MagicMock(return_value=3)
        result = loader.download_to_directory(str(tmp_path), {"folder_ids": ["folder1"]})
        assert result["files_downloaded"] == 3

    @pytest.mark.unit
    def test_download_folders_string_id(self, loader, tmp_path, mock_service):
        mock_service.files.return_value.get.return_value.execute.return_value = {"name": "F"}
        loader._download_folder_recursive = MagicMock(return_value=1)
        result = loader.download_to_directory(str(tmp_path), {"folder_ids": "single_folder"})
        assert result["files_downloaded"] == 1

    @pytest.mark.unit
    def test_no_ids_returns_error(self, loader, tmp_path):
        result = loader.download_to_directory(str(tmp_path), {})
        assert "error" in result
        assert result["empty_result"] is True

    @pytest.mark.unit
    def test_none_config_uses_empty(self, loader, tmp_path):
        result = loader.download_to_directory(str(tmp_path))
        assert "error" in result

    @pytest.mark.unit
    def test_folder_error_continues(self, loader, tmp_path, mock_service):
        mock_service.files.return_value.get.return_value.execute.side_effect = Exception("fail")
        loader._download_file_to_directory = MagicMock(return_value=True)
        result = loader.download_to_directory(str(tmp_path), {"file_ids": ["f1"], "folder_ids": ["bad_folder"]})
        assert result["files_downloaded"] == 1


class TestDownloadSingleFile:

    @pytest.mark.unit
    def test_downloads_supported_file(self, loader, mock_service, tmp_path):
        mock_service.files.return_value.get.return_value.execute.return_value = {
            "name": "test.txt", "mimeType": "text/plain"
        }
        mock_request = MagicMock()
        mock_service.files.return_value.get_media.return_value = mock_request

        with patch("application.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDl:
            mock_dl = MagicMock()
            mock_dl.next_chunk.return_value = (None, True)
            MockDl.return_value = mock_dl

            result = loader._download_single_file("f1", str(tmp_path))
        assert result is True

    @pytest.mark.unit
    def test_unsupported_mime_returns_false(self, loader, mock_service, tmp_path):
        mock_service.files.return_value.get.return_value.execute.return_value = {
            "name": "test.zip", "mimeType": "application/zip"
        }
        result = loader._download_single_file("f1", str(tmp_path))
        assert result is False

    @pytest.mark.unit
    def test_google_workspace_file_export(self, loader, mock_service, tmp_path):
        mock_service.files.return_value.get.return_value.execute.return_value = {
            "name": "doc", "mimeType": "application/vnd.google-apps.document"
        }
        mock_request = MagicMock()
        mock_service.files.return_value.export_media.return_value = mock_request

        with patch("application.parser.connectors.google_drive.loader.MediaIoBaseDownload") as MockDl:
            mock_dl = MagicMock()
            mock_dl.next_chunk.return_value = (None, True)
            MockDl.return_value = mock_dl
            result = loader._download_single_file("f1", str(tmp_path))

        assert result is True
        mock_service.files.return_value.export_media.assert_called_once()


class TestDownloadFolderRecursive:

    @pytest.mark.unit
    def test_downloads_files_in_folder(self, loader, mock_service, tmp_path):
        mock_service.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "f1", "name": "file1.txt", "mimeType": "text/plain"},
            ],
            "nextPageToken": None,
        }
        loader._download_single_file = MagicMock(return_value=True)
        count = loader._download_folder_recursive("folder1", str(tmp_path))
        assert count == 1

    @pytest.mark.unit
    def test_recurses_into_subfolders(self, loader, mock_service, tmp_path):
        # First call: folder with subfolder and file
        # Second call: subfolder contents
        call_count = [0]
        def list_side_effect():
            mock = MagicMock()
            if call_count[0] == 0:
                call_count[0] += 1
                mock.execute.return_value = {
                    "files": [
                        {"id": "sub1", "name": "subfolder", "mimeType": "application/vnd.google-apps.folder"},
                        {"id": "f1", "name": "file1.txt", "mimeType": "text/plain"},
                    ],
                    "nextPageToken": None,
                }
            else:
                mock.execute.return_value = {
                    "files": [
                        {"id": "f2", "name": "file2.txt", "mimeType": "text/plain"},
                    ],
                    "nextPageToken": None,
                }
            return mock

        mock_service.files.return_value.list.side_effect = lambda **kw: list_side_effect()
        loader._download_single_file = MagicMock(return_value=True)
        count = loader._download_folder_recursive("folder1", str(tmp_path), recursive=True)
        assert count == 2

    @pytest.mark.unit
    def test_non_recursive_skips_subfolders(self, loader, mock_service, tmp_path):
        mock_service.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "sub1", "name": "subfolder", "mimeType": "application/vnd.google-apps.folder"},
                {"id": "f1", "name": "file1.txt", "mimeType": "text/plain"},
            ],
            "nextPageToken": None,
        }
        loader._download_single_file = MagicMock(return_value=True)
        count = loader._download_folder_recursive("folder1", str(tmp_path), recursive=False)
        assert count == 1

    @pytest.mark.unit
    def test_download_failure_continues(self, loader, mock_service, tmp_path):
        mock_service.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "f1", "name": "fail.txt", "mimeType": "text/plain"},
                {"id": "f2", "name": "ok.txt", "mimeType": "text/plain"},
            ],
            "nextPageToken": None,
        }
        loader._download_single_file = MagicMock(side_effect=[False, True])
        count = loader._download_folder_recursive("folder1", str(tmp_path))
        assert count == 1

    @pytest.mark.unit
    def test_exception_returns_partial_count(self, loader, mock_service, tmp_path):
        mock_service.files.return_value.list.return_value.execute.side_effect = Exception("fail")
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
        assert loader._download_file_to_directory("f1", str(tmp_path)) is False


class TestDownloadFolderContents:

    @pytest.mark.unit
    def test_delegates_to_recursive(self, loader, tmp_path):
        loader._download_folder_recursive = MagicMock(return_value=5)
        count = loader._download_folder_contents("folder1", str(tmp_path))
        assert count == 5

    @pytest.mark.unit
    def test_exception_returns_zero(self, loader, tmp_path):
        loader.service = None
        loader.auth.build_drive_service.side_effect = Exception("fail")
        count = loader._download_folder_contents("folder1", str(tmp_path))
        assert count == 0


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


class TestGetExtensionForMimeType:

    @pytest.mark.unit
    def test_known_mime_types(self, loader):
        assert loader._get_extension_for_mime_type("application/pdf") == ".pdf"
        assert loader._get_extension_for_mime_type("text/plain") == ".txt"
        assert loader._get_extension_for_mime_type("text/html") == ".html"
        assert loader._get_extension_for_mime_type("text/markdown") == ".md"

    @pytest.mark.unit
    def test_unknown_returns_bin(self, loader):
        assert loader._get_extension_for_mime_type("application/unknown") == ".bin"
