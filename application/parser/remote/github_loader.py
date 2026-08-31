import base64
import logging
import mimetypes
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import requests

from application.core.settings import settings
from application.parser.remote.base import BaseRemote
from application.parser.schema.base import Document

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


class GitHubLoader(BaseRemote):
    """Load a GitHub repository's text files as ``Document`` objects.

    Uses the git *tree* API to enumerate the repository in a single request
    rather than walking ``/contents/`` directory by directory, filters out
    binaries, vendored output and oversized blobs *before* fetching them, and
    downloads the survivors in parallel.
    """

    def __init__(self):
        self.access_token = settings.GITHUB_ACCESS_TOKEN
        self.headers = {
            "Authorization": f"token {self.access_token}",
            "Accept": "application/vnd.github.v3+json"
        } if self.access_token else {
            "Accept": "application/vnd.github.v3+json"
        }
        return

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
        raw = getattr(settings, "GITHUB_INGEST_MAX_FILE_BYTES", None)
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            return 1048576
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 1048576

    def _max_workers(self) -> int:
        """Resolve the parallel-fetch width, clamped to a sane range."""
        raw = getattr(settings, "GITHUB_INGEST_MAX_WORKERS", None)
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            return 8
        try:
            return max(1, min(32, int(raw)))
        except (TypeError, ValueError):
            return 8

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
        """Make a request with retry logic for rate limiting"""
        for attempt in range(max_retries):
            response = requests.get(url, headers=self.headers, timeout=100)

            if response.status_code == 200:
                return response
            elif response.status_code == 403:
                # Check if it's a rate limit issue
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", "")

                    # Check rate limit headers
                    remaining = response.headers.get("X-RateLimit-Remaining", "unknown")
                    reset_time = response.headers.get("X-RateLimit-Reset", "unknown")

                    logger.warning("GitHub API 403 Error: %s", error_msg)
                    logger.warning(
                        "Rate limit remaining: %s, Reset time: %s", remaining, reset_time
                    )

                    if "rate limit" in error_msg.lower():
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt  # Exponential backoff
                            logger.warning(
                                "Rate limit hit, waiting %s seconds before retry...",
                                wait_time,
                            )
                            time.sleep(wait_time)
                            continue

                    # Provide helpful error message
                    if remaining == "0":
                        raise Exception(f"GitHub API rate limit exceeded. Please set GITHUB_ACCESS_TOKEN environment variable. Reset time: {reset_time}")
                    else:
                        raise Exception(f"GitHub API error: {error_msg}. This may require authentication - set GITHUB_ACCESS_TOKEN environment variable.")
                except Exception as e:
                    if isinstance(e, Exception) and "GitHub API" in str(e):
                        raise
                    # If we can't parse the response, raise the original error
                    response.raise_for_status()
            elif response.status_code == 401 and self.access_token:
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
            else:
                response.raise_for_status()

        return response

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
        except Exception as e:
            logger.warning(
                "Tree listing failed for %s (%s); falling back to the "
                "directory walk", repo_name, e,
            )
        paths = self.fetch_repo_files(repo_name)
        return self.select_files([(p, 0) for p in paths])

    def load_data(self, repo_url: str) -> List[Document]:
        """Load every ingestable text file in ``repo_url`` as a Document."""
        repo_name = self.normalize_repo(repo_url)
        if not repo_name or "/" not in repo_name:
            raise ValueError(
                f"Not a valid GitHub repository: {repo_url!r}. "
                "Expected a github.com URL like https://github.com/owner/name."
            )
        branch = self.get_default_branch(repo_name)
        files = self._list_candidate_files(repo_name, branch)
        logger.info(
            "Fetching %d file(s) from %s@%s", len(files), repo_name, branch
        )

        # Fetch in parallel: this phase is pure network latency, and it was
        # previously one blocking round-trip per file.
        contents: Dict[str, Optional[str]] = {}

        def _fetch(file_path: str) -> Tuple[str, Optional[str]]:
            try:
                return file_path, self.fetch_file_content(repo_name, file_path)
            except Exception as e:
                # One unreadable file must not sink the whole repo ingest.
                logger.warning("Skipping %s: %s", file_path, e)
                return file_path, None

        max_workers = min(self._max_workers(), len(files)) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for file_path, content in pool.map(_fetch, files):
                contents[file_path] = content

        documents = []
        for file_path in files:
            content = contents.get(file_path)
            # Skip binary files (content is None)
            if not content:
                continue
            documents.append(Document(
                text=content,
                doc_id=file_path,
                extra_info={
                    "title": file_path,
                    "source": (
                        f"https://github.com/{repo_name}/blob/{branch}/{file_path}"
                    ),
                }
            ))
        return documents
