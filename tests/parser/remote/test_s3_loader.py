"""Tests for S3 loader implementation."""

import json
import pytest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError, NoCredentialsError


@pytest.fixture
def mock_boto3():
    """Mock boto3 module."""
    with patch.dict("sys.modules", {"boto3": MagicMock()}):
        with patch("application.parser.remote.s3_loader.boto3") as mock:
            yield mock


@pytest.fixture
def s3_loader(mock_boto3):
    """Create S3Loader instance with mocked boto3."""
    from application.parser.remote.s3_loader import S3Loader

    loader = S3Loader()
    return loader


class TestS3LoaderInit:
    """Test S3Loader initialization."""

    def test_init_raises_import_error_when_boto3_missing(self):
        """Should raise ImportError when boto3 is not installed."""
        with patch("application.parser.remote.s3_loader.boto3", None):
            from application.parser.remote.s3_loader import S3Loader

            with pytest.raises(ImportError, match="boto3 is required"):
                S3Loader()

    def test_init_sets_client_to_none(self, mock_boto3):
        """Should initialize with s3_client as None."""
        from application.parser.remote.s3_loader import S3Loader

        loader = S3Loader()
        assert loader.s3_client is None


class TestNormalizeEndpointUrl:
    """Test endpoint URL normalization for S3-compatible services."""

    def test_returns_unchanged_for_empty_endpoint(self, s3_loader):
        """Should return unchanged values when endpoint_url is empty."""
        endpoint, bucket = s3_loader._normalize_endpoint_url("", "my-bucket")
        assert endpoint == ""
        assert bucket == "my-bucket"

    def test_returns_unchanged_for_none_endpoint(self, s3_loader):
        """Should return unchanged values when endpoint_url is None."""
        endpoint, bucket = s3_loader._normalize_endpoint_url(None, "my-bucket")
        assert endpoint is None
        assert bucket == "my-bucket"

    def test_extracts_bucket_from_do_spaces_url(self, s3_loader):
        """Should extract bucket name from DigitalOcean Spaces bucket-prefixed URL."""
        endpoint, bucket = s3_loader._normalize_endpoint_url(
            "https://mybucket.nyc3.digitaloceanspaces.com", ""
        )
        assert endpoint == "https://nyc3.digitaloceanspaces.com"
        assert bucket == "mybucket"

    def test_extracts_bucket_overrides_provided_bucket(self, s3_loader):
        """Should use extracted bucket when it differs from provided one."""
        endpoint, bucket = s3_loader._normalize_endpoint_url(
            "https://mybucket.lon1.digitaloceanspaces.com", "other-bucket"
        )
        assert endpoint == "https://lon1.digitaloceanspaces.com"
        assert bucket == "mybucket"

    def test_keeps_provided_bucket_when_matches_extracted(self, s3_loader):
        """Should keep bucket when provided matches extracted."""
        endpoint, bucket = s3_loader._normalize_endpoint_url(
            "https://mybucket.sfo3.digitaloceanspaces.com", "mybucket"
        )
        assert endpoint == "https://sfo3.digitaloceanspaces.com"
        assert bucket == "mybucket"

    def test_returns_unchanged_for_standard_do_endpoint(self, s3_loader):
        """Should return unchanged for standard DO Spaces endpoint."""
        endpoint, bucket = s3_loader._normalize_endpoint_url(
            "https://nyc3.digitaloceanspaces.com", "my-bucket"
        )
        assert endpoint == "https://nyc3.digitaloceanspaces.com"
        assert bucket == "my-bucket"

    def test_returns_unchanged_for_aws_endpoint(self, s3_loader):
        """Should return unchanged for standard AWS S3 endpoints."""
        endpoint, bucket = s3_loader._normalize_endpoint_url(
            "https://s3.us-east-1.amazonaws.com", "my-bucket"
        )
        assert endpoint == "https://s3.us-east-1.amazonaws.com"
        assert bucket == "my-bucket"

    def test_handles_minio_endpoint(self, s3_loader):
        """Should return unchanged for MinIO endpoints."""
        endpoint, bucket = s3_loader._normalize_endpoint_url(
            "http://localhost:9000", "my-bucket"
        )
        assert endpoint == "http://localhost:9000"
        assert bucket == "my-bucket"


