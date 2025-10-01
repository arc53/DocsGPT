"""Tests for LocalStorage implementation
"""

import io
import pytest
from unittest.mock import patch, MagicMock, mock_open

from application.storage.local import LocalStorage


@pytest.fixture
def temp_base_dir():
    """Provide a temporary base directory path for testing."""
    return "/tmp/test_storage"


@pytest.fixture
def local_storage(temp_base_dir):
    """Create LocalStorage instance with test base directory."""
    return LocalStorage(base_dir=temp_base_dir)


class TestLocalStorageInitialization:
    """Test LocalStorage initialization and configuration."""

    def test_init_with_custom_base_dir(self):
        """Should use provided base directory."""
        storage = LocalStorage(base_dir="/custom/path")
        assert storage.base_dir == "/custom/path"

    def test_init_with_default_base_dir(self):
        """Should use default base directory when none provided."""
        storage = LocalStorage()
        # Default is three levels up from the file location
        assert storage.base_dir is not None
        assert isinstance(storage.base_dir, str)

    def test_get_full_path_with_relative_path(self, local_storage):
        """Should combine base_dir with relative path."""
        result = local_storage._get_full_path("documents/test.txt")
        assert result == "/tmp/test_storage/documents/test.txt"

    def test_get_full_path_with_absolute_path(self, local_storage):
        """Should return absolute path unchanged."""
        result = local_storage._get_full_path("/absolute/path/test.txt")
        assert result == "/absolute/path/test.txt"


