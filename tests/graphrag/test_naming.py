"""Tests for canonical entity naming (the key graph nodes are merged on).

Two failure directions matter. Too little folding splits one entity across
nodes ("agent" / "agents", "VECTOR_STORE" / "vector stores"), so the walk never
connects what the text connects. Too much folding invents entities: stripping
the "s" off ``postgres`` or ``redis`` would merge nothing and create a node no
chunk ever named.
"""

from __future__ import annotations

import pytest

from docsgpt.graphrag.naming import canonical_name, normalize_entity_name


@pytest.mark.unit
class TestCanonicalName:
    @pytest.mark.parametrize(
        "variants, key",
        [
            (["VECTOR_STORE", "Vector store", "vector stores", "vector-stores"], "vector store"),
            ([".env file", "env_file", "ENV FILE"], "env file"),
            (["Celery worker", "Celery workers"], "celery worker"),
            (["agent", "Agents", "agents!"], "agent"),
        ],
    )
    def test_orthographic_variants_share_one_key(self, variants, key):
        assert {canonical_name(v) for v in variants} == {key}

    @pytest.mark.parametrize(
        "singular, plural",
        [
            ("policy", "policies"),
            ("index", "indexes"),
            ("batch", "batches"),
            ("hash", "hashes"),
            ("class", "classes"),
            ("process", "processes"),
            ("status", "statuses"),
            ("bus", "buses"),
            ("alias", "aliases"),
            ("document", "documents"),
            ("service", "services"),
            # Singulars ending in "e" whose plural also ends in "-es": the
            # plural alone cannot say whether to drop "s" or "es".
            ("cache", "caches"),
            ("database", "databases"),
            ("response", "responses"),
            ("release", "releases"),
            ("case", "cases"),
            ("size", "sizes"),
            ("cookie", "cookies"),
        ],
    )
    def test_singular_and_plural_share_one_key(self, singular, plural):
        assert canonical_name(singular) == canonical_name(plural)

    def test_the_key_need_not_be_a_word(self):
        # It is a merge key, never shown: "cache" and "caches" meet at the
        # stem an "-es" plural cannot see past, rather than guessing a form.
        assert canonical_name("caches") == "cach"
        assert canonical_name("batches") == "batch"

    @pytest.mark.parametrize(
        "word",
        ["postgres", "kubernetes", "redis", "https", "status", "analysis", "access", "docs", "series"],
    )
    def test_words_that_only_look_plural_are_left_alone(self, word):
        assert canonical_name(word) == word

    @pytest.mark.parametrize("word", ["class", "corpus", "thesis"])
    def test_ss_us_is_endings_are_never_stripped(self, word):
        assert canonical_name(word) == word

    @pytest.mark.parametrize("word", ["aws", "ids", "ops"])
    def test_short_words_are_left_alone(self, word):
        assert canonical_name(word) == word

    def test_each_word_of_a_phrase_is_folded(self):
        assert canonical_name("Postgres Replicas") == "postgres replica"

    @pytest.mark.parametrize("name", [None, "", "   ", "!!!", "--_--"])
    def test_a_name_with_nothing_left_is_no_entity(self, name):
        assert canonical_name(name) == ""

    def test_normalize_entity_name_is_the_canonical_key(self):
        assert normalize_entity_name("Vector Stores") == canonical_name("Vector Stores")
