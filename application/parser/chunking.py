import logging
import re
from typing import List, Tuple

from application.parser.schema.base import Document
from application.utils import get_encoding

logger = logging.getLogger(__name__)


class Chunker:
    """Helper class to split documents into smaller chunks for ingestion.

    Supports classic mathematical token-slicing and recursive character splitting.
    """

    def __init__(
        self,
        chunking_strategy: str = "classic_chunk",
        max_tokens: int = 2000,
        min_tokens: int = 150,
        duplicate_headers: bool = False,
        chunk_overlap: int = 200,
    ) -> None:
        """Initializes the Chunker.

        Args:
            chunking_strategy: The chunking strategy to use.
                Supported values: "classic_chunk", "recursive_chunk".
            max_tokens: Maximum number of tokens per chunk.
            min_tokens: Minimum number of tokens per chunk.
            duplicate_headers: Whether to duplicate document headers in classic chunking.
            chunk_overlap: Number of tokens to overlap between chunks (for recursive chunking).

        Raises:
            ValueError: If an unsupported chunking strategy is specified.
        """
        if chunking_strategy not in ["classic_chunk", "recursive_chunk"]:
            raise ValueError(f"Unsupported chunking strategy: {chunking_strategy}")
        self.chunking_strategy = chunking_strategy
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens
        self.duplicate_headers = duplicate_headers
        self.chunk_overlap = chunk_overlap
        self.encoding = get_encoding()

    def separate_header_and_body(self, text: str) -> Tuple[str, str]:
        """Separates the first three lines as header and the rest as body.

        Args:
            text: The raw text string.

        Returns:
            A tuple of (header_string, body_string).
        """
        header_pattern = r"^(.*?\n){3}"
        match = re.match(header_pattern, text)
        if match:
            header = match.group(0)
            body = text[len(header) :]
        else:
            header, body = "", text  # No header, treat entire text as body
        return header, body

    def split_document(self, doc: Document) -> List[Document]:
        """Splits a single document into chunks mathematically (legacy classic strategy).

        Args:
            doc: The Document object to split.

        Returns:
            A list of chunked Document objects.
        """
        split_docs = []
        header, body = self.separate_header_and_body(doc.text)
        header_tokens = self.encoding.encode(header) if header else []
        body_tokens = self.encoding.encode(body)

        current_position = 0
        part_index = 0
        while current_position < len(body_tokens):
            end_position = current_position + self.max_tokens - len(header_tokens)
            chunk_tokens = (
                header_tokens + body_tokens[current_position:end_position]
                if self.duplicate_headers or part_index == 0
                else body_tokens[current_position:end_position]
            )
            chunk_text = self.encoding.decode(chunk_tokens)
            new_doc = Document(
                text=chunk_text,
                doc_id=f"{doc.doc_id}-{part_index}",
                embedding=doc.embedding,
                extra_info={
                    **(doc.extra_info or {}),
                    "token_count": len(chunk_tokens),
                },
            )
            split_docs.append(new_doc)
            current_position = end_position
            part_index += 1
            header_tokens = []
        return split_docs

    def classic_chunk(self, documents: List[Document]) -> List[Document]:
        """Applies classic chunking logic on a list of documents.

        Args:
            documents: List of Document objects to chunk.

        Returns:
            A list of chunked Document objects.
        """
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
                doc.extra_info = doc.extra_info or {}
                doc.extra_info["token_count"] = token_count
                processed_docs.append(doc)
                i += 1
            else:
                # Split large documents
                processed_docs.extend(self.split_document(doc))
                i += 1
        return processed_docs

    def recursive_chunk(self, documents: List[Document]) -> List[Document]:
        """Splits documents recursively based on semantic boundaries using tiktoken.

        Args:
            documents: List of Document objects to chunk.

        Returns:
            A list of chunked Document objects.
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        processed_docs = []

        splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            encoding_name="cl100k_base",
            chunk_size=self.max_tokens,
            chunk_overlap=self.chunk_overlap,
        )

        for doc in documents:
            chunks = splitter.split_text(doc.text)
            for part_index, chunk_text in enumerate(chunks):
                chunk_tokens = self.encoding.encode(chunk_text)
                token_count = len(chunk_tokens)

                new_doc = Document(
                    text=chunk_text,
                    doc_id=f"{doc.doc_id}-{part_index}",
                    embedding=doc.embedding,
                    extra_info={
                        **(doc.extra_info or {}),
                        "token_count": token_count,
                    },
                )
                processed_docs.append(new_doc)

        return processed_docs

    def chunk(self, documents: List[Document]) -> List[Document]:
        """Dispatches documents to the appropriate chunking strategy.

        Args:
            documents: List of Document objects to chunk.

        Returns:
            A list of chunked Document objects.

        Raises:
            ValueError: If an unsupported chunking strategy is set.
        """
        if self.chunking_strategy == "classic_chunk":
            return self.classic_chunk(documents)
        elif self.chunking_strategy == "recursive_chunk":
            return self.recursive_chunk(documents)
        else:
            raise ValueError("Unsupported chunking strategy")
