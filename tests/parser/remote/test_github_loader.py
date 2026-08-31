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

        assert result == content_str
        mock_get.assert_called_once_with(
            "https://api.github.com/repos/owner/repo/contents/README.md",
            headers=loader.headers,
            timeout=100,
        )

    @patch("application.parser.remote.github_loader.requests.get")
    def test_binary_file_skipped(self, mock_get):
        loader = GitHubLoader()
        mock_get.return_value = make_response({"encoding": "base64", "content": "AAAA"})

        result = loader.fetch_file_content("owner/repo", "image.png")

        assert result is None

    @patch("application.parser.remote.github_loader.requests.get")
    def test_non_base64_plain_content(self, mock_get):
        loader = GitHubLoader()
        mock_get.return_value = make_response({"encoding": "", "content": "Plain text"})

        result = loader.fetch_file_content("owner/repo", "file.txt")

        assert result == "Plain text"

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

        def side_effect(url, headers=None, timeout=None):
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
        monkeypatch.setattr(loader, "get_default_branch", lambda repo: "main")
        monkeypatch.setattr(
            loader, "fetch_repo_tree",
            lambda repo, branch: ([("README.md", 10), ("src/main.py", 10)], False),
        )

        def fake_fetch_content(repo, file_path):
            return f"content for {file_path}"

        monkeypatch.setattr(loader, "fetch_file_content", fake_fetch_content)

        docs = loader.load_data("https://github.com/owner/repo")

        assert len(docs) == 2
        assert docs[0].text == "content for README.md"
        assert docs[0].extra_info == {
            "title": "README.md",
            "source": "https://github.com/owner/repo/blob/main/README.md",
        }
        assert docs[1].text == "content for src/main.py"
        assert docs[1].extra_info == {
            "title": "src/main.py",
            "source": "https://github.com/owner/repo/blob/main/src/main.py",
        }




class TestGitHubLoaderIsTextFile:
    def test_known_extension(self):
        loader = GitHubLoader()
        assert loader.is_text_file("app.py") is True
        assert loader.is_text_file("data.json") is True

    def test_unknown_extension_with_text_mime(self):
        loader = GitHubLoader()
        assert loader.is_text_file("file.xml") is True

    def test_binary_file(self):
        loader = GitHubLoader()
        assert loader.is_text_file("image.png") is False

    @patch("application.parser.remote.github_loader.mimetypes.guess_type")
    def test_mime_fallback_text(self, mock_mime):
        mock_mime.return_value = ("text/plain", None)
        loader = GitHubLoader()
        assert loader.is_text_file("unknownfile.xyz") is True


class TestGitHubLoaderMakeRequest:
    @patch("application.parser.remote.github_loader.requests.get")
    def test_success(self, mock_get):
        loader = GitHubLoader()
        mock_get.return_value = make_response({"ok": True}, 200)
        resp = loader._make_request("http://example.com")
        assert resp.status_code == 200

    @patch("application.parser.remote.github_loader.time.sleep")
    @patch("application.parser.remote.github_loader.requests.get")
    def test_rate_limit_retry(self, mock_get, mock_sleep):
        loader = GitHubLoader()
        rate_resp = MagicMock()
        rate_resp.status_code = 403
        rate_resp.json.return_value = {"message": "API rate limit exceeded"}
        rate_resp.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "9999999",
        }
        ok_resp = make_response({"ok": True}, 200)
        mock_get.side_effect = [rate_resp, ok_resp]

        resp = loader._make_request("http://example.com", max_retries=2)
        assert resp.status_code == 200
        mock_sleep.assert_called_once()

    @patch("application.parser.remote.github_loader.requests.get")
    def test_rate_limit_exhausted(self, mock_get):
        loader = GitHubLoader()
        rate_resp = MagicMock()
        rate_resp.status_code = 403
        rate_resp.json.return_value = {"message": "API rate limit exceeded"}
        rate_resp.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "9999",
        }
        mock_get.return_value = rate_resp

        with pytest.raises(Exception, match="rate limit exceeded"):
            loader._make_request("http://example.com", max_retries=1)

    @patch("application.parser.remote.github_loader.requests.get")
    def test_403_non_rate_limit(self, mock_get):
        loader = GitHubLoader()
        resp = MagicMock()
        resp.status_code = 403
        resp.json.return_value = {"message": "Forbidden - need auth"}
        resp.headers = {"X-RateLimit-Remaining": "50", "X-RateLimit-Reset": "9999"}
        mock_get.return_value = resp

        with pytest.raises(Exception, match="GitHub API error"):
            loader._make_request("http://example.com", max_retries=1)

    @patch("application.parser.remote.github_loader.requests.get")
    def test_other_error_raises(self, mock_get):
        loader = GitHubLoader()
        resp = make_response(
            status_code=500,
            raise_error=requests.HTTPError("Server Error"),
        )
        mock_get.return_value = resp

        with pytest.raises(requests.HTTPError):
            loader._make_request("http://example.com", max_retries=1)


