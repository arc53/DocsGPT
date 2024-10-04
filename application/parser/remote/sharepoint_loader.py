from office365.runtime.auth.authentication_context import AuthenticationContext
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.files.file import File
import os

class SharePointLoader:
    def __init__(self, site_url, client_id, client_secret, folder_path):
        """
        Initializes SharePointLoader with necessary credentials and configuration.
        
        :param site_url: URL of the SharePoint site.
        :param client_id: Application Client ID for authentication.
        :param client_secret: Client Secret for authentication.
        :param folder_path: Path to the SharePoint folder for document retrieval.
        """
        self.site_url = site_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.folder_path = folder_path
        self.context = self.authenticate()

    def authenticate(self):
        """
        Authenticates with SharePoint using client credentials.
        """
        auth_context = AuthenticationContext(self.site_url)
        if auth_context.acquire_token_for_app(client_id=self.client_id, client_secret=self.client_secret):
            ctx = ClientContext(self.site_url, auth_context)
            return ctx
        else:
            raise Exception("Authentication failed")

    def fetch_documents(self):
        """
        Fetches all files from a specified SharePoint folder and returns content.
        
        :return: List of document content from SharePoint.
        """
        folder = self.context.web.get_folder_by_server_relative_url(self.folder_path)
        files = folder.files
        self.context.load(files)
        self.context.execute_query()

        documents = []
        for file in files:
            file_url = file.serverRelativeUrl
            file_content = self.download_file(file_url)
            documents.append({"name": file.name, "content": file_content})
        
        return documents

    def download_file(self, file_url):
        """
        Downloads a single file from SharePoint.
        
        :param file_url: URL of the file on SharePoint.
        :return: Content of the file.
        """
        file = File.open_binary(self.context, file_url)
        return file.content

# Usage example
# loader = SharePointLoader(
#     site_url="https://yourtenant.sharepoint.com/sites/yoursite",
#     client_id="YOUR_CLIENT_ID",
#     client_secret="YOUR_CLIENT_SECRET",
#     folder_path="/sites/yoursite/Shared Documents"
# )
# documents = loader.fetch_documents()
# print(documents)