class TestInitClient:
    """Test S3 client initialization."""

    def test_init_client_creates_boto3_client(self, s3_loader, mock_boto3):
        """Should create boto3 S3 client with provided credentials."""
        s3_loader._init_client(
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
            region_name="us-west-2",
        )

        mock_boto3.client.assert_called_once()
        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["aws_access_key_id"] == "test-key"
        assert call_kwargs["aws_secret_access_key"] == "test-secret"
        assert call_kwargs["region_name"] == "us-west-2"

    def test_init_client_with_custom_endpoint(self, s3_loader, mock_boto3):
        """Should configure path-style addressing for custom endpoints."""
        s3_loader._init_client(
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
            region_name="us-east-1",
            endpoint_url="https://nyc3.digitaloceanspaces.com",
            bucket="my-bucket",
        )

        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["endpoint_url"] == "https://nyc3.digitaloceanspaces.com"
        assert "config" in call_kwargs

    def test_init_client_normalizes_do_endpoint(self, s3_loader, mock_boto3):
        """Should normalize DigitalOcean Spaces bucket-prefixed URLs."""
        corrected_bucket = s3_loader._init_client(
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
            region_name="us-east-1",
            endpoint_url="https://mybucket.nyc3.digitaloceanspaces.com",
            bucket="",
        )

        assert corrected_bucket == "mybucket"
        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["endpoint_url"] == "https://nyc3.digitaloceanspaces.com"

    def test_init_client_returns_bucket_name(self, s3_loader, mock_boto3):
        """Should return the bucket name (potentially corrected)."""
        result = s3_loader._init_client(
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
            region_name="us-east-1",
            bucket="my-bucket",
        )

        assert result == "my-bucket"


class TestIsTextFile:
    """Test text file detection."""

    def test_recognizes_common_text_extensions(self, s3_loader):
        """Should recognize common text file extensions."""
        text_files = [
            "readme.txt",
            "docs.md",
            "config.json",
            "data.yaml",
            "script.py",
            "app.js",
            "main.go",
            "style.css",
            "index.html",
        ]
        for filename in text_files:
            assert s3_loader.is_text_file(filename), f"{filename} should be text"

    def test_rejects_binary_extensions(self, s3_loader):
        """Should reject binary file extensions."""
        binary_files = ["image.png", "photo.jpg", "archive.zip", "app.exe", "doc.pdf"]
        for filename in binary_files:
            assert not s3_loader.is_text_file(filename), f"{filename} should not be text"

    def test_case_insensitive_matching(self, s3_loader):
        """Should match extensions case-insensitively."""
        assert s3_loader.is_text_file("README.TXT")
        assert s3_loader.is_text_file("Config.JSON")
        assert s3_loader.is_text_file("Script.PY")


class TestIsSupportedDocument:
    """Test document file detection."""

    def test_recognizes_document_extensions(self, s3_loader):
        """Should recognize document file extensions."""
        doc_files = [
            "report.pdf",
            "document.docx",
            "spreadsheet.xlsx",
            "presentation.pptx",
            "book.epub",
        ]
        for filename in doc_files:
            assert s3_loader.is_supported_document(
                filename
            ), f"{filename} should be document"

    def test_rejects_non_document_extensions(self, s3_loader):
        """Should reject non-document file extensions."""
        non_doc_files = ["image.png", "script.py", "readme.txt", "archive.zip"]
        for filename in non_doc_files:
            assert not s3_loader.is_supported_document(
                filename
            ), f"{filename} should not be document"

    def test_case_insensitive_matching(self, s3_loader):
        """Should match extensions case-insensitively."""
        assert s3_loader.is_supported_document("Report.PDF")
        assert s3_loader.is_supported_document("Document.DOCX")