class TestGitHubLoaderFetchRepoFilesErrors:
    @patch("application.parser.remote.github_loader.requests.get")
    def test_api_error_message_in_dict(self, mock_get):
        loader = GitHubLoader()
        mock_get.return_value = make_response(
            {"message": "Not Found"}, 200
        )

        with pytest.raises(Exception, match="GitHub API error"):
            loader.fetch_repo_files("owner/repo")

    @patch("application.parser.remote.github_loader.requests.get")
    def test_non_list_response(self, mock_get):
        loader = GitHubLoader()
        mock_get.return_value = make_response("not a list", 200)

        with pytest.raises(TypeError, match="Expected list"):
            loader.fetch_repo_files("owner/repo")


class TestGitHubLoaderFetchFileContentEdgeCases:
    @patch("application.parser.remote.github_loader.requests.get")
    def test_empty_base64_text_returns_none(self, mock_get):
        loader = GitHubLoader()
        b64 = base64.b64encode(b"").decode("utf-8")
        mock_get.return_value = make_response(
            {"encoding": "base64", "content": b64}
        )
        result = loader.fetch_file_content("owner/repo", "empty.py")
        assert result is None

    @patch("application.parser.remote.github_loader.requests.get")
    def test_empty_non_base64_returns_none(self, mock_get):
        loader = GitHubLoader()
        mock_get.return_value = make_response(
            {"encoding": "none", "content": "   "}
        )
        result = loader.fetch_file_content("owner/repo", "empty.txt")
        assert result is None

    @patch("application.parser.remote.github_loader.requests.get")
    def test_decode_failure_returns_none(self, mock_get):
        loader = GitHubLoader()
        mock_get.return_value = make_response(
            {"encoding": "base64", "content": "invalid!!base64"}
        )
        result = loader.fetch_file_content("owner/repo", "broken.py")
        assert result is None


class TestGitHubLoaderLoadDataSkipsNone:
    def test_skips_binary_files(self, monkeypatch):
        loader = GitHubLoader()
        monkeypatch.setattr(loader, "get_default_branch", lambda repo: "main")
        monkeypatch.setattr(
            loader, "fetch_repo_tree",
            lambda repo, branch: ([("a.py", 10), ("b.png", 10)], False),
        )

        def fake_content(repo, fp):
            return "code" if fp == "a.py" else None

        monkeypatch.setattr(loader, "fetch_file_content", fake_content)
        docs = loader.load_data("https://github.com/o/r")
        assert len(docs) == 1
        assert docs[0].doc_id == "a.py"


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
    def test_fetch_file_content_unexpected_shape_missing_content_returns_none(self, mock_get):
        # encoding indicates base64 text, but 'content' key is missing
        # With the new code, the exception is caught and returns None (treated as binary/skipped)
        resp = make_response({"encoding": "base64"})
        mock_get.return_value = resp
        result = GitHubLoader().fetch_file_content("owner/repo", "file.txt")
        assert result is None

    @patch("application.parser.remote.github_loader.base64.b64decode")
    @patch("application.parser.remote.github_loader.requests.get")
    def test_large_binary_skip_does_not_decode(self, mock_get, mock_b64decode):
        # Ensure we don't attempt to decode large binary content for non-text files
        mock_b64decode.side_effect = AssertionError("b64decode should not be called for binary files")
        mock_get.return_value = make_response({"encoding": "base64", "content": "AAA"})
        result = GitHubLoader().fetch_file_content("owner/repo", "bigfile.bin")
        assert result is None


