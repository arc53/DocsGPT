import io
import os
from unittest.mock import MagicMock, mock_open, patch

import pytest
from application.storage.local import LocalStorage


@pytest.fixture
def temp_base_dir():
    return "/tmp/test_storage"


@pytest.fixture
def local_storage(temp_base_dir):
    return LocalStorage(base_dir=temp_base_dir)


@pytest.mark.unit
class TestLocalStorageInitialization:

    def test_init_with_custom_base_dir(self):
        storage = LocalStorage(base_dir="/custom/path")
        assert storage.base_dir == "/custom/path"

    def test_init_with_default_base_dir(self):
        storage = LocalStorage()
        assert storage.base_dir is not None
        assert isinstance(storage.base_dir, str)

    def test_get_full_path_with_relative_path(self, local_storage):
        result = local_storage._get_full_path("documents/test.txt")
        expected = os.path.join("/tmp/test_storage", "documents/test.txt")
        assert os.path.normpath(result) == os.path.normpath(expected)

    def test_get_full_path_with_absolute_path(self, local_storage):
        result = local_storage._get_full_path("/absolute/path/test.txt")
        assert result == "/absolute/path/test.txt"

    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("shutil.copyfileobj")
    def test_save_file_creates_directory_and_saves(
        self, mock_copyfileobj, mock_file, mock_makedirs, local_storage
    ):
        file_data = io.BytesIO(b"test content")
        path = "documents/test.txt"

        result = local_storage.save_file(file_data, path)

        expected_dir = os.path.join("/tmp/test_storage", "documents")
        expected_file = os.path.join("/tmp/test_storage", "documents/test.txt")

        assert mock_makedirs.call_count == 1
        assert os.path.normpath(mock_makedirs.call_args[0][0]) == os.path.normpath(
            expected_dir
        )
        assert mock_makedirs.call_args[1] == {"exist_ok": True}

        assert mock_file.call_count == 1
        assert os.path.normpath(mock_file.call_args[0][0]) == os.path.normpath(
            expected_file
        )
        assert mock_file.call_args[0][1] == "wb"

        mock_copyfileobj.assert_called_once_with(file_data, mock_file())
        assert result == {"storage_type": "local"}

    @patch("os.makedirs")
    def test_save_file_with_save_method(self, mock_makedirs, local_storage):
        file_data = MagicMock()
        file_data.save = MagicMock()
        path = "documents/test.txt"

        result = local_storage.save_file(file_data, path)

        expected_file = os.path.join("/tmp/test_storage", "documents/test.txt")
        assert file_data.save.call_count == 1
        assert os.path.normpath(file_data.save.call_args[0][0]) == os.path.normpath(
            expected_file
        )
        assert result == {"storage_type": "local"}

    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    def test_save_file_with_absolute_path(
        self, mock_file, mock_makedirs, local_storage
    ):
        file_data = io.BytesIO(b"test content")
        path = "/absolute/path/test.txt"

        local_storage.save_file(file_data, path)

        mock_makedirs.assert_called_once_with("/absolute/path", exist_ok=True)
        mock_file.assert_called_once_with("/absolute/path/test.txt", "wb")


@pytest.mark.unit
class TestLocalStorageGetFile:

    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=b"file content")
    def test_get_file_returns_file_handle(self, mock_file, mock_exists, local_storage):
        path = "documents/test.txt"

        result = local_storage.get_file(path)

        expected_path = os.path.join("/tmp/test_storage", "documents/test.txt")
        assert mock_exists.call_count == 1
        assert os.path.normpath(mock_exists.call_args[0][0]) == os.path.normpath(
            expected_path
        )
        assert mock_file.call_count == 1
        assert os.path.normpath(mock_file.call_args[0][0]) == os.path.normpath(
            expected_path
        )
        assert result is not None

    @patch("os.path.exists", return_value=False)
    def test_get_file_raises_error_when_not_found(self, mock_exists, local_storage):
        path = "documents/nonexistent.txt"

        with pytest.raises(FileNotFoundError, match="File not found"):
            local_storage.get_file(path)
        expected_path = os.path.join("/tmp/test_storage", "documents/nonexistent.txt")
        assert mock_exists.call_count == 1
        assert os.path.normpath(mock_exists.call_args[0][0]) == os.path.normpath(
            expected_path
        )


