"""Tests for ChunkerCreator registry + byte-identical classic_chunk parity."""

from __future__ import annotations

import pytest

from application.parser.chunking import Chunker
from application.parser.chunking_creator import ChunkerCreator
from application.parser.schema.base import Document


def _docs():
    """Representative mix: a small doc, a large splittable doc, a tiny doc."""
    return [
        Document(text="A short paragraph of text.", doc_id="small"),
        Document(text="word " * 4000, doc_id="large"),
        Document(text="tiny", doc_id="below-min"),
        Document(text="header1\nheader2\nheader3\n" + "lorem " * 3000, doc_id="hdr"),
    ]


def _serialize(chunks):
    """Stable, comparable view of a chunk list."""
    return [(c.doc_id, c.text, c.extra_info) for c in chunks]


@pytest.mark.unit
class TestChunkerCreator:
    def test_classic_chunk_is_registered(self):
        assert "classic_chunk" in ChunkerCreator.chunkers
        assert ChunkerCreator.chunkers["classic_chunk"] is Chunker

    def test_create_chunker_returns_chunker(self):
        chunker = ChunkerCreator.create_chunker(
            "classic_chunk", max_tokens=1250, min_tokens=150,
        )
        assert isinstance(chunker, Chunker)
        assert chunker.max_tokens == 1250
        assert chunker.min_tokens == 150

    def test_create_chunker_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="No chunker class found"):
            ChunkerCreator.create_chunker("does_not_exist")

    def test_register_is_idempotent_and_overrides(self):
        class Dummy:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        try:
            ChunkerCreator.register("dummy_strategy", Dummy)
            inst = ChunkerCreator.create_chunker("dummy_strategy", x=1)
            assert isinstance(inst, Dummy)
            assert inst.kwargs == {"x": 1}
        finally:
            ChunkerCreator.chunkers.pop("dummy_strategy", None)


@pytest.mark.unit
class TestByteIdenticalParity:
    def test_creator_output_matches_direct_chunker(self):
        # The refactor must not change classic_chunk output: a chunker built
        # via ChunkerCreator must produce identical chunks to the old direct
        # ``Chunker(...)`` instantiation for the same input + params.
        params = dict(max_tokens=1250, min_tokens=150, duplicate_headers=False)

        direct = Chunker(chunking_strategy="classic_chunk", **params)
        via_creator = ChunkerCreator.create_chunker(
            "classic_chunk", chunking_strategy="classic_chunk", **params,
        )

        direct_out = direct.chunk(documents=_docs())
        creator_out = via_creator.chunk(documents=_docs())

        assert _serialize(creator_out) == _serialize(direct_out)