class TestListObjects:
    """Test S3 object listing."""

    def test_list_objects_returns_file_keys(self, s3_loader, mock_boto3):
        """Should return list of file keys from bucket."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "file1.txt"},
                    {"Key": "file2.md"},
                    {"Key": "folder/"},  # Directory marker, should be skipped
                    {"Key": "folder/file3.py"},
                ]
            }
        ]

        result = s3_loader.list_objects("test-bucket", "")

        assert result == ["file1.txt", "file2.md", "folder/file3.py"]
        mock_client.get_paginator.assert_called_once_with("list_objects_v2")
        paginator.paginate.assert_called_once_with(Bucket="test-bucket", Prefix="")

    def test_list_objects_with_prefix(self, s3_loader):
        """Should filter objects by prefix."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "docs/readme.md"}, {"Key": "docs/guide.txt"}]}
        ]

        result = s3_loader.list_objects("test-bucket", "docs/")

        paginator.paginate.assert_called_once_with(Bucket="test-bucket", Prefix="docs/")
        assert len(result) == 2

    def test_list_objects_handles_empty_bucket(self, s3_loader):
        """Should return empty list for empty bucket."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{}]  # No Contents key

        result = s3_loader.list_objects("test-bucket", "")

        assert result == []

    def test_list_objects_raises_on_no_such_bucket(self, s3_loader):
        """Should raise exception when bucket doesn't exist."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value.__iter__ = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "NoSuchBucket", "Message": "Bucket not found"}},
                "ListObjectsV2",
            )
        )

        with pytest.raises(Exception, match="does not exist"):
            s3_loader.list_objects("nonexistent-bucket", "")

    def test_list_objects_raises_on_access_denied(self, s3_loader):
        """Should raise exception on access denied."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value.__iter__ = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
                "ListObjectsV2",
            )
        )

        with pytest.raises(Exception, match="Access denied"):
            s3_loader.list_objects("test-bucket", "")

    def test_list_objects_raises_on_no_credentials(self, s3_loader):
        """Should raise exception when credentials are missing."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value.__iter__ = MagicMock(
            side_effect=NoCredentialsError()
        )

        with pytest.raises(Exception, match="credentials not found"):
            s3_loader.list_objects("test-bucket", "")


class TestGetObjectContent:
    """Test S3 object content retrieval."""

    def test_get_text_file_content(self, s3_loader):
        """Should return decoded text content for text files."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client

        mock_body = MagicMock()
        mock_body.read.return_value = b"Hello, World!"
        mock_client.get_object.return_value = {"Body": mock_body}

        result = s3_loader.get_object_content("test-bucket", "readme.txt")

        assert result == "Hello, World!"
        mock_client.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="readme.txt"
        )

    def test_skip_unsupported_file_types(self, s3_loader):
        """Should return None for unsupported file types."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client

        result = s3_loader.get_object_content("test-bucket", "image.png")

        assert result is None
        mock_client.get_object.assert_not_called()

    def test_skip_empty_text_files(self, s3_loader):
        """Should return None for empty text files."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client

        mock_body = MagicMock()
        mock_body.read.return_value = b"   \n\t  "
        mock_client.get_object.return_value = {"Body": mock_body}

        result = s3_loader.get_object_content("test-bucket", "empty.txt")

        assert result is None

    def test_returns_none_on_unicode_decode_error(self, s3_loader):
        """Should return None when text file can't be decoded."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client

        mock_body = MagicMock()
        mock_body.read.return_value = b"\xff\xfe"  # Invalid UTF-8
        mock_client.get_object.return_value = {"Body": mock_body}

        result = s3_loader.get_object_content("test-bucket", "binary.txt")

        assert result is None

    def test_returns_none_on_no_such_key(self, s3_loader):
        """Should return None when object doesn't exist."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client
        mock_client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Key not found"}},
            "GetObject",
        )

        result = s3_loader.get_object_content("test-bucket", "missing.txt")

        assert result is None

    def test_returns_none_on_access_denied(self, s3_loader):
        """Should return None when access is denied."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client
        mock_client.get_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "GetObject",
        )

        result = s3_loader.get_object_content("test-bucket", "secret.txt")

        assert result is None

    def test_processes_document_files(self, s3_loader):
        """Should process document files through parser."""
        mock_client = MagicMock()
        s3_loader.s3_client = mock_client

        mock_body = MagicMock()
        mock_body.read.return_value = b"PDF content"
        mock_client.get_object.return_value = {"Body": mock_body}

        with patch.object(
            s3_loader, "_process_document", return_value="Extracted text"
        ) as mock_process:
            result = s3_loader.get_object_content("test-bucket", "document.pdf")

        assert result == "Extracted text"
        mock_process.assert_called_once_with(b"PDF content", "document.pdf")


