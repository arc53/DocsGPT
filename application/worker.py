import os
import shutil
import string
import zipfile
from urllib.parse import urljoin

import nltk
import requests

from application.core.settings import settings
from application.parser.file.bulk import SimpleDirectoryReader
from application.parser.open_ai_func import call_openai_api
from application.parser.schema.base import Document
from application.parser.token_func import group_split

try:
    nltk.download('punkt', quiet=True)
    nltk.download('averaged_perceptron_tagger', quiet=True)
except FileExistsError:
    pass


def metadata_from_filename(title):
    store = title.split('/')
    store = store[1] + '/' + store[2]
    return {'title': title, 'store': store}


def generate_random_string(length):
    return ''.join([string.ascii_letters[i % 52] for i in range(length)])

current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def ingest_worker(self, directory, formats, name_job, filename, user):
    # directory = 'inputs' or 'temp'
    # formats = [".rst", ".md"]
    input_files = None
    recursive = True
    limit = None
    exclude = True
    # name_job = 'job1'
    # filename = 'install.rst'
    # user = 'local'
    sample = False
    token_check = True
    min_tokens = 150
    max_tokens = 1250
    full_path = directory + '/' + user + '/' + name_job
    import sys
    print(full_path, file=sys.stderr)
    # check if API_URL env variable is set
    file_data = {'name': name_job, 'file': filename, 'user': user}
    response = requests.get(urljoin(settings.API_URL, "/api/download"), params=file_data)
    # check if file is in the response
    print(response, file=sys.stderr)
    file = response.content

    if not os.path.exists(full_path):
        os.makedirs(full_path)
    with open(full_path + '/' + filename, 'wb') as f:
        f.write(file)

    # check if file is .zip and extract it
    if filename.endswith('.zip'):
        with zipfile.ZipFile(full_path + '/' + filename, 'r') as zip_ref:
            zip_ref.extractall(full_path)
        os.remove(full_path + '/' + filename)

    self.update_state(state='PROGRESS', meta={'current': 1})

    raw_docs = SimpleDirectoryReader(input_dir=full_path, input_files=input_files, recursive=recursive,
                                     required_exts=formats, num_files_limit=limit,
                                     exclude_hidden=exclude, file_metadata=metadata_from_filename).load_data()
    raw_docs = group_split(documents=raw_docs, min_tokens=min_tokens, max_tokens=max_tokens, token_check=token_check)

    docs = [Document.to_langchain_format(raw_doc) for raw_doc in raw_docs]

    call_openai_api(docs, full_path, self)
    self.update_state(state='PROGRESS', meta={'current': 100})

    if sample:
        for i in range(min(5, len(raw_docs))):
            print(raw_docs[i].text)

    # get files from outputs/inputs/index.faiss and outputs/inputs/index.pkl
    # and send them to the server (provide user and name in form)
    file_data = {'name': name_job, 'user': user}
    if settings.VECTOR_STORE == "faiss":
        files = {'file_faiss': open(full_path + '/index.faiss', 'rb'),
                'file_pkl': open(full_path + '/index.pkl', 'rb')}
        response = requests.post(urljoin(settings.API_URL, "/api/upload_index"), files=files, data=file_data)
        response = requests.get(urljoin(settings.API_URL, "/api/delete_old?path=" + full_path))
    else:
        response = requests.post(urljoin(settings.API_URL, "/api/upload_index"), data=file_data)

    
    # delete local
    shutil.rmtree(full_path)

    return {
        'directory': directory,
        'formats': formats,
        'name_job': name_job,
        'filename': filename,
        'user': user,
        'limited': False
    }
