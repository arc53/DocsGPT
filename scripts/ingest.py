import sys
import nltk
import dotenv
import typer

from typing import List, Optional

from langchain.text_splitter import RecursiveCharacterTextSplitter

from parser.file.bulk import SimpleDirectoryReader
from parser.schema.base import Document
from parser.open_ai_func import call_openai_api, get_user_permission

dotenv.load_dotenv()

app = typer.Typer(add_completion=False)

nltk.download('punkt', quiet=True)
nltk.download('averaged_perceptron_tagger', quiet=True)

#Splits all files in specified folder to documents
@app.command()
def ingest(directory: Optional[str] = typer.Option("inputs",
                                                   help="Path to the directory for index creation."),
           files: Optional[List[str]] = typer.Option(None,
                                                   help="""File paths to use (Optional; overrides directory).
                                                        E.g. --files inputs/1.md --files inputs/2.md"""),
           recursive: Optional[bool] = typer.Option(True,
                                                   help="Whether to recursively search in subdirectories."),
           limit: Optional[int] = typer.Option(None,
                                                   help="Maximum number of files to read."),
           formats: Optional[List[str]] = typer.Option([".rst", ".md"],
                                                   help="""List of required extensions (list with .)
                                                        Currently supported: .rst, .md, .pdf, .docx, .csv, .epub"""),
           exclude: Optional[bool] = typer.Option(True, help="Whether to exclude hidden files (dotfiles).")):

    """
        Creates index from specified location or files.
        By default /inputs folder is used, .rst and .md are parsed.
    """
    raw_docs = SimpleDirectoryReader(input_dir=directory, input_files=files, recursive=recursive,
                                     required_exts=formats, num_files_limit=limit,
                                     exclude_hidden=exclude).load_data()
    raw_docs = [Document.to_langchain_format(raw_doc) for raw_doc in raw_docs]
    print(raw_docs)
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

if __name__ == "__main__":
  app()
