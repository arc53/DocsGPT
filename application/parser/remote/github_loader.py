import base64
import requests
from typing import List
from application.parser.remote.base import BaseRemote
from langchain_core.documents import Document
import mimetypes

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
            mime_type, _ = mimetypes.guess_type(file_path)  # Guess the MIME type based on the file extension

            if content.get("encoding") == "base64":
                if mime_type and mime_type.startswith("text"):  # Handle only text files
                    try:
                        decoded_content = base64.b64decode(content["content"]).decode("utf-8")
                        return f"Filename: {file_path}\n\n{decoded_content}"
                    except Exception as e:
                        raise e
                else:
                    return f"Filename: {file_path} is a binary file and was skipped."
            else:
                return f"Filename: {file_path}\n\n{content['content']}"
        else:
            response.raise_for_status()

    def fetch_repo_files(self, repo_url: str, path: str = "") -> List[str]:
        url = f"https://api.github.com/repos/{repo_url}/contents/{path}"
        response = requests.get(url, headers={**self.headers, "Accept": "application/vnd.github.v3.raw"})
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
            documents.append(Document(page_content=content, metadata={"title": file_path, 
            "source": f"https://github.com/{repo_name}/blob/main/{file_path}"}))
        return documents
