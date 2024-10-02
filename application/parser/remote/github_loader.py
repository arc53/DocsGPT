import os
import base64
import requests
from typing import List
from application.parser.remote.base import BaseRemote
from application.parser.schema.base import Document

class GitHubLoader(BaseRemote):
    def __init__(self, access_token: str):
        self.access_token = access_token

    def fetch_file_content(self, repo_url: str, file_path: str) -> str:
        url = f"https://api.github.com/repos/{repo_url}/contents/{file_path}"
        headers = {
            "Authorization": f"token {self.access_token}",
            "Accept": "application/vnd.github.v3.raw"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        content = response.json()
        if content.get("encoding") == "base64":
            return base64.b64decode(content["content"]).decode("utf-8")
        return content["content"]

    def fetch_repo_files(self, repo_url: str, path: str = "") -> List[str]:
        url = f"https://api.github.com/repos/{repo_url}/contents/{path}"
        headers = {
            "Authorization": f"token {self.access_token}",
            "Accept": "application/vnd.github.v3.raw"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        contents = response.json()
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
            documents.append(Document(content=content, metadata={"file_path": file_path}))
        return documents