class TestLoadData:
    """Test main load_data method."""

    def test_load_data_from_dict_input(self, s3_loader, mock_boto3):
        """Should load documents from dict input."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        # Setup mock paginator
        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "readme.md"}, {"Key": "guide.txt"}]}
        ]

        # Setup mock get_object
        def get_object_side_effect(Bucket, Key):
            mock_body = MagicMock()
            mock_body.read.return_value = f"Content of {Key}".encode()
            return {"Body": mock_body}

        mock_client.get_object.side_effect = get_object_side_effect

        input_data = {
            "aws_access_key_id": "test-key",
            "aws_secret_access_key": "test-secret",
            "bucket": "test-bucket",
        }

        docs = s3_loader.load_data(input_data)

        assert len(docs) == 2
        assert docs[0].text == "Content of readme.md"
        assert docs[0].extra_info["bucket"] == "test-bucket"
        assert docs[0].extra_info["key"] == "readme.md"
        assert docs[0].extra_info["source"] == "s3://test-bucket/readme.md"

    def test_load_data_from_json_string(self, s3_loader, mock_boto3):
        """Should load documents from JSON string input."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{"Contents": [{"Key": "file.txt"}]}]

        mock_body = MagicMock()
        mock_body.read.return_value = b"File content"
        mock_client.get_object.return_value = {"Body": mock_body}

        input_json = json.dumps(
            {
                "aws_access_key_id": "test-key",
                "aws_secret_access_key": "test-secret",
                "bucket": "test-bucket",
            }
        )

        docs = s3_loader.load_data(input_json)

        assert len(docs) == 1
        assert docs[0].text == "File content"

    def test_load_data_with_prefix(self, s3_loader, mock_boto3):
        """Should filter objects by prefix."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{"Contents": [{"Key": "docs/readme.md"}]}]

        mock_body = MagicMock()
        mock_body.read.return_value = b"Documentation"
        mock_client.get_object.return_value = {"Body": mock_body}

        input_data = {
            "aws_access_key_id": "test-key",
            "aws_secret_access_key": "test-secret",
            "bucket": "test-bucket",
            "prefix": "docs/",
        }

        s3_loader.load_data(input_data)

        paginator.paginate.assert_called_once_with(Bucket="test-bucket", Prefix="docs/")

    def test_load_data_with_custom_region(self, s3_loader, mock_boto3):
        """Should use custom region."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{}]

        input_data = {
            "aws_access_key_id": "test-key",
            "aws_secret_access_key": "test-secret",
            "bucket": "test-bucket",
            "region": "eu-west-1",
        }

        s3_loader.load_data(input_data)

        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["region_name"] == "eu-west-1"

    def test_load_data_with_custom_endpoint(self, s3_loader, mock_boto3):
        """Should use custom endpoint URL."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{}]

        input_data = {
            "aws_access_key_id": "test-key",
            "aws_secret_access_key": "test-secret",
            "bucket": "test-bucket",
            "endpoint_url": "https://nyc3.digitaloceanspaces.com",
        }

        s3_loader.load_data(input_data)

        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["endpoint_url"] == "https://nyc3.digitaloceanspaces.com"

    def test_load_data_raises_on_invalid_json(self, s3_loader):
        """Should raise ValueError for invalid JSON input."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            s3_loader.load_data("not valid json")

    def test_load_data_raises_on_missing_required_fields(self, s3_loader):
        """Should raise ValueError when required fields are missing."""
        with pytest.raises(ValueError, match="Missing required fields"):
            s3_loader.load_data({"aws_access_key_id": "test-key"})

        with pytest.raises(ValueError, match="Missing required fields"):
            s3_loader.load_data(
                {"aws_access_key_id": "test-key", "aws_secret_access_key": "secret"}
            )

    def test_load_data_skips_unsupported_files(self, s3_loader, mock_boto3):
        """Should skip unsupported file types."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "readme.txt"},
                    {"Key": "image.png"},  # Unsupported
                    {"Key": "photo.jpg"},  # Unsupported
                ]
            }
        ]

        def get_object_side_effect(Bucket, Key):
            mock_body = MagicMock()
            mock_body.read.return_value = b"Text content"
            return {"Body": mock_body}

        mock_client.get_object.side_effect = get_object_side_effect

        input_data = {
            "aws_access_key_id": "test-key",
            "aws_secret_access_key": "test-secret",
            "bucket": "test-bucket",
        }

        docs = s3_loader.load_data(input_data)

        # Only txt file should be loaded
        assert len(docs) == 1
        assert docs[0].extra_info["key"] == "readme.txt"

    def test_load_data_uses_corrected_bucket_from_endpoint(self, s3_loader, mock_boto3):
        """Should use bucket name extracted from DO Spaces URL."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{"Contents": [{"Key": "file.txt"}]}]

        mock_body = MagicMock()
        mock_body.read.return_value = b"Content"
        mock_client.get_object.return_value = {"Body": mock_body}

        input_data = {
            "aws_access_key_id": "test-key",
            "aws_secret_access_key": "test-secret",
            "bucket": "wrong-bucket",  # Will be corrected from endpoint
            "endpoint_url": "https://mybucket.nyc3.digitaloceanspaces.com",
        }

        docs = s3_loader.load_data(input_data)

        # Verify bucket name was corrected
        paginator.paginate.assert_called_once_with(Bucket="mybucket", Prefix="")
        assert docs[0].extra_info["bucket"] == "mybucket"