@pytest.mark.unit
class TestLocalStorageDeleteFile:

    @patch("os.remove")
    @patch("os.path.exists", return_value=True)
    def test_delete_file_removes_existing_file(
        self, mock_exists, mock_remove, local_storage
    ):
        path = "documents/test.txt"

        result = local_storage.delete_file(path)

        expected_path = os.path.join("/tmp/test_storage", "documents/test.txt")
        assert result is True
        assert mock_exists.call_count == 1
        assert os.path.normpath(mock_exists.call_args[0][0]) == os.path.normpath(
            expected_path
        )
        assert mock_remove.call_count == 1
        assert os.path.normpath(mock_remove.call_args[0][0]) == os.path.normpath(
            expected_path
        )

    @patch("os.path.exists", return_value=False)
    def test_delete_file_returns_false_when_not_found(self, mock_exists, local_storage):
        path = "documents/nonexistent.txt"

        result = local_storage.delete_file(path)

        expected_path = os.path.join("/tmp/test_storage", "documents/nonexistent.txt")
        assert result is False
        assert mock_exists.call_count == 1
        assert os.path.normpath(mock_exists.call_args[0][0]) == os.path.normpath(
            expected_path
        )


@pytest.mark.unit
class TestLocalStorageFileExists:

    @patch("os.path.exists", return_value=True)
    def test_file_exists_returns_true_when_file_found(self, mock_exists, local_storage):
        path = "documents/test.txt"

        result = local_storage.file_exists(path)

        expected_path = os.path.join("/tmp/test_storage", "documents/test.txt")
        assert result is True
        assert mock_exists.call_count == 1
        assert os.path.normpath(mock_exists.call_args[0][0]) == os.path.normpath(
            expected_path
        )

    @patch("os.path.exists", return_value=False)
    def test_file_exists_returns_false_when_not_found(self, mock_exists, local_storage):
        path = "documents/nonexistent.txt"

        result = local_storage.file_exists(path)

        expected_path = os.path.join("/tmp/test_storage", "documents/nonexistent.txt")
        assert result is False
        assert mock_exists.call_count == 1
        assert os.path.normpath(mock_exists.call_args[0][0]) == os.path.normpath(
            expected_path
        )


@pytest.mark.unit
class TestLocalStorageListFiles:

    @patch("os.walk")
    @patch("os.path.exists", return_value=True)
    def test_list_files_returns_all_files_in_directory(
        self, mock_exists, mock_walk, local_storage
    ):
        directory = "documents"
        base_dir = os.path.join("/tmp/test_storage", "documents")

        mock_walk.return_value = [
            (base_dir, ["subdir"], ["file1.txt", "file2.txt"]),
            (os.path.join(base_dir, "subdir"), [], ["file3.txt"]),
        ]

        result = local_storage.list_files(directory)

        assert len(result) == 3
        result_normalized = [os.path.normpath(f) for f in result]
        assert os.path.normpath("documents/file1.txt") in result_normalized
        assert os.path.normpath("documents/file2.txt") in result_normalized
        assert os.path.normpath("documents/subdir/file3.txt") in result_normalized

    @patch("os.path.exists", return_value=False)
    def test_list_files_returns_empty_list_when_directory_not_found(
        self, mock_exists, local_storage
    ):
        directory = "nonexistent"

        result = local_storage.list_files(directory)

        expected_path = os.path.join("/tmp/test_storage", "nonexistent")
        assert result == []
        assert mock_exists.call_count == 1
        assert os.path.normpath(mock_exists.call_args[0][0]) == os.path.normpath(
            expected_path
        )


@pytest.mark.unit
class TestLocalStorageProcessFile:

    @patch("os.path.exists", return_value=True)
    def test_process_file_calls_processor_with_full_path(
        self, mock_exists, local_storage
    ):
        path = "documents/test.txt"
        processor_func = MagicMock(return_value="processed")

        result = local_storage.process_file(path, processor_func, extra_arg="value")

        expected_path = os.path.join("/tmp/test_storage", "documents/test.txt")
        assert result == "processed"
        assert processor_func.call_count == 1
        call_kwargs = processor_func.call_args[1]
        assert os.path.normpath(call_kwargs["local_path"]) == os.path.normpath(
            expected_path
        )
        assert call_kwargs["extra_arg"] == "value"

    @patch("os.path.exists", return_value=False)
    def test_process_file_raises_error_when_file_not_found(
        self, mock_exists, local_storage
    ):
        path = "documents/nonexistent.txt"
        processor_func = MagicMock()

        with pytest.raises(FileNotFoundError, match="File not found"):
            local_storage.process_file(path, processor_func)
        processor_func.assert_not_called()


