import os
from typing import List
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request
from io import BytesIO
from langchain_core.documents import Document
from application.parser.remote.base import BaseRemote

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

class GoogleDriveLoader(BaseRemote):
    def __init__(self, token_path: str, credentials_path: str):
        # Load OAuth2 credentials from token and credentials JSON files
        self.creds = None
        if os.path.exists(token_path):
            self.creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                raise Exception("Invalid or missing credentials. Please authenticate.")

        # Initialize the Google Drive API client
        self.service = build('drive', 'v3', credentials=self.creds)

    def fetch_file_content(self, file_id: str) -> str:
        request = self.service.files().get_media(fileId=file_id)
        file_io = BytesIO()
        downloader = MediaIoBaseDownload(file_io, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        file_io.seek(0)
        return file_io.read().decode("utf-8")

    def fetch_drive_files(self, folder_id: str = 'root', mime_type_filter: List[str] = None) -> List[dict]:
        query = f"'{folder_id}' in parents"
        if mime_type_filter:
            mime_types_query = " or ".join([f"mimeType='{mime_type}'" for mime_type in mime_type_filter])
            query += f" and ({mime_types_query})"

        results = self.service.files().list(q=query, pageSize=1000, fields="files(id, name, mimeType)").execute()
        return results.get('files', [])

    def load_data(self, folder_id: str = 'root', mime_type_filter: List[str] = None) -> List[Document]:
        # Fetch the list of files within the specified folder
        files = self.fetch_drive_files(folder_id, mime_type_filter)
        documents = []
        
        # Loop over each file, download its content, and convert it into a document
        for file in files:
            if file['mimeType'] != 'application/vnd.google-apps.folder':
                try:
                    content = self.fetch_file_content(file['id'])
                    documents.append(Document(page_content=content, metadata={
                        "title": file['name'],
                        "source": f"https://drive.google.com/file/d/{file['id']}/view"
                    }))
                except Exception as e:
                    print(f"Failed to load file {file['name']}: {e}")
        return documents
