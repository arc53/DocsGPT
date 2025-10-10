"""Tests for S3 storage implementation."""

import io
from unittest.mock import MagicMock, patch

import pytest

from application.storage.s3 import S3Storage
from botocore.exceptions import ClientError


@pytest.fixture
def mock_boto3_client():
    """Mock boto3.client to isolate S3 client creation."""
    with patch("boto3.client") as mock_client:
        s3_mock = MagicMock()
        mock_client.return_value = s3_mock
        yield s3_mock


@pytest.fixture
def s3_storage(mock_boto3_client):
    """Create S3Storage instance with mocked boto3 client."""
    return S3Storage(bucket_name="test-bucket")


class TestS3StorageInitialization:
    """Test S3Storage initialization and configuration."""

    @pytest.mark.unit
    def test_init_with_default_bucket(self):
        """Should use default bucket name when none provided."""
        with patch("boto3.client"):
            storage = S3Storage()
            assert storage.bucket_name == "docsgpt-test-bucket"

    @pytest.mark.unit
    def test_init_with_custom_bucket(self):
        """Should use provided bucket name."""
        with patch("boto3.client"):
            storage = S3Storage(bucket_name="custom-bucket")
            assert storage.bucket_name == "custom-bucket"

    @pytest.mark.unit
    def test_init_creates_boto3_client(self):
        """Should create boto3 S3 client with credentials from settings."""
        with patch("boto3.client") as mock_client, patch(
            "application.storage.s3.settings"
        ) as mock_settings:

            mock_settings.SAGEMAKER_ACCESS_KEY = "test-key"
            mock_settings.SAGEMAKER_SECRET_KEY = "test-secret"
            mock_settings.SAGEMAKER_REGION = "us-west-2"

            S3Storage()

            mock_client.assert_called_once_with(
                "s3",
                aws_access_key_id="test-key",
                aws_secret_access_key="test-secret",
                region_name="us-west-2",
            )


class TestS3StorageSaveFile:
    """Test file saving functionality."""

    @pytest.mark.unit
    def test_save_file_uploads_to_s3(self, s3_storage, mock_boto3_client):
        """Should upload file to S3 with correct parameters."""
        file_data = io.BytesIO(b"test content")
        path = "documents/test.txt"

        with patch("application.storage.s3.settings") as mock_settings:
            mock_settings.SAGEMAKER_REGION = "us-east-1"
            result = s3_storage.save_file(file_data, path)
        mock_boto3_client.upload_fileobj.assert_called_once_with(
            file_data,
            "test-bucket",
            path,
            ExtraArgs={"StorageClass": "INTELLIGENT_TIERING"},
        )

        assert result == {
            "storage_type": "s3",
            "bucket_name": "test-bucket",
            "uri": "s3://test-bucket/documents/test.txt",
            "region": "us-east-1",
        }

    @pytest.mark.unit
    def test_save_file_with_custom_storage_class(self, s3_storage, mock_boto3_client):
        """Should use custom storage class when provided."""
        file_data = io.BytesIO(b"test content")
        path = "documents/test.txt"

        with patch("application.storage.s3.settings") as mock_settings:
            mock_settings.SAGEMAKER_REGION = "us-east-1"
            s3_storage.save_file(file_data, path, storage_class="STANDARD")
        mock_boto3_client.upload_fileobj.assert_called_once_with(
            file_data, "test-bucket", path, ExtraArgs={"StorageClass": "STANDARD"}
        )

    @pytest.mark.unit
    def test_save_file_propagates_client_error(self, s3_storage, mock_boto3_client):
        """Should propagate ClientError when upload fails."""
        file_data = io.BytesIO(b"test content")
        path = "documents/test.txt"

        mock_boto3_client.upload_fileobj.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "upload_fileobj",
        )

        with pytest.raises(ClientError):
            s3_storage.save_file(file_data, path)