@pytest.mark.unit
class TestLocalStorageIsDirectory:

    @patch("os.path.isdir", return_value=True)
    def test_is_directory_returns_true_when_directory_exists(
        self, mock_isdir, local_storage
    ):
        path = "documents"

        result = local_storage.is_directory(path)

        expected_path = os.path.join("/tmp/test_storage", "documents")
        assert result is True
        assert mock_isdir.call_count == 1
        assert os.path.normpath(mock_isdir.call_args[0][0]) == os.path.normpath(
            expected_path
        )

    @patch("os.path.isdir", return_value=False)
    def test_is_directory_returns_false_when_not_directory(
        self, mock_isdir, local_storage
    ):
        path = "documents/test.txt"

        result = local_storage.is_directory(path)

        expected_path = os.path.join("/tmp/test_storage", "documents/test.txt")
        assert result is False
        assert mock_isdir.call_count == 1
        assert os.path.normpath(mock_isdir.call_args[0][0]) == os.path.normpath(
            expected_path
        )


@pytest.mark.unit
class TestLocalStorageRemoveDirectory:

    @patch("shutil.rmtree")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    def test_remove_directory_deletes_directory(
        self, mock_exists, mock_isdir, mock_rmtree, local_storage
    ):
        directory = "documents"

        result = local_storage.remove_directory(directory)

        expected_path = os.path.join("/tmp/test_storage", "documents")
        assert result is True
        assert mock_exists.call_count == 1
        assert os.path.normpath(mock_exists.call_args[0][0]) == os.path.normpath(
            expected_path
        )
        assert mock_isdir.call_count == 1
        assert os.path.normpath(mock_isdir.call_args[0][0]) == os.path.normpath(
            expected_path
        )
        assert mock_rmtree.call_count == 1
        assert os.path.normpath(mock_rmtree.call_args[0][0]) == os.path.normpath(
            expected_path
        )

    @patch("os.path.exists", return_value=False)
    def test_remove_directory_returns_false_when_not_exists(
        self, mock_exists, local_storage
    ):
        directory = "nonexistent"

        result = local_storage.remove_directory(directory)

        expected_path = os.path.join("/tmp/test_storage", "nonexistent")
        assert result is False
        assert mock_exists.call_count == 1
        assert os.path.normpath(mock_exists.call_args[0][0]) == os.path.normpath(
            expected_path
        )

    @patch("os.path.isdir", return_value=False)
    @patch("os.path.exists", return_value=True)
    def test_remove_directory_returns_false_when_not_directory(
        self, mock_exists, mock_isdir, local_storage
    ):
        path = "documents/test.txt"

        result = local_storage.remove_directory(path)

        expected_path = os.path.join("/tmp/test_storage", "documents/test.txt")
        assert result is False
        assert mock_exists.call_count == 1
        assert os.path.normpath(mock_exists.call_args[0][0]) == os.path.normpath(
            expected_path
        )
        assert mock_isdir.call_count == 1
        assert os.path.normpath(mock_isdir.call_args[0][0]) == os.path.normpath(
            expected_path
        )

    @patch("shutil.rmtree", side_effect=OSError("Permission denied"))
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    def test_remove_directory_returns_false_on_os_error(
        self, mock_exists, mock_isdir, mock_rmtree, local_storage
    ):
        directory = "documents"

        result = local_storage.remove_directory(directory)

        expected_path = os.path.join("/tmp/test_storage", "documents")
        assert result is False
        assert mock_rmtree.call_count == 1
        assert os.path.normpath(mock_rmtree.call_args[0][0]) == os.path.normpath(
            expected_path
        )

    @patch("shutil.rmtree", side_effect=PermissionError("Access denied"))
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    def test_remove_directory_returns_false_on_permission_error(
        self, mock_exists, mock_isdir, mock_rmtree, local_storage
    ):
        directory = "documents"

        result = local_storage.remove_directory(directory)

        expected_path = os.path.join("/tmp/test_storage", "documents")
        assert result is False
        assert mock_rmtree.call_count == 1
        assert os.path.normpath(mock_rmtree.call_args[0][0]) == os.path.normpath(
            expected_path
        )
