import os
import re
import sys
import nltk
import dotenv
import typer
import ast
import tiktoken
from math import ceil


from collections import defaultdict
from pathlib import Path
from typing import List, Optional, Tuple

from langchain.text_splitter import RecursiveCharacterTextSplitter

from parser.file.bulk import SimpleDirectoryReader
from parser.schema.base import Document
from parser.open_ai_func import call_openai_api, get_user_permission
from parser.py2doc import transform_to_docs
from parser.py2doc import extract_functions_and_classes as extract_py
from parser.js2doc import extract_functions_and_classes as extract_js
from parser.java2doc import extract_functions_and_classes as extract_java


dotenv.load_dotenv()

app = typer.Typer(add_completion=False)

nltk.download('punkt', quiet=True)
nltk.download('averaged_perceptron_tagger', quiet=True)


def group_documents(documents: List[Document], min_tokens: int = 50, max_tokens: int = 2000) -> List[Document]:
    groups = []
    current_group = None

    for doc in documents:
        doc_len = len(tiktoken.get_encoding("cl100k_base").encode(doc.text))

        if current_group is None:
            current_group = Document(text=doc.text, doc_id=doc.doc_id, embedding=doc.embedding,
                                     extra_info=doc.extra_info)
        elif len(tiktoken.get_encoding("cl100k_base").encode(current_group.text)) + doc_len < max_tokens and doc_len >= min_tokens:
            current_group.text += " " + doc.text
        else:
            groups.append(current_group)
            current_group = Document(text=doc.text, doc_id=doc.doc_id, embedding=doc.embedding,
                                     extra_info=doc.extra_info)

    if current_group is not None:
        groups.append(current_group)

    return groups


def separate_header_and_body(text):
    header_pattern = r"^(.*?\n){3}"
    match = re.match(header_pattern, text)
    header = match.group(0)
    body = text[len(header):]
    return header, body

def split_documents(documents: List[Document], max_tokens: int = 2000) -> List[Document]:
    new_documents = []
    for doc in documents:
        token_length = len(tiktoken.get_encoding("cl100k_base").encode(doc.text))
        print(token_length)
        if token_length <= max_tokens:
            new_documents.append(doc)
        else:
            header, body = separate_header_and_body(doc.text)
            num_body_parts = ceil(token_length / max_tokens)
            part_length = ceil(len(body) / num_body_parts)
            body_parts = [body[i:i + part_length] for i in range(0, len(body), part_length)]
            for i, body_part in enumerate(body_parts):
                new_doc = Document(text=header + body_part.strip(),
                                   doc_id=f"{doc.doc_id}-{i}",
                                   embedding=doc.embedding,
                                   extra_info=doc.extra_info)
                new_documents.append(new_doc)
    return new_documents


#Splits all files in specified folder to documents
@app.command()
def ingest(yes: bool = typer.Option(False, "-y", "--yes", prompt=False,
                                                   help="Whether to skip price confirmation"),
           dir: Optional[List[str]] = typer.Option(["inputs"],
                                                   help="""List of paths to directory for index creation.
                                                        E.g. --dir inputs --dir inputs2"""),
           file: Optional[List[str]] = typer.Option(None,
                                                   help="""File paths to use (Optional; overrides dir).
                                                        E.g. --file inputs/1.md --file inputs/2.md"""),
           recursive: Optional[bool] = typer.Option(True,
                                                   help="Whether to recursively search in subdirectories."),
           limit: Optional[int] = typer.Option(None,
                                                   help="Maximum number of files to read."),
           formats: Optional[List[str]] = typer.Option([".rst", ".md"],
                                                   help="""List of required extensions (list with .)
                                                        Currently supported: .rst, .md, .pdf, .docx, .csv, .epub, .html, .mdx"""),
           exclude: Optional[bool] = typer.Option(True, help="Whether to exclude hidden files (dotfiles).")):

    """
        Creates index from specified location or files.
        By default /inputs folder is used, .rst and .md are parsed.
    """

    def process_one_docs(directory, folder_name):
        raw_docs = SimpleDirectoryReader(input_dir=directory, input_files=file, recursive=recursive,
                                         required_exts=formats, num_files_limit=limit,
                                         exclude_hidden=exclude).load_data()

        raw_docs = group_documents(raw_docs)
        raw_docs = split_documents(raw_docs)

        print(raw_docs)
        raw_docs = [Document.to_langchain_format(raw_doc) for raw_doc in raw_docs]
        # Here we split the documents, as needed, into smaller chunks.
        # We do this due to the context limits of the LLMs.
        text_splitter = RecursiveCharacterTextSplitter()
        docs = text_splitter.split_documents(raw_docs)

        # Here we check for command line arguments for bot calls.
        # If no argument exists or the yes is not True, then the
        # user permission is requested to call the API.
        if len(sys.argv) > 1:
            if yes:
                call_openai_api(docs, folder_name)
            else:
                get_user_permission(docs, folder_name)
        else:
            get_user_permission(docs, folder_name)

    folder_counts = defaultdict(int)
    folder_names = []
    for dir_path in dir:
        folder_name = os.path.basename(os.path.normpath(dir_path))
        folder_counts[folder_name] += 1
        if folder_counts[folder_name] > 1:
            folder_name = f"{folder_name}_{folder_counts[folder_name]}"
        folder_names.append(folder_name)

    for directory, folder_name in zip(dir, folder_names):
        process_one_docs(directory, folder_name)


@app.command()
def convert(dir: Optional[str] = typer.Option("inputs",
                                                   help="""Path to directory to make documentation for.
                                                        E.g. --dir inputs """),
            formats: Optional[str] = typer.Option("py",
                                                        help="""Required language. 
                                                        py, js, java supported for now""")):

    """
            Creates documentation linked to original functions from specified location.
            By default /inputs folder is used, .py is parsed.
    """
    if formats == 'py':
        functions_dict, classes_dict = extract_py(dir)
    elif formats == 'js':
        functions_dict, classes_dict = extract_js(dir)
    elif formats == 'java':
        functions_dict, classes_dict = extract_java(dir)
    else:
        raise Exception("Sorry, language not supported yet")
    transform_to_docs(functions_dict, classes_dict, formats, dir)
if __name__ == "__main__":
  app()


