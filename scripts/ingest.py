import sys
import nltk
import dotenv

from langchain.text_splitter import RecursiveCharacterTextSplitter

from parser.file.bulk import SimpleDirectoryReader
from parser.schema.base import Document
from parser.open_ai_func import call_openai_api, get_user_permission

dotenv.load_dotenv()

#Specify your folder HERE
directory_to_ingest = 'data_test'

nltk.download('punkt')
nltk.download('averaged_perceptron_tagger')

#Splits all files in specified folder to documents
raw_docs = SimpleDirectoryReader(input_dir=directory_to_ingest).load_data()
raw_docs = [Document.to_langchain_format(raw_doc) for raw_doc in raw_docs]
# Here we split the documents, as needed, into smaller chunks.
# We do this due to the context limits of the LLMs.
text_splitter = RecursiveCharacterTextSplitter()
docs = text_splitter.split_documents(raw_docs)

# Here we check for command line arguments for bot calls.
# If no argument exists or the permission_bypass_flag argument is not '-y',
# user permission is requested to call the API.
if len(sys.argv) > 1:
    permission_bypass_flag = sys.argv[1]
    if permission_bypass_flag == '-y':
        call_openai_api(docs)
    else:
        get_user_permission(docs)
else:
    get_user_permission(docs)