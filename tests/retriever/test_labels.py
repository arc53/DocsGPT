"""Retrieval labels carry the identity a citation needs to find its chunk."""

import hashlib

import pytest
from sqlalchemy import text as sql_text

from docsgpt.retriever.labels import chunk_key, labels_from_metadata


@pytest.mark.unit
class TestChunkKey:
    def test_is_the_md5_of_the_utf8_text(self):
        text = "Occupancy peaked in August 2019 at 82%."
        assert chunk_key(text) == hashlib.md5(text.encode("utf-8")).hexdigest()

    def test_of_none_is_the_empty_hash(self):
        assert chunk_key(None) == hashlib.md5(b"").hexdigest()

    def test_ignores_metadata_so_it_survives_a_reingest(self):
        # The row id changes on every re-ingest; the text does not, so a
        # citation saved with a conversation still resolves afterwards.
        a = labels_from_metadata({"title": "x", "source_id": "s"}, "same", "s")
        b = labels_from_metadata({"title": "y", "source_id": "s", "page": 3}, "same", "s")
        assert a["chunk_key"] == b["chunk_key"]


def test_chunk_key_matches_postgres_md5_for_non_ascii(pg_conn):
    # The lookup asks Postgres for ``md5(text)``; a key computed here has to
    # hash the same UTF-8 bytes or a citation never finds its chunk.
    text = "Café — Highlands, 1 000 ₽"
    stored = pg_conn.execute(sql_text("SELECT md5(:t)"), {"t": text}).scalar()
    assert chunk_key(text) == stored


@pytest.mark.unit
class TestLabelsFromMetadata:
    def test_carry_source_id_and_chunk_key(self):
        metadata = {"title": "a.pdf", "source": "a.pdf", "source_id": "abc-123"}
        labels = labels_from_metadata(metadata, "some text", "abc-123")
        assert labels["source_id"] == "abc-123"
        assert labels["chunk_key"] == chunk_key("some text")

    def test_source_id_is_the_store_searched_not_the_chunks_own_say(self):
        # A chunk's metadata can be written through the chunk API (a FAISS store kept it as sent), so a
        # ``source_id`` there must not move the chunk to another source: the store's id is the source searched.
        metadata = {"title": "a.pdf", "source": "a.pdf", "source_id": "someone-elses-source"}
        assert labels_from_metadata(metadata, "t", "abc-123")["source_id"] == "abc-123"

    def test_source_id_falls_back_to_metadata_without_a_store_id(self):
        assert labels_from_metadata({"source_id": "abc-123"}, "t", "")["source_id"] == "abc-123"

    def test_keep_the_labels_retrievers_and_prompts_rely_on(self):
        labels = labels_from_metadata({"title": "a.pdf", "source": "a.pdf"}, "t", "s")
        assert labels["title"] == "a.pdf"
        assert labels["source"] == "a.pdf"
        assert labels["filename"] == "a.pdf"

    def test_source_id_falls_back_to_the_store_id_without_the_legacy_prefix(self):
        labels = labels_from_metadata({}, "t", "docsgpt/indexes/abc-123/")
        assert labels["source_id"] == "abc-123"

    def test_wiki_page_path_stays_in_source_not_source_id(self):
        # Wiki chunks carry the page path as ``source``; the id must still be
        # the source's, or the citation looks the chunk up in the wrong place.
        metadata = {"source": "/guide/levy.md", "filename": "/guide/levy.md"}
        labels = labels_from_metadata(metadata, "t", "wiki-src")
        assert labels["source"] == "/guide/levy.md"
        assert labels["source_id"] == "wiki-src"
