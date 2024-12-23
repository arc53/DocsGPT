import re
from typing import List, Tuple
import logging
from application.parser.schema.base import Document
from application.utils import get_encoding

logger = logging.getLogger(__name__)

class Chunker:
    def __init__(
        self,
        chunking_strategy: str = "classic_chunk",
        max_tokens: int = 2000,
        min_tokens: int = 150,
        duplicate_headers: bool = False,
    ):
        if chunking_strategy not in ["classic_chunk"]:
            raise ValueError(f"Unsupported chunking strategy: {chunking_strategy}")
        self.chunking_strategy = chunking_strategy
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens
        self.duplicate_headers = duplicate_headers
        self.encoding = get_encoding()

    def separate_header_and_body(self, text: str) -> Tuple[str, str]:
        header_pattern = r"^(.*?\n){3}"
        match = re.match(header_pattern, text)
        if match:
            header = match.group(0)
            body = text[len(header):]
        else:
            header, body = "", text  # No header, treat entire text as body
        return header, body

    def combine_documents(self, doc: Document, next_doc: Document) -> Document:
        combined_text = doc.text + " " + next_doc.text
        combined_token_count = len(self.encoding.encode(combined_text))
        new_doc = Document(
            text=combined_text,
            doc_id=doc.doc_id,
            embedding=doc.embedding,
            extra_info={**(doc.extra_info or {}), "token_count": combined_token_count}
        )
        return new_doc
    
    def split_document(self, doc: Document) -> List[Document]:
        split_docs = []
        header, body = self.separate_header_and_body(doc.text)
        header_tokens = self.encoding.encode(header) if header else []
        body_tokens = self.encoding.encode(body)

        current_position = 0
        part_index = 0
        while current_position < len(body_tokens):
            end_position = current_position + self.max_tokens - len(header_tokens)
            chunk_tokens = (header_tokens + body_tokens[current_position:end_position]
                            if self.duplicate_headers or part_index == 0 else body_tokens[current_position:end_position])
            chunk_text = self.encoding.decode(chunk_tokens)
            new_doc = Document(
                text=chunk_text,
                doc_id=f"{doc.doc_id}-{part_index}",
                embedding=doc.embedding,
                extra_info={**(doc.extra_info or {}), "token_count": len(chunk_tokens)}
            )
            split_docs.append(new_doc)
            current_position = end_position
            part_index += 1
            header_tokens = []
        return split_docs

    def classic_chunk(self, documents: List[Document]) -> List[Document]:
        processed_docs = []
        i = 0
        while i < len(documents):
            doc = documents[i]
            tokens = self.encoding.encode(doc.text)
            token_count = len(tokens)

            if self.min_tokens <= token_count <= self.max_tokens:
                doc.extra_info = doc.extra_info or {}
                doc.extra_info["token_count"] = token_count
                processed_docs.append(doc)
                i += 1
            elif token_count < self.min_tokens:
                if i + 1 < len(documents):
                    next_doc = documents[i + 1]
                    next_tokens = self.encoding.encode(next_doc.text)
                    if token_count + len(next_tokens) <= self.max_tokens:
                        # Combine small documents
                        combined_doc = self.combine_documents(doc, next_doc)
                        processed_docs.append(combined_doc)
                        i += 2
                    else:
                        # Keep the small document as is if adding next_doc would exceed max_tokens
                        doc.extra_info = doc.extra_info or {}
                        doc.extra_info["token_count"] = token_count
                        processed_docs.append(doc)
                        i += 1
                else:
                    # No next document to combine with; add the small document as is
                    doc.extra_info = doc.extra_info or {}
                    doc.extra_info["token_count"] = token_count
                    processed_docs.append(doc)
                    i += 1
            else:
                # Split large documents
                processed_docs.extend(self.split_document(doc))
                i += 1
        return processed_docs

    def chunk(
        self,
        documents: List[Document]
    ) -> List[Document]:
        if self.chunking_strategy == "classic_chunk":
            return self.classic_chunk(documents)
        else:
            raise ValueError("Unsupported chunking strategy")