class TestGitHubLoaderNormalizeRepo:
    @pytest.mark.parametrize("raw,expected", [
        ("https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo.git", "owner/repo"),
        ("https://github.com/owner/repo/", "owner/repo"),
        ("http://github.com/owner/repo.git/", "owner/repo"),
        ("owner/repo", "owner/repo"),
        ("https://github.com/owner/repo/tree/main/sub", "owner/repo"),
    ])
    def test_normalizes(self, raw, expected):
        assert GitHubLoader.normalize_repo(raw) == expected

    def test_rejects_non_repo_url(self):
        """Regression: a pasted website URL used to be concatenated straight
        into the contents path and 404-loop."""
        loader = GitHubLoader()
        with pytest.raises(ValueError, match="Not a valid GitHub repository"):
            loader.load_data("https://suat-handbook.netlify.app/")


class TestGitHubLoaderSkipPaths:
    @pytest.mark.parametrize("path", [
        "node_modules/left-pad/index.js",
        "web/dist/app.js",
        "target/scala-2.13/Foo.class",
        "vendor/github.com/pkg/errors/errors.go",
        "package-lock.json",
        "assets/app.min.js",
        "build/output.map",
        ".venv/lib/thing.py",
        "src/__pycache__/mod.pyc",
    ])
    def test_skipped(self, path):
        assert GitHubLoader().should_skip_path(path) is True

    @pytest.mark.parametrize("path", [
        "README.md",
        "src/main/scala/zio/ZIO.scala",
        ".github/workflows/ci.yml",
        "docs/guide/setup.md",
        "Cargo.toml",
    ])
    def test_kept(self, path):
        assert GitHubLoader().should_skip_path(path) is False


class TestGitHubLoaderIsTextFileAdditions:
    @pytest.mark.parametrize("path", [
        "Cargo.toml", "main.go", "app.vue", "schema.proto",
        "infra.tf", "Dockerfile", "Makefile", "build.gradle",
    ])
    def test_newly_recognised_text(self, path):
        assert GitHubLoader().is_text_file(path) is True

    def test_env_files_are_not_ingested(self):
        """.env was in the allowlist, so a committed secrets file would be
        embedded verbatim into the vector index."""
        loader = GitHubLoader()
        assert loader.is_text_file("config/.env") is False
        assert loader.is_text_file(".env") is False


class TestGitHubLoaderSelectFiles:
    def test_applies_size_cap(self, monkeypatch):
        loader = GitHubLoader()
        monkeypatch.setattr(
            "application.parser.remote.github_loader.settings.GITHUB_INGEST_MAX_FILE_BYTES",
            100, raising=False,
        )
        entries = [("small.py", 50), ("huge.py", 5000), ("ok.md", 99)]
        assert loader.select_files(entries) == ["small.py", "ok.md"]

    def test_zero_cap_disables_limit(self, monkeypatch):
        loader = GitHubLoader()
        monkeypatch.setattr(
            "application.parser.remote.github_loader.settings.GITHUB_INGEST_MAX_FILE_BYTES",
            0, raising=False,
        )
        assert loader.select_files([("huge.py", 10**9)]) == ["huge.py"]

    def test_filters_binaries_and_vendored(self):
        entries = [
            ("README.md", 10), ("logo.png", 10),
            ("node_modules/x/i.js", 10), ("src/a.py", 10),
        ]
        assert GitHubLoader().select_files(entries) == ["README.md", "src/a.py"]


