import base64
import datetime
import logging
import math
import mimetypes
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
import urllib3

from docsgpt.core.settings import settings
from docsgpt.parser.remote.base import BaseRemote
from docsgpt.parser.schema.base import Document

logger = logging.getLogger(__name__)

# Directory names that hold vendored or generated output. Anything under one
# of these is build product, not source: it bloats the index, costs an API
# call each, and answers no question a user would ask of the repo.
SKIP_DIRECTORIES = {
    ".git", ".github/workflows/generated", ".idea", ".vscode",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".tox", ".venv", "venv",
    "node_modules", "bower_components", "vendor", "third_party", "external",
    "dist", "build", "out", "target", "bin", "obj",
    "site-packages", "coverage", "htmlcov", ".next", ".nuxt", ".svelte-kit",
}

# Exact filenames that are machine-generated and semantically empty.
SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "composer.lock", "gemfile.lock", "cargo.lock", "poetry.lock",
    "pipfile.lock", "go.sum", "mix.lock", "podfile.lock",
}

# Suffixes that mark minified or map output even under a source directory.
SKIP_SUFFIXES = (
    ".min.js", ".min.css", ".map", ".lock",
    ".pyc", ".pyo", ".class", ".jar", ".war", ".o", ".so", ".dylib", ".dll",
    ".exe", ".wasm", ".bin", ".pdb",
)


class GitHubTokenRejected(PermissionError):
    """GitHub answered 401 to a user's own token (revoked or expired)."""


class PrivateRepositoryError(PermissionError):
    """A repository the instance-wide token may not read for a user."""


# A rate limit that clears within this many seconds (GitHub's secondary
# limits) is waited out; a longer one (the hourly primary limit) fails the
# request with its reset time.
RATE_LIMIT_MAX_WAIT_SECONDS = 60


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class GitHubRateLimited(RuntimeError):
    """GitHub rate-limited the account the requests run as.

    The primary limit (5,000 requests an hour) belongs to the GitHub account,
    not to the token or to DocsGPT, so it also blocks the user's own use of
    the API until ``reset_at``.
    """

    def __init__(self, reset_at: datetime.datetime):
        self.reset_at = reset_at
        super().__init__(
            f"GitHub API rate limit exceeded for this account; it resets at {reset_at:%H:%M} UTC. "
            "Try again after that."
        )

    @property
    def retry_after_seconds(self) -> int:
        """Whole seconds until the limit resets, at least 1."""
        return max(1, math.ceil((self.reset_at - _utcnow()).total_seconds()))


def rate_limit_reset(response: Any, now: Optional[datetime.datetime] = None) -> Optional[datetime.datetime]:
    """When the rate limit that refused ``response`` clears, or None when it is no rate limit.

    GitHub refuses a rate-limited request with 403 or 429. A secondary limit
    sends ``Retry-After``; the primary limit sends ``X-RateLimit-Remaining: 0``
    and the reset as epoch seconds in ``X-RateLimit-Reset``. Without either
    header, a "rate limit" message waits a minute, as GitHub advises.

    Args:
        response: The refused ``requests`` response.
        now: The current time (for tests).

    Returns:
        The UTC time the limit clears, or None.
    """
    if response.status_code not in (403, 429):
        return None
    now = now or _utcnow()
    headers = getattr(response, "headers", None) or {}
    retry_after = str(headers.get("Retry-After") or "")
    if retry_after.isdigit():
        return now + datetime.timedelta(seconds=int(retry_after))
    if str(headers.get("X-RateLimit-Remaining")) == "0":
        reset = str(headers.get("X-RateLimit-Reset") or "")
        if reset.isdigit():
            return max(now, datetime.datetime.fromtimestamp(int(reset), tz=datetime.timezone.utc))
        return now + datetime.timedelta(seconds=60)
    if response.status_code == 429:
        return now + datetime.timedelta(seconds=60)
    try:
        message = str(response.json().get("message") or "")
    except Exception:  # noqa: BLE001 - not a JSON object: no rate-limit message either
        message = ""
    if "rate limit" in message.lower():
        return now + datetime.timedelta(seconds=60)
    return None


