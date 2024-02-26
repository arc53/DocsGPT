import re
from math import ceil
from typing import List

import tiktoken
from application.parser.schema.base import Document


def separate_header_and_body(text):
    header_pattern = r"^(.*?\n){3}"
    match = re.match(header_pattern, text)
    header = match.group(0)
    body = text[len(header):]
    return header, body


def group_documents(documents: List[Document], min_tokens: int, max_tokens: int) -> List[Document]:
    docs = []
    current_group = None

    for doc in documents:
        doc_len = len(tiktoken.get_encoding("cl100k_base").encode(doc.text))

        # Check if current group is empty or if the document can be added based on token count and matching metadata
        if current_group is None or (len(tiktoken.get_encoding("cl100k_base").encode(current_group.text)) + doc_len < max_tokens and doc_len < min_tokens and current_group.extra_info == doc.extra_info):
            if current_group is None:
                current_group = doc  # Use the document directly to retain its metadata
            else:
                current_group.text += " " + doc.text  # Append text to the current group
        else:
            docs.append(current_group)
            current_group = doc  # Start a new group with the current document

    if current_group is not None:
        docs.append(current_group)

    return docs


def split_documents(documents: List[Document], max_tokens: int) -> List[Document]:
    docs = []
    for doc in documents:
        token_length = len(tiktoken.get_encoding("cl100k_base").encode(doc.text))
        if token_length <= max_tokens:
            docs.append(doc)
        else:
            header, body = separate_header_and_body(doc.text)
            if len(tiktoken.get_encoding("cl100k_base").encode(header)) > max_tokens:
                body = doc.text
                header = ""
            num_body_parts = ceil(token_length / max_tokens)
            part_length = ceil(len(body) / num_body_parts)
            body_parts = [body[i:i + part_length] for i in range(0, len(body), part_length)]
            for i, body_part in enumerate(body_parts):
                new_doc = Document(text=header + body_part.strip(),
                                   doc_id=f"{doc.doc_id}-{i}",
                                   embedding=doc.embedding,
                                   extra_info=doc.extra_info)
                docs.append(new_doc)
    return docs


def group_split(documents: List[Document], max_tokens: int = 2000, min_tokens: int = 150, token_check: bool = True):
    if not token_check:
        return documents
    print("Grouping small documents")
    try:
        documents = group_documents(documents=documents, min_tokens=min_tokens, max_tokens=max_tokens)
    except Exception:
        print("Grouping failed, try running without token_check")
    print("Separating large documents")
    try:
        documents = split_documents(documents=documents, max_tokens=max_tokens)
    except Exception:
        print("Grouping failed, try running without token_check")
    return documents