class TestGitHubLoaderTree:
    @patch("application.parser.remote.github_loader.requests.get")
    def test_single_request_lists_all_blobs(self, mock_get):
        mock_get.return_value = make_response({
            "tree": [
                {"path": "README.md", "type": "blob", "size": 12},
                {"path": "src", "type": "tree"},
                {"path": "src/a.py", "type": "blob", "size": 34},
            ],
            "truncated": False,
        })
        entries, truncated = GitHubLoader().fetch_repo_tree("owner/repo", "main")

        assert entries == [("README.md", 12), ("src/a.py", 34)]
        assert truncated is False
        # One call for the whole repo, versus one per directory before.
        assert mock_get.call_count == 1

    @patch("application.parser.remote.github_loader.requests.get")
    def test_truncated_tree_falls_back_to_walk(self, mock_get, monkeypatch):
        loader = GitHubLoader()
        mock_get.return_value = make_response({"tree": [], "truncated": True})
        monkeypatch.setattr(
            loader, "fetch_repo_files", lambda repo, path="": ["README.md"]
        )
        assert loader._list_candidate_files("owner/repo", "main") == ["README.md"]


class TestGitHubLoaderDefaultBranch:
    @patch("application.parser.remote.github_loader.requests.get")
    def test_uses_repo_default_branch(self, mock_get):
        mock_get.return_value = make_response({"default_branch": "master"})
        assert GitHubLoader().get_default_branch("owner/repo") == "master"

    @patch("application.parser.remote.github_loader.requests.get")
    def test_falls_back_to_main(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")
        assert GitHubLoader().get_default_branch("owner/repo") == "main"

    def test_citation_url_uses_real_branch(self, monkeypatch):
        """Regression: blob/main was hard-coded, so every master-default
        repo produced dead source links."""
        loader = GitHubLoader()
        monkeypatch.setattr(loader, "get_default_branch", lambda repo: "master")
        monkeypatch.setattr(
            loader, "fetch_repo_tree", lambda repo, branch: ([("a.py", 5)], False)
        )
        monkeypatch.setattr(loader, "fetch_file_content", lambda r, p: "code")

        docs = loader.load_data("https://github.com/owner/repo")
        assert docs[0].extra_info["source"] == (
            "https://github.com/owner/repo/blob/master/a.py"
        )


class TestGitHubLoaderParallelFetch:
    def test_fetches_in_parallel_and_preserves_order(self, monkeypatch):
        loader = GitHubLoader()
        monkeypatch.setattr(loader, "get_default_branch", lambda repo: "main")
        paths = [f"f{i}.py" for i in range(10)]
        monkeypatch.setattr(
            loader, "fetch_repo_tree",
            lambda repo, branch: ([(p, 5) for p in paths], False),
        )
        monkeypatch.setattr(
            loader, "fetch_file_content", lambda r, p: f"body {p}"
        )

        docs = loader.load_data("https://github.com/owner/repo")
        assert [d.doc_id for d in docs] == paths

    def test_one_bad_file_does_not_sink_the_ingest(self, monkeypatch):
        loader = GitHubLoader()
        monkeypatch.setattr(loader, "get_default_branch", lambda repo: "main")
        monkeypatch.setattr(
            loader, "fetch_repo_tree",
            lambda repo, branch: ([("good.py", 5), ("bad.py", 5)], False),
        )

        def flaky(repo, path):
            if path == "bad.py":
                raise requests.HTTPError("500")
            return "code"
        monkeypatch.setattr(loader, "fetch_file_content", flaky)

        docs = loader.load_data("https://github.com/owner/repo")
        assert [d.doc_id for d in docs] == ["good.py"]


class TestGitHubLoaderStaleTokenFallback:
    @patch("application.parser.remote.github_loader.requests.get")
    def test_401_retries_unauthenticated(self, mock_get):
        """An expired PAT 401s even public repos; fall back to anonymous
        rather than failing the ingest outright."""
        loader = GitHubLoader()
        loader.access_token = "stale-token"
        unauthorized = MagicMock(status_code=401)
        ok = make_response({"ok": True}, 200)
        mock_get.side_effect = [unauthorized, ok]

        resp = loader._make_request("https://api.github.com/repos/o/r")

        assert resp.status_code == 200
        assert mock_get.call_count == 2
        # Second attempt carried no Authorization header.
        assert "Authorization" not in mock_get.call_args.kwargs["headers"]