class TestS3StorageFileExists:
    """Test file existence checking."""

    @pytest.mark.unit
    def test_file_exists_returns_true_when_file_found(
        self, s3_storage, mock_boto3_client
    ):
        """Should return True when head_object succeeds."""
        path = "documents/test.txt"
        mock_boto3_client.head_object.return_value = {"ContentLength": 100}

        result = s3_storage.file_exists(path)

        assert result is True
        mock_boto3_client.head_object.assert_called_once_with(
            Bucket="test-bucket", Key=path
        )

    @pytest.mark.unit
    def test_file_exists_returns_false_on_client_error(
        self, s3_storage, mock_boto3_client
    ):
        """Should return False when head_object raises ClientError."""
        path = "documents/nonexistent.txt"
        mock_boto3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "head_object"
        )

        result = s3_storage.file_exists(path)

        assert result is False


class TestS3StorageGetFile:
    """Test file retrieval functionality."""

    @pytest.mark.unit
    def test_get_file_downloads_and_returns_file_object(
        self, s3_storage, mock_boto3_client
    ):
        """Should download file from S3 and return BytesIO object."""
        path = "documents/test.txt"
        test_content = b"file content"

        mock_boto3_client.head_object.return_value = {}

        def mock_download(bucket, key, file_obj):
            file_obj.write(test_content)

        mock_boto3_client.download_fileobj.side_effect = mock_download

        result = s3_storage.get_file(path)

        assert isinstance(result, io.BytesIO)
        assert result.read() == test_content
        mock_boto3_client.download_fileobj.assert_called_once()

    @pytest.mark.unit
    def test_get_file_raises_error_when_file_not_found(
        self, s3_storage, mock_boto3_client
    ):
        """Should raise FileNotFoundError when file doesn't exist."""
        path = "documents/nonexistent.txt"
        mock_boto3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "head_object"
        )

        with pytest.raises(FileNotFoundError, match="File not found"):
            s3_storage.get_file(path)


class TestS3StorageDeleteFile:
    """Test file deletion functionality."""

    @pytest.mark.unit
    def test_delete_file_returns_true_on_success(self, s3_storage, mock_boto3_client):
        """Should return True when deletion succeeds."""
        path = "documents/test.txt"
        mock_boto3_client.delete_object.return_value = {}

        result = s3_storage.delete_file(path)

        assert result is True
        mock_boto3_client.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key=path
        )

    @pytest.mark.unit
    def test_delete_file_returns_false_on_client_error(
        self, s3_storage, mock_boto3_client
    ):
        """Should return False when deletion fails with ClientError."""
        path = "documents/test.txt"
        mock_boto3_client.delete_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "delete_object",
        )

        result = s3_storage.delete_file(path)

        assert result is False


class TestS3StorageListFiles:
    """Test directory listing functionality."""

    @pytest.mark.unit
    def test_list_files_returns_all_keys_with_prefix(
        self, s3_storage, mock_boto3_client
    ):
        """Should return all file keys matching the directory prefix."""
        directory = "documents/"

        paginator_mock = MagicMock()
        mock_boto3_client.get_paginator.return_value = paginator_mock
        paginator_mock.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "documents/file1.txt"},
                    {"Key": "documents/file2.txt"},
                    {"Key": "documents/subdir/file3.txt"},
                ]
            }
        ]

        result = s3_storage.list_files(directory)

        assert len(result) == 3
        assert "documents/file1.txt" in result
        assert "documents/file2.txt" in result
        assert "documents/subdir/file3.txt" in result

        mock_boto3_client.get_paginator.assert_called_once_with("list_objects_v2")
        paginator_mock.paginate.assert_called_once_with(
            Bucket="test-bucket", Prefix="documents/"
        )

    @pytest.mark.unit
    def test_list_files_returns_empty_list_when_no_contents(
        self, s3_storage, mock_boto3_client
    ):
        """Should return empty list when directory has no files."""
        directory = "empty/"

        paginator_mock = MagicMock()
        mock_boto3_client.get_paginator.return_value = paginator_mock
        paginator_mock.paginate.return_value = [{}]

        result = s3_storage.list_files(directory)

        assert result == []


