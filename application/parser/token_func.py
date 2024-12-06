import re
from math import ceil
from typing import List
import sys

import tiktoken
from application.parser.schema.base import Document


def separate_header_and_body(text):
    header_pattern = r"^(.*?\n){3}"
    match = re.match(header_pattern, text)
    if match:
        header = match.group(0)
        body = text[len(header) :]
    else:
        header = ""
        body = text
    print(
        f"Header: {header.strip()[:50]}... | Body length: {len(body)}", file=sys.stderr
    )
    return header, body

def is_text_document(doc: Document) -> bool:
    return doc.text is not None and doc.text.strip() != ""

def group_documents(
    documents: List[Document], min_tokens: int, max_tokens: int
) -> List[Document]:
    docs = []
    current_group = None

    print(
        f"Starting to group documents. Total documents: {len(documents)}",
        file=sys.stderr,
    )
    encoding = tiktoken.get_encoding("cl100k_base")

    for idx, doc in enumerate(documents):
        print(f"Processing document {idx + 1}/{len(documents)}", file=sys.stderr)
        if not is_text_document(doc):
            print(f"Skipping document {idx + 1} as it has no text", file=sys.stderr)
            docs.append(doc)
            continue
        
        doc_tokens = encoding.encode(doc.text)
        doc_len = len(doc_tokens)
        print(f"Document length: {doc_len} tokens", file=sys.stderr)

        # Check if current group is empty or if the document can be added based on token count and matching metadata
        if current_group is None or (
            len(tiktoken.get_encoding("cl100k_base").encode(current_group.text))
            + doc_len
            < max_tokens
            and doc_len < min_tokens
            and current_group.extra_info == doc.extra_info
        ):
            if current_group is None:
                current_group = doc  # Use the document directly to retain its metadata
                print(f"Starting a new group with document {idx + 1}", file=sys.stderr)
            else:
                current_group.text += " " + doc.text  # Append text to the current group
                print(f"Added document {idx + 1} to current group", file=sys.stderr)
        else:
            print(
                f"Finalizing current group and starting a new group with document {idx + 1}",
                file=sys.stderr,
            )
            docs.append(current_group)
            current_group = doc  # Start a new group with the current document

    if current_group is not None:
        print(f"Finalizing the last group", file=sys.stderr)
        docs.append(current_group)

    print(f"Total groups created: {len(docs)}", file=sys.stderr)
    return docs


def split_documents(documents: List[Document], max_tokens: int) -> List[Document]:
    docs = []
    print(
        f"Starting to split documents. Total documents: {len(documents)}",
        file=sys.stderr,
    )
    encoding = tiktoken.get_encoding("cl100k_base")

    for idx, doc in enumerate(documents):
        print(f"Processing document {idx + 1}/{len(documents)}", file=sys.stderr)
        if not is_text_document(doc):
            print("Skipping splitting for non-text document", file=sys.stderr)
            docs.append(doc)
            continue

        token_length = len(encoding.encode(doc.text))
        print(f"Document length: {token_length} tokens", file=sys.stderr)
        if token_length <= max_tokens:
            print(
                f"Document {idx + 1} fits within max tokens, no splitting needed",
                file=sys.stderr,
            )
            docs.append(doc)
        else:
            header, body = separate_header_and_body(doc.text)
            if len(encoding.encode(header)) > max_tokens:
                print(
                    f"Header exceeds max tokens. Treating entire document as body.",
                    file=sys.stderr,
                )
                body = doc.text
                header = ""

            num_body_parts = ceil(token_length / max_tokens)
            part_length = ceil(len(body) / num_body_parts)
            print(
                f"Splitting document {idx + 1} into {num_body_parts} parts",
                file=sys.stderr,
            )
            body_parts = [
                body[i : i + part_length] for i in range(0, len(body), part_length)
            ]
            for i, body_part in enumerate(body_parts):
                new_doc = Document(
                    text=(header + body_part.strip()).strip(),
                    doc_id=f"{doc.doc_id}-{i}" if doc.doc_id else None,
                    embedding=doc.embedding,
                    extra_info=doc.extra_info,
                    tables=doc.tables,
                    images=doc.images,
                )
                print(
                    f"Created new document part {i + 1} for document {idx + 1}",
                    file=sys.stderr,
                )
                docs.append(new_doc)
    print(f"Total split documents created: {len(docs)}", file=sys.stderr)
    return docs


def group_split(
    documents: List[Document],
    max_tokens: int = 2000,
    min_tokens: int = 150,
    token_check: bool = True,
):
    if not token_check:
        print("Token check is disabled. Returning original documents.", file=sys.stderr)
        return documents

    print("Grouping small documents", file=sys.stderr)
    try:
        documents = group_documents(
            documents=documents, min_tokens=min_tokens, max_tokens=max_tokens
        )
    except Exception as e:
        print(f"Error during grouping: {e}", file=sys.stderr)

    print("Separating large documents", file=sys.stderr)
    try:
        documents = split_documents(documents=documents, max_tokens=max_tokens)
    except Exception as e:
        print(f"Error during splitting: {e}", file=sys.stderr)

    print(f"Total documents after processing: {len(documents)}", file=sys.stderr)
    return documents
