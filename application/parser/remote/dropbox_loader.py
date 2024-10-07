from application.parser.remote.base import BaseRemote
from langchain_community.document_loaders import DropboxLoader

class DropboxLoaderRemote(BaseRemote):
    def load_data(self, inputs):
        data = eval(inputs)
        access_token = data.get("access_token")
        folder_path = data.get("folder_path", "")
        recursive = data.get("recursive")
        if(recursive == "True"):
            recursive = True
        else:
            recursive = False
        
        
        print(f"Loading documents from Dropbox with access token {access_token}")
        
        self.loader = DropboxLoader(
            access_token=access_token,
            folder_path=folder_path,
            recursive=recursive,
            
        )
        documents = self.loader.load()
        print(f"Loaded {len(documents)} documents from Dropbox")
        return documents
