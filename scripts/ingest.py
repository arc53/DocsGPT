import os
import sys
from collections import defaultdict
from typing import List, Optional

import dotenv
import nltk
import typer

from parser.file.bulk import SimpleDirectoryReader
from parser.java2doc import extract_functions_and_classes as extract_java
from parser.js2doc import extract_functions_and_classes as extract_js
from parser.open_ai_func import call_openai_api, get_user_permission
from parser.py2doc import extract_functions_and_classes as extract_py
from parser.py2doc import transform_to_docs
from parser.schema.base import Document
from parser.token_func import group_split

dotenv.load_dotenv()

app = typer.Typer(add_completion=False)

nltk.download('punkt', quiet=True)
nltk.download('averaged_perceptron_tagger', quiet=True)


def metadata_from_filename(title):
    return {'title': title}

# Splits all files in specified folder to documents
@app.command()
def ingest(yes: bool = typer.Option(False, "-y", "--yes", prompt=False,
                                    help="Whether to skip price confirmation"),
           dir: Optional[List[str]] = typer.Option(["inputs"],
                                                   help="""List of paths to directory for index creation.
                                                        E.g. --dir inputs --dir inputs2"""),
           file: Optional[List[str]] = typer.Option(None,
                                                    help="""File paths to use (Optional; overrides dir).
                                                        E.g. --file inputs/1.md --file inputs/2.md"""),
           recursive: Optional[bool] = typer.Option(True, help="Whether to recursively search in subdirectories."),
           limit: Optional[int] = typer.Option(None, help="Maximum number of files to read."),
           formats: Optional[List[str]] = typer.Option([".rst", ".md"],
                                                       help="""List of required extensions (list with .)
                                                        Currently supported: 
                                                        .rst, .md, .pdf, .docx, .csv, .epub, .html, .mdx"""),
           exclude: Optional[bool] = typer.Option(True, help="Whether to exclude hidden files (dotfiles)."),
           sample: Optional[bool] = typer.Option(False,
                                                 help="Whether to output sample of the first 5 split documents."),
           token_check: Optional[bool] = typer.Option(True, help="Whether to group small documents and split large."),
           min_tokens: Optional[int] = typer.Option(150, help="Minimum number of tokens to not group."),
           max_tokens: Optional[int] = typer.Option(2000, help="Maximum number of tokens to not split."),
           ):
    """
        Creates index from specified location or files.
        By default /inputs folder is used, .rst and .md are parsed.
    """

    def process_one_docs(directory, folder_name):
        raw_docs = SimpleDirectoryReader(input_dir=directory, input_files=file, recursive=recursive,
                                         required_exts=formats, num_files_limit=limit,
                                         exclude_hidden=exclude, file_metadata=metadata_from_filename).load_data()

        # Here we split the documents, as needed, into smaller chunks.
        # We do this due to the context limits of the LLMs.
        raw_docs = group_split(documents=raw_docs, min_tokens=min_tokens, max_tokens=max_tokens,
                               token_check=token_check)
        # Old method
        # text_splitter = RecursiveCharacterTextSplitter()
        # docs = text_splitter.split_documents(raw_docs)

        # Sample feature
        if sample:
            for i in range(min(5, len(raw_docs))):
                print(raw_docs[i].text)

        docs = [Document.to_langchain_format(raw_doc) for raw_doc in raw_docs]

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
