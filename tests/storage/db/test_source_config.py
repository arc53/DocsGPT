"""Tests for SourceConfig parse/validation (lenient read, strict write)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from application.storage.db.source_config import (
    ChunkingConfig,
    GraphConfig,
    PreScreenConfig,
    RetrievalConfig,
    SourceConfig,
)


@pytest.mark.unit
class TestParseLenient:
    def test_parse_empty_dict_is_all_defaults(self):
        cfg = SourceConfig.parse({})
        assert cfg == SourceConfig()
        assert cfg.kind == "classic"
        assert cfg.chunking == ChunkingConfig()
        assert cfg.retrieval == RetrievalConfig()
        assert cfg.graph == GraphConfig()

    def test_parse_none_is_all_defaults(self):
        cfg = SourceConfig.parse(None)
        assert cfg == SourceConfig()

    def test_chunking_defaults_match_worker(self):
        # Byte-identical-ingest guarantee: defaults equal worker MAX/MIN_TOKENS.
        c = ChunkingConfig()
        assert c.strategy == "classic_chunk"
        assert c.max_tokens == 1250
        assert c.min_tokens == 150
        assert c.duplicate_headers is False

    def test_retrieval_defaults(self):
        r = RetrievalConfig()
        assert r.retriever == "classic"
        assert r.exposure == "prefetch"
        assert r.chunks == 2
        assert r.score_threshold is None
        assert r.rephrase_query is True
        assert r.reranker is None
        assert r.prescreen is None

    def test_parse_partial_merges_onto_defaults(self):
        cfg = SourceConfig.parse({"retrieval": {"chunks": 5}})
        assert cfg.retrieval.chunks == 5
        # Untouched fields keep their defaults.
        assert cfg.retrieval.retriever == "classic"
        assert cfg.chunking.max_tokens == 1250

    def test_parse_bad_type_falls_back_to_defaults(self):
        # Lenient read: a non-dict / invalid blob never crashes the caller.
        assert SourceConfig.parse("not-a-dict") == SourceConfig()
        assert SourceConfig.parse({"retrieval": {"chunks": "lots"}}) == SourceConfig()
        assert SourceConfig.parse({"unknown_key": 1}) == SourceConfig()


@pytest.mark.unit
class TestStrictWrite:
    def test_model_validate_rejects_bad_type(self):
        with pytest.raises(ValidationError):
            SourceConfig.model_validate({"retrieval": {"chunks": "lots"}})

    def test_model_validate_rejects_unknown_key(self):
        with pytest.raises(ValidationError):
            SourceConfig.model_validate({"unexpected": True})

    def test_chunks_upper_bound_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(chunks=501)

    def test_chunks_lower_bound_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(chunks=0)

    def test_chunks_accepts_small_and_ceiling_values(self):
        assert RetrievalConfig(chunks=2).chunks == 2
        assert RetrievalConfig(chunks=500).chunks == 500

    def test_model_validate_accepts_full_valid_config(self):
        cfg = SourceConfig.model_validate(
            {
                "kind": "classic",
                "chunking": {
                    "strategy": "classic_chunk",
                    "max_tokens": 800,
                    "min_tokens": 100,
                    "duplicate_headers": True,
                },
                "retrieval": {
                    "retriever": "classic",
                    "exposure": "prefetch",
                    "chunks": 4,
                    "score_threshold": 0.2,
                    "rephrase_query": False,
                },
            }
        )
        assert cfg.chunking.max_tokens == 800
        assert cfg.retrieval.score_threshold == 0.2
        assert cfg.retrieval.rephrase_query is False


@pytest.mark.unit
class TestPreScreenConfig:
    def test_defaults(self):
        ps = PreScreenConfig()
        assert ps.candidate_k == 40
        assert ps.model is None
        assert ps.batch_size == 10
        assert ps.max_keep == 8

    def test_max_keep_must_not_exceed_candidate_k(self):
        with pytest.raises(ValidationError):
            PreScreenConfig(candidate_k=5, max_keep=10)

    def test_bounds_rejected(self):
        with pytest.raises(ValidationError):
            PreScreenConfig(candidate_k=0)
        with pytest.raises(ValidationError):
            PreScreenConfig(batch_size=1000)

    def test_prescreen_default_off(self):
        assert RetrievalConfig().prescreen is None
        assert RetrievalConfig().prescreen_config() is None

    def test_retrieval_validates_prescreen_dict_strictly(self):
        # candidate_k < chunks is rejected on the write path.
        with pytest.raises(ValidationError):
            RetrievalConfig.model_validate(
                {"chunks": 20, "prescreen": {"candidate_k": 5}}
            )

    def test_retrieval_normalises_prescreen(self):
        rc = RetrievalConfig.model_validate(
            {"chunks": 2, "prescreen": {"candidate_k": 30, "max_keep": 4}}
        )
        ps = rc.prescreen_config()
        assert ps.candidate_k == 30
        assert ps.max_keep == 4
        # Defaults filled in.
        assert ps.batch_size == 10

    def test_prescreen_config_lenient_read(self):
        # A garbage stored prescreen blob never crashes the read path.
        rc = RetrievalConfig.model_construct(prescreen={"candidate_k": "x"})
        assert rc.prescreen_config() is None


@pytest.mark.unit
class TestGraphConfig:
    def test_defaults(self):
        g = GraphConfig()
        assert g.extraction_model is None
        assert g.max_chunks is None
        assert g.gleanings == 0

    def test_parse_graph_block_round_trips(self):
        raw = {
            "kind": "graphrag",
            "graph": {
                "extraction_model": "gpt-4o-mini",
                "max_chunks": 500,
                "gleanings": 1,
            },
        }
        cfg = SourceConfig.parse(raw)
        assert cfg.kind == "graphrag"
        assert cfg.graph.extraction_model == "gpt-4o-mini"
        assert cfg.graph.max_chunks == 500
        assert cfg.graph.gleanings == 1
        dumped = cfg.model_dump()
        assert SourceConfig.model_validate(dumped) == cfg
        assert dumped["graph"] == {
            "extraction_model": "gpt-4o-mini",
            "max_chunks": 500,
            "gleanings": 1,
        }

    def test_forbid_unknown_graph_key(self):
        with pytest.raises(ValidationError):
            SourceConfig.model_validate({"graph": {"unknown": 1}})
        with pytest.raises(ValidationError):
            GraphConfig(unknown=1)

    def test_negative_values_rejected(self):
        with pytest.raises(ValidationError):
            GraphConfig(gleanings=-1)
        with pytest.raises(ValidationError):
            GraphConfig(max_chunks=0)

    def test_parse_lenient_on_garbage_graph(self):
        # A non-dict / invalid graph blob falls back to all-defaults on read.
        assert SourceConfig.parse({"graph": "nope"}) == SourceConfig()
        assert SourceConfig.parse({"graph": {"gleanings": "lots"}}) == SourceConfig()
        # Missing graph block still yields the default GraphConfig.
        cfg = SourceConfig.parse({"kind": "graphrag"})
        assert cfg.graph == GraphConfig()
