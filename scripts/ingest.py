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

import boto3
import botocore
from boto3.s3.transfer import TransferConfig

# When override=True .env variables take precedence over environment. https://pypi.org/project/python-dotenv/
dotenv.load_dotenv(override=True)

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
           use_s3: Optional[bool] = typer.Option(False, "--s3", help="Whether to use S3 as the document store"),
           s3_assume_role: Optional[bool] = typer.Option(False, "--s3-assume", help="Whether to use S3 as the document store"),
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
        if len(sys.argv) > 1 and yes:
            call_openai_api(docs, folder_name, use_s3, s3_assume_role)
        else:
            get_user_permission(docs, folder_name, use_s3, s3_assume_role)

    if not use_s3:
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

    if use_s3:
        s3_bucket_name = os.environ.get("S3_BUCKET")
        aws_assume_role_profile = os.environ.get("AWS_ASSUME_ROLE_PROFILE")
        s3_prefix = os.environ.get("S3_DOCUMENTS_FOLDER")
        if not s3_bucket_name:
            print("Error: S3_BUCKET environment variable is not set.")
            sys.exit(1)
        if not s3_assume_role:
            s3 = boto3.Session().resource("s3")
        elif s3_assume_role:
            if not aws_assume_role_profile:
                print("Error: AWS_ASSUME_ROLE_PROFILE environment variable is not set.")
                sys.exit(1)
            s3 = boto3.Session(profile_name=aws_assume_role_profile).resource("s3")

        if not s3_prefix:
            print(
                "WARNING: S3_DOCUMENTS_FOLDER environment variable is not set. "
                f"All files in S3 bucket '{s3_bucket_name}' will be downloaded. "
                "This could incur significant charges from AWS. "
                "See S3 pricing for 'List Requests' and 'Data Transfer' for more information."
            )
            user_input = input("Continue? (Y/N) \n").lower()
            if user_input != "y":
                print("Ingest aborted. No S3 files were downloaded")
                sys.exit(1)

        if not os.path.exists("s3_temp_storage"):
            os.makedirs("s3_temp_storage")

        try:
            s3_docs_count = sum(
                1
                for obj in s3.Bucket(s3_bucket_name).objects.filter(Prefix=s3_prefix)
                if not (obj.key.endswith(".faiss") or obj.key.endswith(".pkl"))
            )
            filtered_objects = (
                obj
                for obj in s3.Bucket(s3_bucket_name).objects.filter(Prefix=s3_prefix)
                if not obj.key.endswith((".faiss", ".pkl"))
            )
        except botocore.exceptions.ClientError as e:
            if str(e.response["Error"]["Code"]) == "AccessDenied":
                print(
                    f"You do not have AWS permissions to access the specified bucket,'{s3_bucket_name}'. "
                    + "Verify you have AWS permissions to download from and save to this bucket with the supplied credentials."
                )
                sys.exit(1)
            if str(e.response["Error"]["Code"]) == "SignatureDoesNotMatch":
                print(
                    "This error is likely due to expired or incorrect AWS permissions (AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY)."
                )
                raise
            else:
                raise

        if s3_prefix == "" and s3_docs_count < 1:
            raise ValueError(f"No objects were found in {s3_bucket_name} bucket")
        if s3_docs_count < 1:
            raise ValueError(
                f"No objects were found within the '{s3_prefix}' folder in {s3_bucket_name} bucket"
            )

        from tqdm import tqdm

        for obj in tqdm(
            filtered_objects,
            desc=f"Downloading {s3_docs_count} doc(s) from S3 🦖",
            unit="doc(s)",
            total=s3_docs_count,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} {unit} [Time Left: {remaining}]",
        ):
            if obj.key.endswith("/"):
                continue

            s3.Bucket(s3_bucket_name).download_file(
                obj.key,
                f"s3_temp_storage/{os.path.basename(obj.key)}",
                Config=TransferConfig(num_download_attempts=5),
            )

        process_one_docs("s3_temp_storage", "s3_temp_storage")


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
    # Using a dictionary to map between the formats and their respective extraction functions
    # makes the code more scalable. When adding more formats in the future, 
    # you only need to update the extraction_functions dictionary.
    extraction_functions = {
    'py': extract_py,
    'js': extract_js,
    'java': extract_java
    }

    if formats in extraction_functions:
        functions_dict, classes_dict = extraction_functions[formats](dir)
    else:
        raise Exception("Sorry, language not supported yet")                                   
    transform_to_docs(functions_dict, classes_dict, formats, dir)


if __name__ == "__main__":
    app()
