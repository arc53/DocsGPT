"""Tests for SharePoint loader."""

import pytest
from unittest.mock import patch, MagicMock

from application.parser.connectors.share_point.loader import SharePointLoader


def make_response(json_data=None, status_code=200, raise_error=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.content = b"test content"
    if raise_error is not None:
        resp.raise_for_status.side_effect = raise_error
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestSharePointLoaderProcessFile:
    """Test _process_file method."""

    def test_size_retrieved_from_root_level(self):
        """Should retrieve size from root of file_metadata, not nested file object."""
        loader = SharePointLoader.__new__(SharePointLoader)

        file_metadata = {
            "id": "test-id",
            "name": "test.txt",
            "createdDateTime": "2024-01-01T00:00:00Z",
            "lastModifiedDateTime": "2024-01-01T00:00:00Z",
            "size": 1024,
            "file": {
                "mimeType": "text/plain"
            }
        }

        doc = loader._process_file(file_metadata, load_content=False)

        assert doc is not None
        assert doc.extra_info["size"] == 1024
        assert doc.extra_info["file_name"] == "test.txt"
        assert doc.extra_info["mime_type"] == "text/plain"

    def test_size_null_when_missing(self):
        """Should return None when size field is missing."""
        loader = SharePointLoader.__new__(SharePointLoader)

        file_metadata = {
            "id": "test-id",
            "name": "test.txt",
            "createdDateTime": "2024-01-01T00:00:00Z",
            "lastModifiedDateTime": "2024-01-01T00:00:00Z",
            "file": {
                "mimeType": "text/plain"
            }
        }

        doc = loader._process_file(file_metadata, load_content=False)

        assert doc is not None
        assert doc.extra_info["size"] is None


class TestSharePointLoaderLoadFileById:
    """Test _load_file_by_id method."""

    @patch("application.parser.connectors.share_point.loader.requests.get")
    @patch("application.parser.connectors.share_point.loader.SharePointAuth.get_token_info_from_session")
    @patch("application.parser.connectors.share_point.loader.SharePointLoader._ensure_valid_token")
    def test_load_file_by_id_includes_size_in_select(self, mock_ensure_token, mock_get_token, mock_get):
        """Should include size field in $select parameter."""
        mock_get_token.return_value = {
            "access_token": "test-token",
            "refresh_token": "test-refresh"
        }
        mock_get.return_value = make_response({
            "id": "test-id",
            "name": "test.txt",
            "createdDateTime": "2024-01-01T00:00:00Z",
            "lastModifiedDateTime": "2024-01-01T00:00:00Z",
            "size": 2048,
            "file": {
                "mimeType": "text/plain"
            }
        })

        loader = SharePointLoader("test-session")
        doc = loader._load_file_by_id("test-id", load_content=False)

        assert doc is not None
        assert doc.extra_info["size"] == 2048

        call_args = mock_get.call_args
        params = call_args[1]["params"]
        assert "size" in params["$select"]

    @patch("application.parser.connectors.share_point.loader.requests.get")
    @patch("application.parser.connectors.share_point.loader.SharePointAuth.get_token_info_from_session")
    @patch("application.parser.connectors.share_point.loader.SharePointLoader._ensure_valid_token")
    def test_load_file_by_id_returns_document_with_size(self, mock_ensure_token, mock_get_token, mock_get):
        """Should return document with size from API response."""
        mock_get_token.return_value = {
            "access_token": "test-token",
            "refresh_token": "test-refresh"
        }
        mock_get.return_value = make_response({
            "id": "test-id",
            "name": "document.pdf",
            "createdDateTime": "2024-01-01T00:00:00Z",
            "lastModifiedDateTime": "2024-06-15T10:30:00Z",
            "size": 56789,
            "file": {
                "mimeType": "application/pdf"
            }
        })

        loader = SharePointLoader("test-session")
        doc = loader._load_file_by_id("test-id", load_content=False)

        assert doc is not None
        assert doc.doc_id == "test-id"
        assert doc.extra_info["file_name"] == "document.pdf"
        assert doc.extra_info["mime_type"] == "application/pdf"
        assert doc.extra_info["size"] == 56789
        assert doc.extra_info["created_time"] == "2024-01-01T00:00:00Z"
        assert doc.extra_info["modified_time"] == "2024-06-15T10:30:00Z"
        assert doc.extra_info["source"] == "share_point"


class TestSharePointLoaderListItems:
    """Test _list_items_in_parent method."""

    @patch("application.parser.connectors.share_point.loader.requests.get")
    @patch("application.parser.connectors.share_point.loader.SharePointAuth.get_token_info_from_session")
    @patch("application.parser.connectors.share_point.loader.SharePointLoader._ensure_valid_token")
    def test_list_items_includes_size_in_select(self, mock_ensure_token, mock_get_token, mock_get):
        """Should include size field in $select parameter when listing items."""
        mock_get_token.return_value = {
            "access_token": "test-token",
            "refresh_token": "test-refresh"
        }
        mock_get.return_value = make_response({
            "value": [
                {
                    "id": "file-1",
                    "name": "file1.txt",
                    "createdDateTime": "2024-01-01T00:00:00Z",
                    "lastModifiedDateTime": "2024-01-01T00:00:00Z",
                    "size": 12345,
                    "file": {
                        "mimeType": "text/plain"
                    }
                }
            ]
        })

        loader = SharePointLoader("test-session")
        docs = loader._list_items_in_parent("parent-id", limit=10, load_content=False)

        assert len(docs) == 1
        assert docs[0].extra_info["size"] == 12345

        call_args = mock_get.call_args
        params = call_args[1]["params"]
        assert "size" in params["$select"]

    @patch("application.parser.connectors.share_point.loader.requests.get")
    @patch("application.parser.connectors.share_point.loader.SharePointAuth.get_token_info_from_session")
    @patch("application.parser.connectors.share_point.loader.SharePointLoader._ensure_valid_token")
    def test_list_items_folders_include_size(self, mock_ensure_token, mock_get_token, mock_get):
        """Should include size for folders as well."""
        mock_get_token.return_value = {
            "access_token": "test-token",
            "refresh_token": "test-refresh"
        }
        mock_get.return_value = make_response({
            "value": [
                {
                    "id": "folder-1",
                    "name": "MyFolder",
                    "createdDateTime": "2024-01-01T00:00:00Z",
                    "lastModifiedDateTime": "2024-01-01T00:00:00Z",
                    "size": 0,
                    "folder": {}
                }
            ]
        })

        loader = SharePointLoader("test-session")
        docs = loader._list_items_in_parent("parent-id", limit=10, load_content=False)

        assert len(docs) == 1
        assert docs[0].extra_info["is_folder"] is True
        assert docs[0].extra_info["size"] == 0