class TestProcessDocument:
    """Test document processing."""

    def test_process_document_extracts_text(self, s3_loader):
        """Should extract text from document files."""
        mock_doc = MagicMock()
        mock_doc.text = "Extracted document text"

        with patch(
            "application.parser.file.bulk.SimpleDirectoryReader"
        ) as mock_reader_class:
            mock_reader = MagicMock()
            mock_reader.load_data.return_value = [mock_doc]
            mock_reader_class.return_value = mock_reader

            with patch("tempfile.NamedTemporaryFile") as mock_temp:
                mock_file = MagicMock()
                mock_file.__enter__ = MagicMock(return_value=mock_file)
                mock_file.__exit__ = MagicMock(return_value=False)
                mock_file.name = "/tmp/test.pdf"
                mock_temp.return_value = mock_file

                with patch("os.path.exists", return_value=True):
                    with patch("os.unlink"):
                        result = s3_loader._process_document(
                            b"PDF content", "document.pdf"
                        )

        assert result == "Extracted document text"

    def test_process_document_returns_none_on_error(self, s3_loader):
        """Should return None when document processing fails."""
        with patch(
            "application.parser.file.bulk.SimpleDirectoryReader"
        ) as mock_reader_class:
            mock_reader_class.side_effect = Exception("Parse error")

            with patch("tempfile.NamedTemporaryFile") as mock_temp:
                mock_file = MagicMock()
                mock_file.__enter__ = MagicMock(return_value=mock_file)
                mock_file.__exit__ = MagicMock(return_value=False)
                mock_file.name = "/tmp/test.pdf"
                mock_temp.return_value = mock_file

                with patch("os.path.exists", return_value=True):
                    with patch("os.unlink"):
                        result = s3_loader._process_document(
                            b"PDF content", "document.pdf"
                        )

        assert result is None

    def test_process_document_cleans_up_temp_file(self, s3_loader):
        """Should clean up temporary file after processing."""
        with patch(
            "application.parser.file.bulk.SimpleDirectoryReader"
        ) as mock_reader_class:
            mock_reader = MagicMock()
            mock_reader.load_data.return_value = []
            mock_reader_class.return_value = mock_reader

            with patch("tempfile.NamedTemporaryFile") as mock_temp:
                mock_file = MagicMock()
                mock_file.__enter__ = MagicMock(return_value=mock_file)
                mock_file.__exit__ = MagicMock(return_value=False)
                mock_file.name = "/tmp/test.pdf"
                mock_temp.return_value = mock_file

                with patch("os.path.exists", return_value=True) as mock_exists:
                    with patch("os.unlink") as mock_unlink:
                        s3_loader._process_document(b"PDF content", "document.pdf")

                        mock_exists.assert_called_with("/tmp/test.pdf")
                        mock_unlink.assert_called_with("/tmp/test.pdf")
