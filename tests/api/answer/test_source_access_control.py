"""``active_docs`` is client input and must be authorization-gated.

The retriever runs ``WHERE source_id = <id>`` with no owner predicate, so an
unchecked id read another tenant's documents straight into the answer while
``/api/sources/<id>/search`` correctly refused the same id.

The gate must not break the three legitimate ways a caller reaches a source
they do not own: a direct team grant, running an agent someone shared with
them, and calling that agent with its API key. The first goes through
``can_access``; the other two resolve from agent config and deliberately never
reach this gate — transitive access *through* a shared agent is a separate
run-time concept (see ``can_access``'s docstring).
"""

from __future__ import annotations

import pytest

import application.api.answer.services.stream_processor as sp_mod

StreamProcessor = sp_mod.StreamProcessor

OWNED = "src-owned"
TEAM_SHARED = "src-team-shared"
FOREIGN = "src-foreign"


@pytest.fixture(autouse=True)
def _stub_db(monkeypatch):
    """``_load_request_sources`` opens a connection; it needn't be a real one."""
    import contextlib
    from unittest.mock import MagicMock

    @contextlib.contextmanager
    def _conn():
        yield MagicMock()

    # Patch the name bound in stream_processor, not the source module: it is
    # imported at module load, so rebinding the origin has no effect.
    monkeypatch.setattr(sp_mod, "db_readonly", _conn)


@pytest.fixture
def access_model(monkeypatch):
    """``can_access`` semantics: own it, or hold a direct team grant."""

    def _can_access(conn, resource_type, resource_id, user_id):
        if user_id == "owner":
            return resource_id in (OWNED, TEAM_SHARED)
        if user_id == "teammate":
            return resource_id == TEAM_SHARED
        return False

    monkeypatch.setattr(sp_mod, "can_access", _can_access)


def _processor(data, user):
    sp = StreamProcessor.__new__(StreamProcessor)
    sp.data = data
    sp.decoded_token = {"sub": user}
    sp.initial_user_id = user
    sp._agent_data = data.get("_agent_data")
    sp.source = {}
    sp.all_sources = []
    return sp


@pytest.mark.unit
class TestRequestSourceAccess:
    def test_owner_reaches_their_own_source(self, access_model):
        sp = _processor({"active_docs": OWNED}, "owner")
        sp._configure_source()
        assert sp.source == {"active_docs": OWNED}

    def test_teammate_reaches_a_team_shared_source(self, access_model):
        """A direct team grant is exactly what ``can_access`` allows."""
        sp = _processor({"active_docs": TEAM_SHARED}, "teammate")
        sp._configure_source()
        assert sp.source == {"active_docs": TEAM_SHARED}

    def test_teammate_cannot_reach_an_unshared_source(self, access_model):
        sp = _processor({"active_docs": OWNED}, "teammate")
        sp._configure_source()
        assert sp.source == {}

    def test_stranger_cannot_reach_anything(self, access_model):
        sp = _processor({"active_docs": FOREIGN}, "stranger")
        sp._configure_source()
        assert sp.source == {}

    def test_list_keeps_only_the_permitted_ids(self, access_model):
        sp = _processor({"active_docs": [TEAM_SHARED, OWNED]}, "teammate")
        sp._configure_source()
        assert sp.source == {"active_docs": [TEAM_SHARED]}

    def test_all_sources_matches_the_permitted_set(self, access_model):
        sp = _processor({"active_docs": [TEAM_SHARED, OWNED]}, "teammate")
        sp._configure_source()
        assert [e["id"] for e in sp.all_sources] == [TEAM_SHARED]


@pytest.mark.unit
class TestSharedAgentAccessIsUnaffected:
    """Agent-resolved sources must keep working for a non-owner.

    Someone running a shared agent, or calling it with its API key, never
    supplied the source id — it comes from the agent's own config, which was
    gated when the owner attached it. Re-gating here against the *caller*
    would break every shared agent that has a source.
    """

    def test_shared_agent_multi_source_survives(self, access_model):
        sp = _processor(
            {
                "_agent_data": {
                    "user_id": "owner",
                    "sources": [{"id": OWNED}, {"id": FOREIGN}],
                }
            },
            "teammate",
        )
        sp._configure_source()
        assert sp.source == {"active_docs": [OWNED, FOREIGN]}
        assert len(sp.all_sources) == 2

    def test_shared_agent_legacy_single_source_survives(self, access_model):
        sp = _processor(
            {"_agent_data": {"user_id": "owner", "source": OWNED}}, "teammate"
        )
        sp._configure_source()
        assert sp.source == {"active_docs": OWNED}

    def test_api_key_caller_reaches_the_agents_source(self, access_model):
        """An API-key call carries no user of its own; the agent owns access."""
        sp = _processor(
            {"_agent_data": {"user_id": "owner", "source": OWNED}}, None
        )
        sp._configure_source()
        assert sp.source == {"active_docs": OWNED}

    def test_agent_default_placeholder_still_means_no_source(self, access_model):
        sp = _processor(
            {"_agent_data": {"user_id": "owner", "source": "default"}}, "teammate"
        )
        sp._configure_source()
        assert sp.source == {}
