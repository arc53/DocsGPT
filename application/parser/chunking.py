import re
from typing import List, Tuple
import logging
from application.parser.chunking_creator import ChunkerCreator
from application.parser.schema.base import Document
from application.parser.tokenization import get_token_counter

logger = logging.getLogger(__name__)

# Smallest share of ``max_tokens`` a chunk must keep for body text when the
# header is duplicated onto every chunk. A header that leaves less than this
# makes each chunk mostly repeated header and multiplies the chunk count -- at
# a budget of 32 out of 1250 a document splits into 39x more chunks than it
# needs -- so duplication is dropped rather than honoured.
_MIN_BODY_BUDGET_RATIO = 0.25


class Chunker:
    """Classic token-window chunker (registered as ``classic_chunk``).

    Strategy dispatch lives in ``ChunkerCreator``; this class is one
    registered implementation. The ``chunking_strategy`` arg is retained for
    backward-compatible construction and is not used for dispatch here.
    """

    def __init__(
        self,
        chunking_strategy: str = "classic_chunk",
        max_tokens: int = 2000,
        min_tokens: int = 150,
        duplicate_headers: bool = False,
    ):
        self.chunking_strategy = chunking_strategy
        # A budget below 1 would ask for a chunk per token; the strategy
        # chunkers clamp the same way.
        self.max_tokens = max(1, int(max_tokens))
        self.min_tokens = min_tokens
        self.duplicate_headers = duplicate_headers
        # Counted in the embedding model's tokenizer, not cl100k: ``max_tokens``
        # is compared against a limit the embedding server enforces in its own
        # units, so counting in any other unit is a guess.
        self.counter = get_token_counter()

    def separate_header_and_body(self, text: str) -> Tuple[str, str]:
        header_pattern = r"^(.*?\n){3}"
        match = re.match(header_pattern, text)
        if match:
            header = match.group(0)
            body = text[len(header):]
        else:
            header, body = "", text  # No header, treat entire text as body
        return header, body



    def split_document(self, doc: Document) -> List[Document]:
        """Split one oversized document into ``max_tokens``-sized chunks.

        Pieces are sliced out of the original text rather than decoded back
        from token ids. WordPiece tokenizers normalise as they decode --
        all-mpnet-base-v2 lowercases -- so a decode round-trip would rewrite
        every stored document.
        """
        header, body = self.separate_header_and_body(doc.text)
        header_tokens = self.counter.count(header) if header else 0

        if header and header_tokens >= self.max_tokens:
            # The header alone fills the budget, so no cut of the body can keep
            # a chunk within it and duplicating it would leave a one-token body
            # budget -- a chunk per body token. It is only the first three
            # lines, not something worth preserving at that cost, so it goes
            # back to being ordinary text and the document splits evenly.
            logger.warning(
                "Header of %s is %d token(s), at or over the %d-token chunk "
                "budget; treating it as body text.",
                doc.doc_id,
                header_tokens,
                self.max_tokens,
            )
            body = f"{header}{body}"
            header, header_tokens = "", 0

        # A chunk carrying the header has that much less room for body text.
        with_header_budget = max(1, self.max_tokens - header_tokens)
        duplicate_headers = self.duplicate_headers
        if duplicate_headers and with_header_budget < self.max_tokens * _MIN_BODY_BUDGET_RATIO:
            logger.warning(
                "Header of %s leaves only %d of %d tokens for body text; "
                "carrying it on the first chunk only.",
                doc.doc_id,
                with_header_budget,
                self.max_tokens,
            )
            duplicate_headers = False

        if duplicate_headers:
            body_pieces = self.counter.split(body, with_header_budget)
        else:
            body_pieces = self.counter.split(
                body, self.max_tokens, first_max_tokens=with_header_budget
            )

        if not body_pieces and header:
            # Nothing but a header: the loop below only ever emits the header
            # attached to a body piece, so without this the document is dropped
            # from the index entirely.
            body_pieces = [""]

        split_docs = []
        for part_index, piece in enumerate(body_pieces):
            include_header = bool(header) and (duplicate_headers or part_index == 0)
            chunk_text = f"{header}{piece}" if include_header else piece
            split_docs.append(
                Document(
                    text=chunk_text,
                    doc_id=f"{doc.doc_id}-{part_index}",
                    embedding=doc.embedding,
                    extra_info={
                        **(doc.extra_info or {}),
                        "token_count": self.counter.count(chunk_text),
                    },
                )
            )
        return split_docs

    def classic_chunk(self, documents: List[Document]) -> List[Document]:
        processed_docs = []
        i = 0
        while i < len(documents):
            doc = documents[i]
            token_count = self.counter.count(doc.text)

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

    def chunk(
        self,
        documents: List[Document]
    ) -> List[Document]:
        return self.classic_chunk(documents)


ChunkerCreator.register("classic_chunk", Chunker)
