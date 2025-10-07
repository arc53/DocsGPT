import base64
import requests
import time
from typing import List, Optional
from application.parser.remote.base import BaseRemote
from application.parser.schema.base import Document
import mimetypes
from application.core.settings import settings

class GitHubLoader(BaseRemote):
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
            '.txt', '.md', '.markdown', '.rst', '.json', '.xml', '.yaml', '.yml',
            '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp',
            '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala',
            '.html', '.css', '.scss', '.sass', '.less',
            '.sh', '.bash', '.zsh', '.fish',
            '.sql', '.r', '.m', '.mat',
            '.ini', '.cfg', '.conf', '.config', '.env',
            '.gitignore', '.dockerignore', '.editorconfig',
            '.log', '.csv', '.tsv'
        }

        # Get file extension
        file_lower = file_path.lower()
        for ext in text_extensions:
            if file_lower.endswith(ext):
                return True

        # Also check MIME type
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type and (mime_type.startswith("text") or mime_type in ["application/json", "application/xml"]):
            return True

        return False

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
            response = requests.get(url, headers=self.headers)

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

                    print(f"GitHub API 403 Error: {error_msg}")
                    print(f"Rate limit remaining: {remaining}, Reset time: {reset_time}")

                    if "rate limit" in error_msg.lower():
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt  # Exponential backoff
                            print(f"Rate limit hit, waiting {wait_time} seconds before retry...")
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
            else:
                response.raise_for_status()

        return response

    def fetch_repo_files(self, repo_url: str, path: str = "") -> List[str]:
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

    def load_data(self, repo_url: str) -> List[Document]:
        repo_name = repo_url.split("github.com/")[-1]
        files = self.fetch_repo_files(repo_name)
        documents = []
        for file_path in files:
            content = self.fetch_file_content(repo_name, file_path)
            # Skip binary files (content is None)
            if content is None:
                continue
            documents.append(Document(
                text=content,
                doc_id=file_path,
                extra_info={
                    "title": file_path,
                    "source": f"https://github.com/{repo_name}/blob/main/{file_path}"
                }
            ))
        return documents
