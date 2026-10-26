"""The GitHub loader reads a repository from one tarball request, not one request per file."""

import datetime
import io
import os
import tarfile
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.parser.remote.github_loader import GitHubLoader, GitHubRateLimited, GitHubTokenRejected

PREFIX = "owner-repo-0123abc"


@pytest.fixture(autouse=True)
def _no_instance_token(monkeypatch):
    from docsgpt.core.settings import settings

    monkeypatch.setattr(settings, "GITHUB_ACCESS_TOKEN", None)


def _tarball(files, symlinks=()):
    """A gzipped tarball shaped like GitHub's: every path under one ``owner-repo-sha/`` folder."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        root = tarfile.TarInfo(PREFIX)
        root.type = tarfile.DIRTYPE
        tar.addfile(root)
        for path, data in files.items():
            info = tarfile.TarInfo(f"{PREFIX}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for path, target in symlinks:
            info = tarfile.TarInfo(f"{PREFIX}/{path}")
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)
    return buffer.getvalue()


def _archive_response(body, status=200, headers=None):
    response = MagicMock(status_code=status, headers=headers or {})
    response.raw = io.BytesIO(body)
    response.json.return_value = {}
    return response


def _loader(monkeypatch, **kwargs):
    loader = GitHubLoader(**kwargs)
    monkeypatch.setattr(loader, "get_default_branch", lambda repo: "main")
    # The per-file path must not run when the archive works.
    monkeypatch.setattr(loader, "fetch_file_content", MagicMock(side_effect=AssertionError("per-file fetch")))
    return loader


@pytest.mark.unit
class TestArchiveIngest:
    def test_one_request_reads_every_text_file(self, monkeypatch):
        body = _tarball({
            "README.md": b"# Repo",
            "src/app.py": b"print('hi')",
            "node_modules/lib/index.js": b"vendored",
            "logo.png": b"\x89PNG",
            "empty.md": b"   ",
            "latin1.txt": b"\xff\xfe\xfa not utf-8",
        }, symlinks=[("docs/link.md", "../README.md")])
        loader = _loader(monkeypatch)
        with patch("docsgpt.parser.remote.github_loader.requests.get",
                   return_value=_archive_response(body)) as get:
            docs = loader.load_data("https://github.com/owner/repo")

        assert get.call_count == 1
        assert get.call_args.args[0] == "https://api.github.com/repos/owner/repo/tarball/main"
        assert get.call_args.kwargs["stream"] is True
        assert [d.doc_id for d in docs] == ["README.md", "src/app.py"]
        assert docs[0].text == "# Repo"
        assert docs[1].extra_info == {
            "title": "src/app.py",
            "source": "https://github.com/owner/repo/blob/main/src/app.py",
        }

    def test_the_size_cap_applies_to_archive_members(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GITHUB_INGEST_MAX_FILE_BYTES", 10)
        body = _tarball({"small.md": b"tiny", "big.md": b"x" * 50})
        loader = _loader(monkeypatch)
        with patch("docsgpt.parser.remote.github_loader.requests.get", return_value=_archive_response(body)):
            docs = loader.load_data("owner/repo")
        assert [d.doc_id for d in docs] == ["small.md"]

    def test_the_connections_token_reads_the_archive(self, monkeypatch):
        body = _tarball({"README.md": b"private"})
        loader = _loader(monkeypatch)
        with patch("docsgpt.parser.remote.github_loader.requests.get",
                   return_value=_archive_response(body)) as get:
            loader.load_data({"repo_url": "owner/private", "access_token": "github_pat_x"})
        assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer github_pat_x"

    @pytest.mark.parametrize("status", [404, 500])
    def test_an_unavailable_archive_falls_back_to_per_file_fetches(self, monkeypatch, status):
        loader = GitHubLoader()
        monkeypatch.setattr(loader, "get_default_branch", lambda repo: "main")
        monkeypatch.setattr(loader, "fetch_repo_tree", lambda repo, branch: ([("README.md", 5)], False))
        monkeypatch.setattr(loader, "fetch_file_content", lambda repo, path: "from the API")
        with patch("docsgpt.parser.remote.github_loader.requests.get",
                   return_value=_archive_response(b"", status=status)):
            docs = loader.load_data("owner/repo")
        assert [d.text for d in docs] == ["from the API"]

    def test_an_archive_over_the_cap_falls_back(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GITHUB_INGEST_MAX_ARCHIVE_BYTES", 64)
        body = _tarball({"README.md": os.urandom(4096)})
        loader = GitHubLoader()
        monkeypatch.setattr(loader, "get_default_branch", lambda repo: "main")
        monkeypatch.setattr(loader, "fetch_repo_tree", lambda repo, branch: ([("README.md", 5)], False))
        monkeypatch.setattr(loader, "fetch_file_content", lambda repo, path: "from the API")
        with patch("docsgpt.parser.remote.github_loader.requests.get", return_value=_archive_response(body)):
            docs = loader.load_data("owner/repo")
        assert [d.text for d in docs] == ["from the API"]

    def test_a_rate_limited_archive_stops_the_ingest(self, monkeypatch):
        reset = int(datetime.datetime(2099, 1, 1, 12, 55, tzinfo=datetime.timezone.utc).timestamp())
        limited = _archive_response(b"", status=403, headers={
            "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset),
        })
        limited.json.return_value = {"message": "API rate limit exceeded for user ID 1."}
        loader = _loader(monkeypatch)
        with patch("docsgpt.parser.remote.github_loader.requests.get", return_value=limited):
            with pytest.raises(GitHubRateLimited) as caught:
                loader.load_data({"repo_url": "owner/repo", "access_token": "github_pat_x"})
        assert caught.value.reset_at.hour == 12 and caught.value.reset_at.minute == 55
        assert "12:55 UTC" in str(caught.value)
        assert "GITHUB_ACCESS_TOKEN" not in str(caught.value)

    def test_a_rejected_connection_token_is_reported(self, monkeypatch):
        loader = _loader(monkeypatch)
        with patch("docsgpt.parser.remote.github_loader.requests.get",
                   return_value=_archive_response(b"", status=401)):
            with pytest.raises(GitHubTokenRejected):
                loader.load_data({"repo_url": "owner/repo", "access_token": "revoked"})

    def test_a_short_secondary_limit_on_the_archive_is_waited_out(self, monkeypatch):
        body = _tarball({"README.md": b"# Repo"})
        limited = _archive_response(b"", status=429, headers={"Retry-After": "5"})
        loader = _loader(monkeypatch)
        with patch("docsgpt.parser.remote.github_loader.requests.get",
                   side_effect=[limited, _archive_response(body)]) as get, \
                patch("docsgpt.parser.remote.github_loader.time.sleep") as sleep:
            docs = loader.load_data("owner/repo")
        sleep.assert_called_once_with(5)
        assert get.call_count == 2
        assert [d.doc_id for d in docs] == ["README.md"]

    def test_a_dropped_download_falls_back_to_per_file_fetches(self, monkeypatch):
        import urllib3

        class Dropped(io.BytesIO):
            def read(self, size=-1):
                raise urllib3.exceptions.ProtocolError("Connection broken")

        response = _archive_response(b"")
        response.raw = Dropped()
        loader = GitHubLoader()
        monkeypatch.setattr(loader, "get_default_branch", lambda repo: "main")
        monkeypatch.setattr(loader, "fetch_repo_tree", lambda repo, branch: ([("README.md", 5)], False))
        monkeypatch.setattr(loader, "fetch_file_content", lambda repo, path: "from the API")
        with patch("docsgpt.parser.remote.github_loader.requests.get", return_value=response):
            docs = loader.load_data("owner/repo")
        assert [d.text for d in docs] == ["from the API"]


@pytest.mark.unit
class TestInstanceTokenVisibilityCheck:
    def test_a_short_secondary_limit_is_waited_out(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GITHUB_ACCESS_TOKEN", "instance-token")
        loader = GitHubLoader()
        public = MagicMock(status_code=200, headers={})
        public.json.return_value = {"private": False, "visibility": "public"}
        with patch("docsgpt.parser.remote.github_loader.requests.get",
                   side_effect=[_archive_response(b"", status=429, headers={"Retry-After": "3"}), public]), \
                patch("docsgpt.parser.remote.github_loader.time.sleep") as sleep:
            loader.ensure_instance_token_allowed("owner/repo")
        sleep.assert_called_once_with(3)
