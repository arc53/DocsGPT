import base64
import requests
from typing import List
from application.parser.remote.base import BaseRemote
from langchain_core.documents import Document

class GitHubLoader(BaseRemote):
    def __init__(self):
        self.access_token = None
        self.headers = {
            "Authorization": f"token {self.access_token}"
        } if self.access_token else {}
        return

    def fetch_file_content(self, repo_url: str, file_path: str) -> str:
        url = f"https://api.github.com/repos/{repo_url}/contents/{file_path}"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            content = response.json()
            if content.get("encoding") == "base64":
                try:
                    decoded_content = base64.b64decode(content["content"]).decode("utf-8")
                    return decoded_content
                except Exception as e:
                    raise
            else:
                return content["content"]
        else:
            response.raise_for_status()

    def fetch_repo_files(self, repo_url: str, path: str = "") -> List[str]:
        url = f"https://api.github.com/repos/{repo_url}/contents/{path}"
        response = requests.get(url, headers=self.headers)
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
            documents.append(Document(page_content=content, metadata={"file_path": file_path}))
        return documents