class TestLocalStorageSaveFile:
    """Test file saving functionality."""

    @patch('os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    @patch('shutil.copyfileobj')
    def test_save_file_creates_directory_and_saves(
        self, mock_copyfileobj, mock_file, mock_makedirs, local_storage
    ):
        """Should create directory and save file content."""
        file_data = io.BytesIO(b"test content")
        path = "documents/test.txt"

        result = local_storage.save_file(file_data, path)

        # Verify directory creation
        mock_makedirs.assert_called_once_with(
            "/tmp/test_storage/documents",
            exist_ok=True
        )

        # Verify file write
        mock_file.assert_called_once_with("/tmp/test_storage/documents/test.txt", 'wb')
        mock_copyfileobj.assert_called_once_with(file_data, mock_file())

        # Verify result
        assert result == {'storage_type': 'local'}

    @patch('os.makedirs')
    def test_save_file_with_save_method(self, mock_makedirs, local_storage):
        """Should use save method if file_data has it."""
        file_data = MagicMock()
        file_data.save = MagicMock()
        path = "documents/test.txt"

        result = local_storage.save_file(file_data, path)

        # Verify save method was called
        file_data.save.assert_called_once_with("/tmp/test_storage/documents/test.txt")

        # Verify result
        assert result == {'storage_type': 'local'}

    @patch('os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    def test_save_file_with_absolute_path(self, mock_file, mock_makedirs, local_storage):
        """Should handle absolute paths correctly."""
        file_data = io.BytesIO(b"test content")
        path = "/absolute/path/test.txt"

        local_storage.save_file(file_data, path)

        mock_makedirs.assert_called_once_with("/absolute/path", exist_ok=True)
        mock_file.assert_called_once_with("/absolute/path/test.txt", 'wb')


class TestLocalStorageGetFile:
    """Test file retrieval functionality."""

    @patch('os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data=b"file content")
    def test_get_file_returns_file_handle(self, mock_file, mock_exists, local_storage):
        """Should open and return file handle when file exists."""
        path = "documents/test.txt"

        result = local_storage.get_file(path)

        mock_exists.assert_called_once_with("/tmp/test_storage/documents/test.txt")
        mock_file.assert_called_once_with("/tmp/test_storage/documents/test.txt", 'rb')
        assert result is not None

    @patch('os.path.exists', return_value=False)
    def test_get_file_raises_error_when_not_found(self, mock_exists, local_storage):
        """Should raise FileNotFoundError when file doesn't exist."""
        path = "documents/nonexistent.txt"

        with pytest.raises(FileNotFoundError, match="File not found"):
            local_storage.get_file(path)

        mock_exists.assert_called_once_with("/tmp/test_storage/documents/nonexistent.txt")


class TestLocalStorageDeleteFile:
    """Test file deletion functionality."""

    @patch('os.remove')
    @patch('os.path.exists', return_value=True)
    def test_delete_file_removes_existing_file(self, mock_exists, mock_remove, local_storage):
        """Should delete file and return True when file exists."""
        path = "documents/test.txt"

        result = local_storage.delete_file(path)

        assert result is True
        mock_exists.assert_called_once_with("/tmp/test_storage/documents/test.txt")
        mock_remove.assert_called_once_with("/tmp/test_storage/documents/test.txt")

    @patch('os.path.exists', return_value=False)
    def test_delete_file_returns_false_when_not_found(self, mock_exists, local_storage):
        """Should return False when file doesn't exist."""
        path = "documents/nonexistent.txt"

        result = local_storage.delete_file(path)

        assert result is False
        mock_exists.assert_called_once_with("/tmp/test_storage/documents/nonexistent.txt")


class TestLocalStorageFileExists:
    """Test file existence checking."""

    @patch('os.path.exists', return_value=True)
    def test_file_exists_returns_true_when_file_found(self, mock_exists, local_storage):
        """Should return True when file exists."""
        path = "documents/test.txt"

        result = local_storage.file_exists(path)

        assert result is True
        mock_exists.assert_called_once_with("/tmp/test_storage/documents/test.txt")

    @patch('os.path.exists', return_value=False)
    def test_file_exists_returns_false_when_not_found(self, mock_exists, local_storage):
        """Should return False when file doesn't exist."""
        path = "documents/nonexistent.txt"

        result = local_storage.file_exists(path)

        assert result is False
        mock_exists.assert_called_once_with("/tmp/test_storage/documents/nonexistent.txt")


class TestLocalStorageListFiles:
    """Test directory listing functionality."""

    @patch('os.walk')
    @patch('os.path.exists', return_value=True)
    def test_list_files_returns_all_files_in_directory(
        self, mock_exists, mock_walk, local_storage
    ):
        """Should return all files in directory and subdirectories."""
        directory = "documents"

        # Mock os.walk to return files in directory structure
        mock_walk.return_value = [
            ("/tmp/test_storage/documents", ["subdir"], ["file1.txt", "file2.txt"]),
            ("/tmp/test_storage/documents/subdir", [], ["file3.txt"])
        ]

        result = local_storage.list_files(directory)

        assert len(result) == 3
        assert "documents/file1.txt" in result
        assert "documents/file2.txt" in result
        assert "documents/subdir/file3.txt" in result

        mock_exists.assert_called_once_with("/tmp/test_storage/documents")
        mock_walk.assert_called_once_with("/tmp/test_storage/documents")

    @patch('os.path.exists', return_value=False)
    def test_list_files_returns_empty_list_when_directory_not_found(
        self, mock_exists, local_storage
    ):
        """Should return empty list when directory doesn't exist."""
        directory = "nonexistent"

        result = local_storage.list_files(directory)

        assert result == []
        mock_exists.assert_called_once_with("/tmp/test_storage/nonexistent")


class TestLocalStorageProcessFile:
    """Test file processing functionality."""

    @patch('os.path.exists', return_value=True)
    def test_process_file_calls_processor_with_full_path(
        self, mock_exists, local_storage
    ):
        """Should call processor function with full file path."""
        path = "documents/test.txt"
        processor_func = MagicMock(return_value="processed")

        result = local_storage.process_file(path, processor_func, extra_arg="value")

        assert result == "processed"
        processor_func.assert_called_once_with(
            local_path="/tmp/test_storage/documents/test.txt",
            extra_arg="value"
        )
        mock_exists.assert_called_once_with("/tmp/test_storage/documents/test.txt")

    @patch('os.path.exists', return_value=False)
    def test_process_file_raises_error_when_file_not_found(self, mock_exists, local_storage):
        """Should raise FileNotFoundError when file doesn't exist."""
        path = "documents/nonexistent.txt"
        processor_func = MagicMock()

        with pytest.raises(FileNotFoundError, match="File not found"):
            local_storage.process_file(path, processor_func)

        processor_func.assert_not_called()


class TestLocalStorageIsDirectory:
    """Test directory checking functionality."""

    @patch('os.path.isdir', return_value=True)
    def test_is_directory_returns_true_when_directory_exists(
        self, mock_isdir, local_storage
    ):
        """Should return True when path is a directory."""
        path = "documents"

        result = local_storage.is_directory(path)

        assert result is True
        mock_isdir.assert_called_once_with("/tmp/test_storage/documents")

    @patch('os.path.isdir', return_value=False)
    def test_is_directory_returns_false_when_not_directory(
        self, mock_isdir, local_storage
    ):
        """Should return False when path is not a directory or doesn't exist."""
        path = "documents/test.txt"

        result = local_storage.is_directory(path)

        assert result is False
        mock_isdir.assert_called_once_with("/tmp/test_storage/documents/test.txt")


class TestLocalStorageRemoveDirectory:
    """Test directory removal functionality."""

    @patch('shutil.rmtree')
    @patch('os.path.isdir', return_value=True)
    @patch('os.path.exists', return_value=True)
    def test_remove_directory_deletes_directory(
        self, mock_exists, mock_isdir, mock_rmtree, local_storage
    ):
        """Should remove directory and return True when successful."""
        directory = "documents"

        result = local_storage.remove_directory(directory)

        assert result is True
        mock_exists.assert_called_once_with("/tmp/test_storage/documents")
        mock_isdir.assert_called_once_with("/tmp/test_storage/documents")
        mock_rmtree.assert_called_once_with("/tmp/test_storage/documents")

    @patch('os.path.exists', return_value=False)
    def test_remove_directory_returns_false_when_not_exists(
        self, mock_exists, local_storage
    ):
        """Should return False when directory doesn't exist."""
        directory = "nonexistent"

        result = local_storage.remove_directory(directory)

        assert result is False
        mock_exists.assert_called_once_with("/tmp/test_storage/nonexistent")

    @patch('os.path.isdir', return_value=False)
    @patch('os.path.exists', return_value=True)
    def test_remove_directory_returns_false_when_not_directory(
        self, mock_exists, mock_isdir, local_storage
    ):
        """Should return False when path is not a directory."""
        path = "documents/test.txt"

        result = local_storage.remove_directory(path)

        assert result is False
        mock_exists.assert_called_once_with("/tmp/test_storage/documents/test.txt")
        mock_isdir.assert_called_once_with("/tmp/test_storage/documents/test.txt")

    @patch('shutil.rmtree', side_effect=OSError("Permission denied"))
    @patch('os.path.isdir', return_value=True)
    @patch('os.path.exists', return_value=True)
    def test_remove_directory_returns_false_on_os_error(
        self, mock_exists, mock_isdir, mock_rmtree, local_storage
    ):
        """Should return False when OSError occurs during removal."""
        directory = "documents"

        result = local_storage.remove_directory(directory)

        assert result is False
        mock_rmtree.assert_called_once_with("/tmp/test_storage/documents")

    @patch('shutil.rmtree', side_effect=PermissionError("Access denied"))
    @patch('os.path.isdir', return_value=True)
    @patch('os.path.exists', return_value=True)
    def test_remove_directory_returns_false_on_permission_error(
        self, mock_exists, mock_isdir, mock_rmtree, local_storage
    ):
        """Should return False when PermissionError occurs during removal."""
        directory = "documents"

        result = local_storage.remove_directory(directory)

        assert result is False
        mock_rmtree.assert_called_once_with("/tmp/test_storage/documents")
