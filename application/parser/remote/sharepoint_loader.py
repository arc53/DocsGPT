import requests
from msal import ConfidentialClientApplication
import os

class SharePointLoader:
    def __init__(self, client_id, client_secret, tenant_id, sharepoint_site, drive_id):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.sharepoint_site = sharepoint_site
        self.drive_id = drive_id
        self.token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        self.api_url = f"https://graph.microsoft.com/v1.0/sites/{self.sharepoint_site}/drives/{self.drive_id}/root/children"
        self.token = self._get_access_token()

    def _get_access_token(self):
        app = ConfidentialClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            client_credential=self.client_secret,
        )
        token_response = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" in token_response:
            return token_response["access_token"]
        else:
            raise Exception("Unable to fetch access token.")

    def get_files(self):
        headers = {
            "Authorization": f"Bearer {self.token}"
        }
        response = requests.get(self.api_url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to retrieve files from SharePoint: {response.status_code}, {response.text}")

    def download_file(self, file_id, output_dir):
        download_url = f"{self.api_url}/{file_id}/content"
        headers = {
            "Authorization": f"Bearer {self.token}"
        }
        response = requests.get(download_url, headers=headers)
        if response.status_code == 200:
            file_path = os.path.join(output_dir, file_id)
            with open(file_path, 'wb') as f:
                f.write(response.content)
            return file_path
        else:
            raise Exception(f"Failed to download file: {response.status_code}, {response.text}")

# Example usage
if __name__ == "__main__":
    loader = SharePointLoader(
        client_id="your_client_id",
        client_secret="your_client_secret",
        tenant_id="your_tenant_id",
        sharepoint_site="your_sharepoint_site_id",
        drive_id="your_drive_id"
    )
    files = loader.get_files()
    print("Files in SharePoint Drive:", files)
