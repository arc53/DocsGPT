"""Tests for per-source search exposure partitioning (E1 / D11)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.api.answer.services.stream_processor import StreamProcessor
from application.storage.db.source_config import RetrievalConfig


def _processor() -> StreamProcessor:
    """A bare StreamProcessor with only the fields the exposure helpers touch.

    Built via ``__new__`` to skip the DB-heavy ``__init__``; the exposure
    methods read ``all_sources`` / ``source`` / ``agent_config`` only.
    """
    sp = StreamProcessor.__new__(StreamProcessor)
    sp.all_sources = []
    sp.source = {}
    sp.agent_config = {}
    sp.retriever_config = {"retriever_name": "classic", "chunks": 2, "doc_token_limit": 50000}
    sp.data = {}
    return sp


@pytest.mark.unit
class TestExposurePartition:
    def test_no_config_all_default_to_prefetch(self):
        sp = _processor()
        sp.all_sources = [{"id": "a", "retrieval": None}, {"id": "b", "retrieval": None}]
        prefetch, agentic = sp._exposure_partition()
        assert [e["id"] for e in prefetch] == ["a", "b"]
        assert agentic == []

    def test_mixed_partition(self):
        sp = _processor()
        sp.all_sources = [
            {"id": "a", "retrieval": RetrievalConfig(exposure="prefetch")},
            {"id": "b", "retrieval": RetrievalConfig(exposure="agentic_tool")},
            {"id": "c", "retrieval": RetrievalConfig()},  # default prefetch
        ]
        prefetch, agentic = sp._exposure_partition()
        assert sorted(e["id"] for e in prefetch) == ["a", "c"]
        assert [e["id"] for e in agentic] == ["b"]

    def test_exposure_of_dict_and_model_and_missing(self):
        sp = _processor()
        assert sp._exposure_of(RetrievalConfig(exposure="agentic_tool")) == "agentic_tool"
        assert sp._exposure_of({"exposure": "agentic_tool"}) == "agentic_tool"
        assert sp._exposure_of(None) == "prefetch"
        assert sp._exposure_of({}) == "prefetch"

    def test_source_for_docs(self):
        sp = _processor()
        assert sp._source_for_docs(["a", "b"]) == {"active_docs": ["a", "b"]}
        assert sp._source_for_docs([]) == {}


@pytest.mark.unit
class TestBuildAgentExposure:
    def _agentic_processor(self):
        sp = _processor()
        sp.agent_config = {"agent_type": "agentic"}
        sp.initialize = MagicMock()
        sp.pre_fetch_docs = MagicMock(return_value=("docs_together", ["doc"]))
        sp.pre_fetch_tools = MagicMock(return_value={"tool": {}})
        sp.create_agent = MagicMock(return_value="AGENT")
        return sp

    def test_all_prefetch_is_today_no_partition(self):
        # No agentic_tool source → today's behavior: no pre-fetch, no
        # agentic_sources passed (tool exposes all sources).
        sp = self._agentic_processor()
        sp.all_sources = [
            {"id": "a", "retrieval": RetrievalConfig()},
            {"id": "b", "retrieval": None},
        ]
        result = sp.build_agent("q")
        assert result == "AGENT"
        sp.pre_fetch_docs.assert_not_called()
        _, kwargs = sp.create_agent.call_args
        assert "agentic_sources" not in kwargs

    def test_mixed_prefetches_and_scopes_tool(self):
        sp = self._agentic_processor()
        sp.all_sources = [
            {"id": "a", "retrieval": RetrievalConfig(exposure="prefetch")},
            {"id": "b", "retrieval": RetrievalConfig(exposure="agentic_tool")},
        ]
        sp.build_agent("q")
        # Pre-fetch ran scoped to the prefetch subset.
        sp.pre_fetch_docs.assert_called_once()
        _, pf_kwargs = sp.pre_fetch_docs.call_args
        assert pf_kwargs.get("exposure") == "prefetch"
        # create_agent received only the agentic_tool subset as the tool sources.
        _, kwargs = sp.create_agent.call_args
        assert [e["id"] for e in kwargs["agentic_sources"]] == ["b"]

    def test_classic_agent_ignores_exposure(self):
        # Classic agents pre-fetch all and never partition by exposure.
        sp = _processor()
        sp.agent_config = {"agent_type": "classic"}
        sp.all_sources = [
            {"id": "a", "retrieval": RetrievalConfig(exposure="agentic_tool")},
        ]
        sp.initialize = MagicMock()
        sp.pre_fetch_docs = MagicMock(return_value=("t", ["d"]))
        sp.pre_fetch_tools = MagicMock(return_value=None)
        sp.create_agent = MagicMock(return_value="AGENT")
        sp.build_agent("q")
        # Classic pre-fetch is called with no exposure scoping (all sources).
        sp.pre_fetch_docs.assert_called_once_with("q")
        _, kwargs = sp.create_agent.call_args
        assert "agentic_sources" not in kwargs
