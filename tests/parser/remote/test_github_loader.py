import base64
import pytest
from unittest.mock import patch, MagicMock
import requests

from application.parser.remote.github_loader import GitHubLoader


def make_response(json_data=None, status_code=200, raise_error=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    if raise_error is not None:
        resp.raise_for_status.side_effect = raise_error
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestGitHubLoaderFetchFileContent:
    @patch("application.parser.remote.github_loader.requests.get")
    def test_text_file_base64_decoded(self, mock_get):
        loader = GitHubLoader()
        content_str = "Hello from README"
        b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
        mock_get.return_value = make_response({"encoding": "base64", "content": b64})

        result = loader.fetch_file_content("owner/repo", "README.md")

        assert result == f"Filename: README.md\n\n{content_str}"
        mock_get.assert_called_once_with(
            "https://api.github.com/repos/owner/repo/contents/README.md",
            headers=loader.headers,
        )

    @patch("application.parser.remote.github_loader.requests.get")
    def test_binary_file_skipped(self, mock_get):
        loader = GitHubLoader()
        mock_get.return_value = make_response({"encoding": "base64", "content": "AAAA"})

        result = loader.fetch_file_content("owner/repo", "image.png")

        assert result == "Filename: image.png is a binary file and was skipped."

    @patch("application.parser.remote.github_loader.requests.get")
    def test_non_base64_plain_content(self, mock_get):
        loader = GitHubLoader()
        mock_get.return_value = make_response({"encoding": "", "content": "Plain text"})

        result = loader.fetch_file_content("owner/repo", "file.txt")

        assert result == "Filename: file.txt\n\nPlain text"

    @patch("application.parser.remote.github_loader.requests.get")
    def test_http_error_raises(self, mock_get):
        loader = GitHubLoader()
        http_err = requests.HTTPError("Not found")
        mock_get.return_value = make_response(status_code=404, raise_error=http_err)

        with pytest.raises(requests.HTTPError):
            loader.fetch_file_content("owner/repo", "missing.txt")


class TestGitHubLoaderFetchRepoFiles:
    @patch("application.parser.remote.github_loader.requests.get")
    def test_recurses_directories(self, mock_get):
        loader = GitHubLoader()

        def side_effect(url, headers=None):
            if url.endswith("/contents/"):
                return make_response([
                    {"type": "file", "path": "README.md"},
                    {"type": "dir", "path": "src"},
                ])
            elif url.endswith("/contents/src"):
                return make_response([
                    {"type": "file", "path": "src/main.py"},
                    {"type": "file", "path": "src/util.py"},
                ])
            raise AssertionError(f"Unexpected URL: {url}")

        mock_get.side_effect = side_effect

        files = loader.fetch_repo_files("owner/repo", path="")
        assert set(files) == {"README.md", "src/main.py", "src/util.py"}


class TestGitHubLoaderLoadData:
    def test_load_data_builds_documents_from_files(self, monkeypatch):
        loader = GitHubLoader()

        # Stub out network-dependent methods
        monkeypatch.setattr(loader, "fetch_repo_files", lambda repo, path="": [
            "README.md", "src/main.py"
        ])

        def fake_fetch_content(repo, file_path):
            return f"content for {file_path}"

        monkeypatch.setattr(loader, "fetch_file_content", fake_fetch_content)

        docs = loader.load_data("https://github.com/owner/repo")

        assert len(docs) == 2
        assert docs[0].page_content == "content for README.md"
        assert docs[0].metadata == {
            "title": "README.md",
            "source": "https://github.com/owner/repo/blob/main/README.md",
        }
        assert docs[1].page_content == "content for src/main.py"
        assert docs[1].metadata == {
            "title": "src/main.py",
            "source": "https://github.com/owner/repo/blob/main/src/main.py",
        }




class TestGitHubLoaderRobustness:
    @patch("application.parser.remote.github_loader.requests.get")
    def test_fetch_repo_files_non_json_raises(self, mock_get):
        resp = MagicMock()
        resp.json.side_effect = ValueError("No JSON")
        mock_get.return_value = resp
        with pytest.raises(ValueError):
            GitHubLoader().fetch_repo_files("owner/repo")

    @patch("application.parser.remote.github_loader.requests.get")
    def test_fetch_repo_files_unexpected_shape_missing_type_raises(self, mock_get):
        # Missing 'type' in items should raise KeyError when accessed
        mock_get.return_value = make_response([{"path": "README.md"}])
        with pytest.raises(KeyError):
            GitHubLoader().fetch_repo_files("owner/repo")

    @patch("application.parser.remote.github_loader.requests.get")
    def test_fetch_file_content_non_json_raises(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("No JSON")
        mock_get.return_value = resp
        with pytest.raises(ValueError):
            GitHubLoader().fetch_file_content("owner/repo", "README.md")

    @patch("application.parser.remote.github_loader.requests.get")
    def test_fetch_file_content_unexpected_shape_missing_content_raises(self, mock_get):
        # encoding indicates base64 text, but 'content' key is missing
        resp = make_response({"encoding": "base64"})
        mock_get.return_value = resp
        with pytest.raises(KeyError):
            GitHubLoader().fetch_file_content("owner/repo", "README.md")

    @patch("application.parser.remote.github_loader.base64.b64decode")
    @patch("application.parser.remote.github_loader.requests.get")
    def test_large_binary_skip_does_not_decode(self, mock_get, mock_b64decode):
        # Ensure we don't attempt to decode large binary content for non-text files
        mock_b64decode.side_effect = AssertionError("b64decode should not be called for binary files")
        mock_get.return_value = make_response({"encoding": "base64", "content": "AAA"})
        result = GitHubLoader().fetch_file_content("owner/repo", "bigfile.bin")
        assert result == "Filename: bigfile.bin is a binary file and was skipped."