class TestS3StorageProcessFile:
    """Test file processing functionality."""

    @pytest.mark.unit
    def test_process_file_downloads_and_processes_file(
        self, s3_storage, mock_boto3_client
    ):
        """Should download file to temp location and call processor function."""
        path = "documents/test.txt"

        mock_boto3_client.head_object.return_value = {}

        with patch("tempfile.NamedTemporaryFile") as mock_temp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test_file"
            mock_temp.return_value.__enter__.return_value = mock_file

            processor_func = MagicMock(return_value="processed")
            result = s3_storage.process_file(path, processor_func, extra_arg="value")
        assert result == "processed"
        processor_func.assert_called_once_with(
            local_path="/tmp/test_file", extra_arg="value"
        )
        mock_boto3_client.download_fileobj.assert_called_once()

    @pytest.mark.unit
    def test_process_file_raises_error_when_file_not_found(
        self, s3_storage, mock_boto3_client
    ):
        """Should raise FileNotFoundError when file doesn't exist."""
        path = "documents/nonexistent.txt"
        mock_boto3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "head_object"
        )

        processor_func = MagicMock()

        with pytest.raises(FileNotFoundError, match="File not found in S3"):
            s3_storage.process_file(path, processor_func)


class TestS3StorageIsDirectory:
    """Test directory checking functionality."""

    @pytest.mark.unit
    def test_is_directory_returns_true_when_objects_exist(
        self, s3_storage, mock_boto3_client
    ):
        """Should return True when objects exist with the directory prefix."""
        path = "documents/"

        mock_boto3_client.list_objects_v2.return_value = {
            "Contents": [{"Key": "documents/file1.txt"}]
        }

        result = s3_storage.is_directory(path)

        assert result is True
        mock_boto3_client.list_objects_v2.assert_called_once_with(
            Bucket="test-bucket", Prefix="documents/", MaxKeys=1
        )

    @pytest.mark.unit
    def test_is_directory_returns_false_when_no_objects_exist(
        self, s3_storage, mock_boto3_client
    ):
        """Should return False when no objects exist with the directory prefix."""
        path = "nonexistent/"

        mock_boto3_client.list_objects_v2.return_value = {}

        result = s3_storage.is_directory(path)

        assert result is False


class TestS3StorageRemoveDirectory:
    """Test directory removal functionality."""

    @pytest.mark.unit
    def test_remove_directory_deletes_all_objects(self, s3_storage, mock_boto3_client):
        """Should delete all objects with the directory prefix."""
        directory = "documents/"

        paginator_mock = MagicMock()
        mock_boto3_client.get_paginator.return_value = paginator_mock
        paginator_mock.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "documents/file1.txt"},
                    {"Key": "documents/file2.txt"},
                ]
            }
        ]

        mock_boto3_client.delete_objects.return_value = {
            "Deleted": [{"Key": "documents/file1.txt"}, {"Key": "documents/file2.txt"}]
        }

        result = s3_storage.remove_directory(directory)

        assert result is True
        mock_boto3_client.delete_objects.assert_called_once()
        call_args = mock_boto3_client.delete_objects.call_args[1]
        assert call_args["Bucket"] == "test-bucket"
        assert len(call_args["Delete"]["Objects"]) == 2

    @pytest.mark.unit
    def test_remove_directory_returns_false_when_empty(
        self, s3_storage, mock_boto3_client
    ):
        """Should return False when directory is empty (no objects to delete)."""
        directory = "empty/"

        paginator_mock = MagicMock()
        mock_boto3_client.get_paginator.return_value = paginator_mock
        paginator_mock.paginate.return_value = [{}]

        result = s3_storage.remove_directory(directory)

        assert result is False
        mock_boto3_client.delete_objects.assert_not_called()

    @pytest.mark.unit
    def test_remove_directory_returns_false_on_client_error(
        self, s3_storage, mock_boto3_client
    ):
        """Should return False when deletion fails with ClientError."""
        directory = "documents/"

        paginator_mock = MagicMock()
        mock_boto3_client.get_paginator.return_value = paginator_mock
        paginator_mock.paginate.return_value = [
            {"Contents": [{"Key": "documents/file1.txt"}]}
        ]

        mock_boto3_client.delete_objects.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "delete_objects",
        )

        result = s3_storage.remove_directory(directory)

        assert result is False