def _wait_out_short_limit(reset_at: datetime.datetime) -> bool:
    """Sleep until ``reset_at`` and return True when that is at most ``RATE_LIMIT_MAX_WAIT_SECONDS`` away."""
    wait = math.ceil((reset_at - _utcnow()).total_seconds())
    if wait > RATE_LIMIT_MAX_WAIT_SECONDS:
        return False
    wait = max(1, wait)
    logger.warning("GitHub rate limit hit, waiting %s seconds before retry...", wait)
    time.sleep(wait)
    return True


class _ArchiveTooLarge(Exception):
    """The repository tarball passed ``GITHUB_INGEST_MAX_ARCHIVE_BYTES``."""


class _CappedReader:
    """A read-only stream that stops after ``limit`` bytes."""

    def __init__(self, raw: Any, limit: int):
        self._raw = raw
        self._limit = limit
        self._read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._raw.read(size)
        self._read += len(chunk)
        if self._read > self._limit:
            raise _ArchiveTooLarge(f"archive is over {self._limit} bytes")
        return chunk


class GitHubLoader(BaseRemote):
    """Load a GitHub repository's text files as ``Document`` objects.

    Reads the whole repository from its tarball, one API request whatever
    its size, and keeps the text files that pass the skip-list and the size
    cap. When the tarball can't be used (too large, unavailable) it falls
    back to the git *tree* API plus one ``/contents/`` request per file,
    filtered before fetching and fetched in parallel.

    Every request counts against the GitHub account's hourly rate limit, so
    a rate limit stops the load (:class:`GitHubRateLimited`) rather than
    skipping files.
    """

    def __init__(self, access_token: Optional[str] = None):
        """Create a loader.

        Args:
            access_token: A user's own GitHub token (from their GitHub
                connection). Without one the instance-wide
                ``GITHUB_ACCESS_TOKEN`` is used, and only for public
                repositories.
        """
        self._user_token = access_token
        self._use_token(access_token or settings.GITHUB_ACCESS_TOKEN)

    def _use_token(self, token: Optional[str]) -> None:
        """Send ``token`` (or nothing) on every following request."""
        self.access_token = token
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    @staticmethod
    def _parse_inputs(inputs: Union[str, Dict[str, Any]]) -> Tuple[str, Optional[str]]:
        """``(repo_url, token)`` from a URL string or a connection's loader input.

        A source synced from a GitHub connection gets a dict: the repository
        (``repo_url`` or ``url``) plus the connection's ``access_token``.
        """
        if isinstance(inputs, dict):
            repo = inputs.get("repo_url") or inputs.get("url") or ""
            token = inputs.get("access_token") or inputs.get("token")
            return str(repo), (str(token) if token else None)
        return str(inputs or ""), None

    def ensure_instance_token_allowed(self, repo_name: str) -> None:
        """Refuse a repository the instance-wide token must not read.

        ``GITHUB_ACCESS_TOKEN`` belongs to the server, not to the user asking,
        and may see private repositories. Without a user's own token it is
        used only for public ones (for their higher rate limit); anything
        else needs the user's GitHub connection.

        Raises:
            PrivateRepositoryError: The repository is private, internal, or
                not visible to the token.
        """
        if self._user_token or not self.access_token:
            # A user's own token, or anonymous requests (which only ever see
            # public repositories).
            return
        url = f"https://api.github.com/repos/{repo_name}"
        response = self._get_waiting_out_short_limit(url, timeout=30)
        if response.status_code == 401:
            # A stale instance token: public repositories still read anonymously.
            logger.warning("GitHub rejected GITHUB_ACCESS_TOKEN (401); reading %s anonymously", repo_name)
            self._use_token(None)
            return
        if response.status_code == 200:
            try:
                data = response.json()
            except ValueError:
                data = {}
            if isinstance(data, dict) and data.get("private") is False and (
                data.get("visibility") or "public"
            ) == "public":
                return
        raise PrivateRepositoryError(
            f"{repo_name} is private or could not be found. Connect your GitHub account "
            "under Connectors to sync private repositories."
        )

    def is_text_file(self, file_path: str) -> bool:
        """Determine if a file is a text file based on extension."""
        # Common text file extensions
        text_extensions = {
            '.txt', '.md', '.markdown', '.rst', '.adoc', '.org',
            '.json', '.jsonc', '.xml', '.yaml', '.yml', '.toml',
            '.py', '.pyi', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx',
            '.vue', '.svelte', '.astro',
            '.java', '.c', '.cc', '.cpp', '.h', '.hpp', '.hxx',
            '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.kts',
            '.scala', '.sc', '.clj', '.cljs', '.edn', '.ex', '.exs', '.erl',
            '.hs', '.ml', '.mli', '.fs', '.fsx', '.dart', '.lua', '.jl',
            '.zig', '.nim', '.v', '.pl', '.pm', '.groovy', '.gradle',
            '.html', '.htm', '.css', '.scss', '.sass', '.less',
            '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat',
            '.sql', '.graphql', '.gql', '.proto', '.thrift',
            '.tf', '.tfvars', '.hcl', '.dockerfile', '.cmake', '.mk',
            '.ini', '.cfg', '.conf', '.config', '.properties',
            '.gitignore', '.dockerignore', '.editorconfig', '.gitattributes',
            '.csv', '.tsv',
        }

        # Get file extension
        file_lower = file_path.lower()
        for ext in text_extensions:
            if file_lower.endswith(ext):
                return True

        # Extension-less files that are conventionally text.
        basename = file_lower.rsplit("/", 1)[-1]
        if basename in {
            "dockerfile", "makefile", "rakefile", "gemfile", "procfile",
            "license", "licence", "notice", "authors", "codeowners", "readme",
        }:
            return True

        # Also check MIME type
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type and (mime_type.startswith("text") or mime_type in ["application/json", "application/xml"]):
            return True

        return False

    def should_skip_path(self, file_path: str) -> bool:
        """Return ``True`` for vendored, generated or binary-by-name paths.

        Applied to the tree listing before any content is fetched, so a
        skipped file costs nothing. Complements :meth:`is_text_file`, which
        only knows about extensions.

        Args:
            file_path: Repo-relative path, e.g. ``"web/dist/app.min.js"``.

        Returns:
            ``True`` when the path should not be ingested.
        """
        lowered = file_path.lower()
        parts = lowered.split("/")
        if any(part in SKIP_DIRECTORIES for part in parts[:-1]):
            return True
        if parts[-1] in SKIP_FILENAMES:
            return True
        if lowered.endswith(SKIP_SUFFIXES):
            return True
        # Dot-directories (.git, .cache, ...) never carry documentation.
        if any(part.startswith(".") and part not in {".github"} for part in parts[:-1]):
            return True
        return False

    def _max_file_bytes(self) -> int:
        """Resolve the per-blob size cap; ``0`` disables it."""
        raw = settings.GITHUB_INGEST_MAX_FILE_BYTES
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            return 1048576
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 1048576

    def _max_workers(self) -> int:
        """Resolve the parallel-fetch width, clamped to a sane range."""
        raw = settings.GITHUB_INGEST_MAX_WORKERS
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            return 8
        try:
            return max(1, min(32, int(raw)))
        except (TypeError, ValueError):
            return 8

    def _max_archive_bytes(self) -> int:
        """Resolve the tarball size cap; ``0`` turns the tarball off."""
        raw = settings.GITHUB_INGEST_MAX_ARCHIVE_BYTES
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            return 536_870_912
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 536_870_912

    @staticmethod
    def normalize_repo(repo_url: str) -> str:
        """Reduce a user-pasted repo URL to ``owner/name``.

        Strips the scheme/host, a trailing ``.git`` and any trailing slash —
        the three shapes that previously 404'd the contents API.

        Args:
            repo_url: Anything from ``owner/name`` to
                ``https://github.com/owner/name.git/``.

        Returns:
            The ``owner/name`` segment.
        """
        repo = (repo_url or "").strip()
        if not repo:
            return ""

        if repo.startswith("git@"):
            # git@github.com:owner/name.git
            host, _, path = repo[len("git@"):].partition(":")
            if host.lower() != "github.com":
                return ""
            repo = path
        elif "://" in repo:
            remainder = repo.split("://", 1)[1]
            host, _, path = remainder.partition("/")
            # Anything not hosted on github.com is not a repo. Previously such
            # a URL was pasted straight into the contents path and 404-looped.
            if host.lower() not in {"github.com", "www.github.com"}:
                return ""
            repo = path
        elif repo.lower().startswith(("github.com/", "www.github.com/")):
            repo = repo.split("/", 1)[1]

        repo = repo.strip("/")
        if repo.lower().endswith(".git"):
            repo = repo[: -len(".git")]
        parts = [p for p in repo.split("/") if p]
        if len(parts) < 2:
            return ""
        owner, name = parts[0], parts[1]
        if name.lower().endswith(".git"):
            name = name[: -len(".git")]
        # A bare host slipping through ("suat-handbook.netlify.app") has no
        # owner segment, so require both halves to look like path segments.
        if not owner or not name or ":" in owner or ":" in name:
            return ""
        return f"{owner}/{name}"

    def get_default_branch(self, repo_name: str) -> str:
        """Return the repo's default branch, falling back to ``main``.

        The blob URL used for citations was hard-coded to ``main``, which
        produced dead source links for every ``master``-default repo.
        """
        try:
            response = self._make_request(f"https://api.github.com/repos/{repo_name}")
            branch = response.json().get("default_branch")
            if branch:
                return str(branch)
        except (GitHubRateLimited, GitHubTokenRejected):
            raise
        except Exception as e:
            logger.warning(
                "Could not resolve default branch for %s (%s); assuming 'main'",
                repo_name, e,
            )
        return "main"

    def fetch_repo_tree(
        self, repo_name: str, branch: str
    ) -> Tuple[List[Tuple[str, int]], bool]:
        """List every blob in the repo with one recursive tree request.

        Replaces the per-directory ``/contents/`` walk, which cost one API
        call per directory (720 for a mid-size repo) before a single file
        was read.

        Args:
            repo_name: ``owner/name``.
            branch: Branch or ref to enumerate.

        Returns:
            ``(entries, truncated)`` where ``entries`` is a list of
            ``(path, size_bytes)`` and ``truncated`` flags a repo too large
            for the tree endpoint (caller should fall back to the walk).
        """
        url = (
            f"https://api.github.com/repos/{repo_name}/git/trees/"
            f"{branch}?recursive=1"
        )
        response = self._make_request(url)
        payload = response.json()
        if isinstance(payload, dict) and "tree" not in payload and "message" in payload:
            raise Exception(f"GitHub API error: {payload.get('message')}")
        entries = [
            (item.get("path", ""), int(item.get("size") or 0))
            for item in payload.get("tree", [])
            if item.get("type") == "blob"
        ]
        return entries, bool(payload.get("truncated"))

    def select_files(self, entries: List[Tuple[str, int]]) -> List[str]:
        """Filter tree entries down to the paths worth fetching.

        Args:
            entries: ``(path, size_bytes)`` pairs from :meth:`fetch_repo_tree`.

        Returns:
            Repo-relative paths that pass the skip-list, the text-extension
            check and the size cap, in tree order.
        """
        max_bytes = self._max_file_bytes()
        selected: List[str] = []
        skipped_big = 0
        for path, size in entries:
            if not path or self.should_skip_path(path) or not self.is_text_file(path):
                continue
            if max_bytes and size > max_bytes:
                skipped_big += 1
                continue
            selected.append(path)
        if skipped_big:
            logger.info(
                "Skipped %d file(s) over the %d-byte cap", skipped_big, max_bytes
            )
        return selected

    def fetch_file_content(self, repo_url: str, file_path: str) -> Optional[str]:
        """Fetch file content. Returns None if file should be skipped (binary files or empty files)."""
        url = f"https://api.github.com/repos/{repo_url}/contents/{file_path}"
        response = self._make_request(url)

        content = response.json()

        if content.get("encoding") == "base64":
            if self.is_text_file(file_path):  # Handle only text files
                try:
                    decoded_content = base64.b64decode(content["content"]).decode("utf-8").strip()
                    # Skip empty files
                    if not decoded_content:
                        return None
                    return decoded_content
                except Exception:
                    # If decoding fails, it's probably a binary file
                    return None
            else:
                # Skip binary files by returning None
                return None
        else:
            file_content = content['content'].strip()
            # Skip empty files
            if not file_content:
                return None
            return file_content

    def _make_request(self, url: str, max_retries: int = 3) -> requests.Response:
        """GET ``url``, waiting out a short rate limit.

        Raises:
            GitHubRateLimited: A rate limit that lasts longer than
                ``RATE_LIMIT_MAX_WAIT_SECONDS``, or one still in place after
                the retries.
            GitHubTokenRejected: GitHub refused the connection's token.
        """
        for attempt in range(max_retries):
            response = requests.get(url, headers=self.headers, timeout=100)

            if response.status_code == 200:
                return response
            reset_at = rate_limit_reset(response)
            if reset_at is not None:
                if attempt < max_retries - 1 and _wait_out_short_limit(reset_at):
                    continue
                raise GitHubRateLimited(reset_at)
            if response.status_code == 403:
                raise Exception(self._forbidden_message(response))
            if response.status_code == 401 and self._user_token:
                # The user's own token: a retry without it could only read
                # public repositories, which is not what they asked for.
                raise GitHubTokenRejected("GitHub rejected the connection's token. Reconnect GitHub to continue.")
            if response.status_code == 401 and self.access_token:
                # An expired or revoked PAT makes even public repos 401, which
                # is strictly worse than not sending one. Retry unauthenticated
                # so a stale credential degrades instead of failing the ingest.
                logger.warning(
                    "GitHub rejected the configured token (401); "
                    "retrying %s unauthenticated", url,
                )
                anon = {"Accept": "application/vnd.github.v3+json"}
                anon_response = requests.get(url, headers=anon, timeout=100)
                if anon_response.status_code == 200:
                    return anon_response
                anon_response.raise_for_status()
                return anon_response
            response.raise_for_status()

        return response

    def _get_waiting_out_short_limit(self, url: str, timeout: int, stream: bool = False) -> requests.Response:
        """GET ``url`` once, or twice when a rate limit clears within ``RATE_LIMIT_MAX_WAIT_SECONDS``.

        Raises:
            GitHubRateLimited: The limit lasts longer, or is still in place
                after the wait.
        """
        response = requests.get(url, headers=self.headers, timeout=timeout, stream=stream)
        reset_at = rate_limit_reset(response)
        if reset_at is not None and _wait_out_short_limit(reset_at):
            response.close()
            response = requests.get(url, headers=self.headers, timeout=timeout, stream=stream)
            reset_at = rate_limit_reset(response)
        if reset_at is not None:
            response.close()
            raise GitHubRateLimited(reset_at)
        return response

    def _forbidden_message(self, response: requests.Response) -> str:
        """The error for a 403 that is not a rate limit."""
        try:
            message = str(response.json().get("message") or "")
        except Exception:  # noqa: BLE001 - not JSON: report the status instead
            message = ""
        text = f"GitHub API error: {message or 'access forbidden (403)'}."
        if not self._user_token:
            # Only the server's token is configured here; a connection's
            # token is the user's to fix, not an environment variable.
            text += " This may require authentication - set GITHUB_ACCESS_TOKEN environment variable."
        return text

    def fetch_repo_files(self, repo_url: str, path: str = "") -> List[str]:
        """Walk ``/contents/`` recursively (fallback for truncated trees)."""
        url = f"https://api.github.com/repos/{repo_url}/contents/{path}"
        response = self._make_request(url)

        contents = response.json()

        # Handle error responses from GitHub API
        if isinstance(contents, dict) and "message" in contents:
            raise Exception(f"GitHub API error: {contents.get('message')}")

        # Ensure contents is a list
        if not isinstance(contents, list):
            raise TypeError(f"Expected list from GitHub API, got {type(contents).__name__}: {contents}")

        files = []
        for item in contents:
            if item["type"] == "file":
                files.append(item["path"])
            elif item["type"] == "dir":
                files.extend(self.fetch_repo_files(repo_url, item["path"]))
        return files

    def _list_candidate_files(self, repo_name: str, branch: str) -> List[str]:
        """Enumerate ingestable paths, preferring the single tree request."""
        try:
            entries, truncated = self.fetch_repo_tree(repo_name, branch)
            if not truncated:
                return self.select_files(entries)
            logger.warning(
                "Tree for %s is truncated; falling back to the directory walk",
                repo_name,
            )
        except (GitHubRateLimited, GitHubTokenRejected):
            raise
        except Exception as e:
            logger.warning(
                "Tree listing failed for %s (%s); falling back to the "
                "directory walk", repo_name, e,
            )
        paths = self.fetch_repo_files(repo_name)
        return self.select_files([(p, 0) for p in paths])

    def load_data(self, inputs: Union[str, Dict[str, Any]]) -> List[Document]:
        """Load every ingestable text file of a repository as a Document.

        Args:
            inputs: The repository URL, or ``{"repo_url", "access_token"}``
                for a source synced from a GitHub connection.

        Raises:
            ValueError: ``inputs`` names no github.com repository.
            PrivateRepositoryError: Only the instance-wide token is available
                and the repository is not public.
            GitHubTokenRejected: GitHub refused the connection's token.
        """
        repo_url, token = self._parse_inputs(inputs)
        if token:
            self._user_token = token
            self._use_token(token)
        repo_name = self.normalize_repo(repo_url)
        if not repo_name or "/" not in repo_name:
            raise ValueError(
                f"Not a valid GitHub repository: {repo_url!r}. "
                "Expected a github.com URL like https://github.com/owner/name."
            )
        self.ensure_instance_token_allowed(repo_name)
        branch = self.get_default_branch(repo_name)
        documents = self._read_archive(repo_name, branch)
        if documents is not None:
            logger.info("Read %d file(s) from the %s@%s archive", len(documents), repo_name, branch)
            return documents

        files = self._list_candidate_files(repo_name, branch)
        logger.info(
            "Fetching %d file(s) from %s@%s", len(files), repo_name, branch
        )

        # Fetch in parallel: this phase is pure network latency, and it was
        # previously one blocking round-trip per file.
        contents: Dict[str, Optional[str]] = {}
        # A rate limit or a refused token fails every request after it, so
        # the first one stops the load instead of skipping the rest one by one.
        stopped: List[Exception] = []

        def _fetch(file_path: str) -> Tuple[str, Optional[str]]:
            if stopped:
                return file_path, None
            try:
                return file_path, self.fetch_file_content(repo_name, file_path)
            except (GitHubRateLimited, GitHubTokenRejected) as e:
                stopped.append(e)
                return file_path, None
            except Exception as e:
                # One unreadable file must not sink the whole repo ingest.
                logger.warning("Skipping %s: %s", file_path, e)
                return file_path, None

        max_workers = min(self._max_workers(), len(files)) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for file_path, content in pool.map(_fetch, files):
                contents[file_path] = content
        if stopped:
            raise stopped[0]

        documents = []
        for file_path in files:
            content = contents.get(file_path)
            # Skip binary files (content is None)
            if not content:
                continue
            documents.append(self._document(repo_name, branch, file_path, content))
        return documents

    @staticmethod
    def _document(repo_name: str, branch: str, file_path: str, text: str) -> Document:
        return Document(
            text=text,
            doc_id=file_path,
            extra_info={
                "title": file_path,
                "source": f"https://github.com/{repo_name}/blob/{branch}/{file_path}",
            },
        )

    def _read_archive(self, repo_name: str, branch: str) -> Optional[List[Document]]:
        """Read the repository's text files from its tarball, in one API request.

        The per-file path costs one request per file, and a few thousand
        files use up the account's hourly rate limit. The tarball is
        streamed and read in memory: nothing is written to disk, and only
        regular files are read (no links).

        Args:
            repo_name: ``owner/name``.
            branch: The ref to read.

        Returns:
            The documents in path order, or None when the tarball can't be
            used (turned off, unavailable, over ``GITHUB_INGEST_MAX_ARCHIVE_BYTES``
            or unreadable), so the caller falls back to per-file requests.

        Raises:
            GitHubRateLimited: GitHub rate-limited the account.
            GitHubTokenRejected: GitHub refused the connection's token.
        """
        max_archive = self._max_archive_bytes()
        if not max_archive:
            return None
        url = f"https://api.github.com/repos/{repo_name}/tarball/{branch}"
        try:
            response = self._get_waiting_out_short_limit(url, timeout=100, stream=True)
        except requests.RequestException as e:
            logger.warning("Could not download the %s archive (%s); fetching files one by one", repo_name, e)
            return None
        try:
            if response.status_code != 200:
                if response.status_code == 401 and self._user_token:
                    raise GitHubTokenRejected("GitHub rejected the connection's token. Reconnect GitHub to continue.")
                logger.warning(
                    "The %s archive is unavailable (%s); fetching files one by one",
                    repo_name, response.status_code,
                )
                return None
            try:
                texts = self._archive_texts(response.raw, max_archive)
            # ``raw.read`` raises urllib3's own errors (a reset connection, a
            # read timeout); ``requests`` wraps those only in ``iter_content``.
            except (_ArchiveTooLarge, tarfile.TarError, OSError, EOFError, urllib3.exceptions.HTTPError) as e:
                logger.warning("Could not read the %s archive (%s); fetching files one by one", repo_name, e)
                return None
        finally:
            response.close()
        return [self._document(repo_name, branch, path, texts[path]) for path in sorted(texts)]

    def _archive_texts(self, raw: Any, max_archive: int) -> Dict[str, str]:
        """``{path: text}`` of the ingestable files in a gzipped tarball stream.

        GitHub puts every path under one ``owner-repo-sha/`` folder; it is
        dropped. Files that fail the skip-list, the text check or the size
        cap, are empty, or aren't UTF-8 are left out.
        """
        if hasattr(raw, "decode_content"):
            raw.decode_content = True
        max_file = self._max_file_bytes()
        texts: Dict[str, str] = {}
        skipped_big = 0
        with tarfile.open(fileobj=_CappedReader(raw, max_archive), mode="r|gz") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                _, _, path = member.name.partition("/")
                if not path or self.should_skip_path(path) or not self.is_text_file(path):
                    continue
                if max_file and member.size > max_file:
                    skipped_big += 1
                    continue
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                try:
                    text = handle.read().decode("utf-8").strip()
                except UnicodeDecodeError:
                    continue
                if text:
                    texts[path] = text
        if skipped_big:
            logger.info("Skipped %d file(s) over the %d-byte cap", skipped_big, max_file)
        return texts
