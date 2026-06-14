"""Tests for agent YAML export/import (application.api.user.agents.portability).

These exercise real SQL against the ephemeral ``pg_conn`` fixture, calling
the dependency-injected serialize/plan/apply functions directly so the
logic is covered without a running Flask app.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from application.agents.default_tools import default_tool_id
from application.api.user.agents.portability import (
    API_VERSION,
    AgentImportError,
    agent_to_yaml,
    apply_import,
    ensure_agent_slug,
    parse_agent_yaml,
    plan_import,
    serialize_agent,
)
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.prompts import PromptsRepository
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.user_tools import UserToolsRepository


pytestmark = pytest.mark.integration


def _make_agent(conn, user, **kwargs):
    defaults = dict(description="d", chunks=2, retriever="classic")
    defaults.update(kwargs)
    return AgentsRepository(conn).create(user, kwargs.pop("name", "Bot"), "published", **defaults)


def _doc(**spec):
    spec.setdefault("name", "Imported")
    return {
        "apiVersion": API_VERSION,
        "kind": "Agent",
        "metadata": {"slug": spec.pop("_slug", "imported")},
        "spec": spec,
    }


def test_serialize_redacts_tool_secret(pg_conn):
    user = "u_redact"
    src = SourcesRepository(pg_conn).create("Docs", user_id=user, type="file")
    prompt = PromptsRepository(pg_conn).create(user, "P", "You are helpful")
    tool = UserToolsRepository(pg_conn).create(
        user,
        "brave",
        config={"encrypted_credentials": "SECRETBLOB", "region": "US"},
        custom_name="My Brave",
        display_name="Brave Search",
        description="search",
        config_requirements={"token": {"secret": True, "required": True}, "region": {}},
        actions=[],
    )
    agent = AgentsRepository(pg_conn).create(
        user,
        "Support Bot",
        "published",
        description="help desk",
        chunks=3,
        retriever="classic",
        prompt_id=str(prompt["id"]),
        source_id=str(src["id"]),
        tools=[str(tool["id"])],
    )

    export = serialize_agent(pg_conn, agent, user)
    text = agent_to_yaml(export)

    assert "SECRETBLOB" not in text
    assert "encrypted_credentials" not in text
    tool_entry = export["spec"]["tools"][0]
    assert tool_entry["type"] == "brave"
    assert tool_entry["requires_secrets"] == ["token"]
    assert "encrypted_credentials" not in tool_entry["config"]
    assert tool_entry["config"] == {"region": "US"}
    assert export["spec"]["prompt"] == {"name": "P", "content": "You are helpful"}
    assert export["spec"]["sources"][0]["name"] == "Docs"


def test_export_assigns_unique_slug(pg_conn):
    user = "u_slug"
    a1 = AgentsRepository(pg_conn).create(user, "My Bot", "draft")
    a2 = AgentsRepository(pg_conn).create(user, "My Bot", "draft")

    s1 = ensure_agent_slug(pg_conn, a1, user)
    a2_reload = AgentsRepository(pg_conn).get(str(a2["id"]), user)
    s2 = ensure_agent_slug(pg_conn, a2_reload, user)

    assert s1 == "my-bot"
    assert s2 == "my-bot-2"


def test_round_trip_same_user_idempotent(pg_conn):
    user = "u_round"
    src = SourcesRepository(pg_conn).create("KB", user_id=user, type="file")
    prompt = PromptsRepository(pg_conn).create(user, "Sys", "Be nice")
    scheduler_id = default_tool_id("scheduler")
    agent = AgentsRepository(pg_conn).create(
        user,
        "Bot",
        "published",
        description="d",
        chunks=2,
        retriever="classic",
        prompt_id=str(prompt["id"]),
        source_id=str(src["id"]),
        tools=[scheduler_id],
    )
    ensure_agent_slug(pg_conn, agent, user)
    agent = AgentsRepository(pg_conn).get(str(agent["id"]), user)

    doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, agent, user)))
    r1 = apply_import(pg_conn, user, doc)
    r2 = apply_import(pg_conn, user, doc)

    assert r1["agent_id"] == r2["agent_id"] == str(agent["id"])  # matched by id
    assert len(PromptsRepository(pg_conn).list_for_user(user)) == 1  # no dup prompt
    imported = AgentsRepository(pg_conn).get(r1["agent_id"], user)
    assert imported["status"] == "published"  # update preserves the live status
    assert [str(s) for s in imported["extra_source_ids"]] == [str(src["id"])]
    assert imported["tools"] == [scheduler_id]  # builtin passthrough


def test_update_preserves_published_status(pg_conn):
    """Re-importing over a published agent must not revert it to draft.

    The agent's API key and any active users keep working; only the content
    is synced. A new agent (no match) still lands as a draft.
    """
    user = "u_pub"
    agent = AgentsRepository(pg_conn).create(
        user,
        "Live Bot",
        "published",
        description="old",
        chunks=2,
        retriever="classic",
    )
    slug = ensure_agent_slug(pg_conn, agent, user)
    doc = {
        "apiVersion": API_VERSION,
        "kind": "Agent",
        "metadata": {"id": str(agent["id"]), "slug": slug},
        "spec": {"name": "Live Bot", "description": "new", "retriever": "classic"},
    }

    result = apply_import(pg_conn, user, doc)

    assert result["action"] == "updated"
    assert result["status"] == "published"  # response reports the preserved status
    updated = AgentsRepository(pg_conn).get(str(agent["id"]), user)
    assert updated["status"] == "published"  # stayed live
    assert updated["description"] == "new"  # content still synced


def test_import_by_slug_idempotent(pg_conn):
    user = "u_slug_import"
    doc = _doc(name="Slug Bot", _slug="slug-bot", retriever="classic")

    r1 = apply_import(pg_conn, user, doc)
    r2 = apply_import(pg_conn, user, doc)

    assert r1["action"] == "created"
    assert r2["action"] == "updated"
    assert r1["agent_id"] == r2["agent_id"]
    assert len(AgentsRepository(pg_conn).list_for_user(user)) == 1


def test_import_missing_source_drafts_and_warns(pg_conn):
    user = "u_missing"
    doc = _doc(
        name="No Source Bot",
        _slug="no-source",
        sources=[{"name": "Nonexistent KB", "type": "file"}],
    )

    result = apply_import(pg_conn, user, doc)

    assert result["status"] == "draft"  # new agents are created as drafts
    assert any("Nonexistent KB" in w for w in result["warnings"])
    agent = AgentsRepository(pg_conn).get(result["agent_id"], user)
    assert agent["status"] == "draft"
    assert list(agent["extra_source_ids"]) == []


def test_import_matches_existing_source_by_name(pg_conn):
    user = "u_match"
    src = SourcesRepository(pg_conn).create("Product Docs", user_id=user, type="file")
    doc = _doc(
        name="Matcher",
        _slug="matcher",
        sources=[{"name": "product docs", "type": "file"}],  # case-insensitive
    )

    result = apply_import(pg_conn, user, doc)

    agent = AgentsRepository(pg_conn).get(result["agent_id"], user)
    assert [str(s) for s in agent["extra_source_ids"]] == [str(src["id"])]
    assert result["warnings"] == []


def test_plan_classifies_references(pg_conn):
    user = "u_plan"
    SourcesRepository(pg_conn).create("Known", user_id=user, type="file")
    tool = UserToolsRepository(pg_conn).create(
        user, "brave", custom_name="My Brave", display_name="Brave", config={},
    )
    doc = _doc(
        name="Plan Bot",
        sources=[{"name": "Known"}, {"name": "Unknown"}],
        tools=[
            {"type": "scheduler", "builtin": True},
            {"type": "brave", "name": "My Brave"},
        ],
    )

    plan = plan_import(pg_conn, user, doc)

    statuses = {s["name"]: s["status"] for s in plan["sources"]}
    assert statuses == {"Known": "matched", "Unknown": "missing"}
    tool_statuses = [t["status"] for t in plan["tools"]]
    assert tool_statuses[0] == "builtin"
    assert tool_statuses[1] == "reuse"
    assert plan["tools"][1]["target_id"] == str(tool["id"])
    assert plan["target"]["action"] == "create"


def test_apply_creates_tool_with_supplied_secret(pg_conn, monkeypatch):
    user = "u_tool"
    fake_tool = Mock()
    fake_tool.get_config_requirements.return_value = {
        "api_key": {"secret": True, "required": True, "label": "API Key"}
    }
    fake_tool.get_actions_metadata.return_value = []
    monkeypatch.setattr(
        "application.api.user.agents.portability._tool_instance",
        lambda tool_type: fake_tool,
    )
    doc = _doc(
        name="Tool Bot",
        _slug="tool-bot",
        tools=[
            {
                "type": "brave",
                "name": "My API",
                "config": {},
                "requires_secrets": ["api_key"],
            }
        ],
    )

    # No secret supplied -> tool skipped, agent still created.
    res = apply_import(pg_conn, user, doc)
    agent = AgentsRepository(pg_conn).get(res["agent_id"], user)
    assert agent["tools"] == []
    assert any("api_key" in w for w in res["warnings"])

    # Secret supplied via resolution -> tool created and linked, secret encrypted.
    res2 = apply_import(
        pg_conn,
        user,
        doc,
        resolution={"tools": {"tool-0": {"secrets": {"api_key": "PLAINTEXT_KEY"}}}},
    )
    agent2 = AgentsRepository(pg_conn).get(res2["agent_id"], user)
    assert len(agent2["tools"]) == 1
    tool_row = UserToolsRepository(pg_conn).get_any(agent2["tools"][0], user)
    assert "PLAINTEXT_KEY" not in str(tool_row["config"])
    assert "encrypted_credentials" in tool_row["config"]


def test_parse_rejects_bad_documents():
    with pytest.raises(AgentImportError):
        parse_agent_yaml("kind: NotAgent\napiVersion: docsgpt.arc53.com/v1\nspec:\n  name: x\n")
    with pytest.raises(AgentImportError):
        parse_agent_yaml("kind: Agent\napiVersion: other/v1\nspec:\n  name: x\n")
    with pytest.raises(AgentImportError):
        parse_agent_yaml("kind: Agent\napiVersion: docsgpt.arc53.com/v1\nspec: {}\n")
    with pytest.raises(AgentImportError):
        parse_agent_yaml(
            "kind: Agent\napiVersion: docsgpt.arc53.com/v1\n"
            "spec:\n  name: x\n  agent_type: workflow\n"
        )


def test_parse_rejects_yaml_aliases():
    bomb = (
        "kind: Agent\napiVersion: docsgpt.arc53.com/v1\n"
        "spec:\n  name: &a x\n  description: *a\n"
    )
    with pytest.raises(AgentImportError):
        parse_agent_yaml(bomb)


def test_update_clears_removed_json_schema(pg_conn):
    """On update the YAML is authoritative — removing json_schema clears it."""
    user = "u_clear"
    agent = AgentsRepository(pg_conn).create(
        user,
        "Clear Bot",
        "published",
        description="d",
        chunks=2,
        retriever="classic",
        json_schema={"type": "object"},
    )
    slug = ensure_agent_slug(pg_conn, agent, user)
    doc = {
        "apiVersion": API_VERSION,
        "kind": "Agent",
        "metadata": {"slug": slug},
        "spec": {"name": "Clear Bot", "retriever": "classic", "json_schema": None},
    }

    result = apply_import(pg_conn, user, doc)

    assert result["action"] == "updated"
    updated = AgentsRepository(pg_conn).get(str(agent["id"]), user)
    assert updated["json_schema"] is None


def test_custom_tool_dedup_across_reimport(pg_conn):
    user = "u_dedup"
    tool = UserToolsRepository(pg_conn).create(
        user, "brave", custom_name="My Brave", display_name="Brave", config={},
    )
    agent = AgentsRepository(pg_conn).create(
        user,
        "Dedup Bot",
        "published",
        description="d",
        chunks=2,
        retriever="classic",
        tools=[str(tool["id"])],
    )
    ensure_agent_slug(pg_conn, agent, user)
    agent = AgentsRepository(pg_conn).get(str(agent["id"]), user)
    doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, agent, user)))

    apply_import(pg_conn, user, doc)
    apply_import(pg_conn, user, doc)

    assert len(UserToolsRepository(pg_conn).list_for_user(user)) == 1  # reused, never duplicated
    final = AgentsRepository(pg_conn).get(str(agent["id"]), user)
    assert final["tools"] == [str(tool["id"])]


def test_import_rejects_ssrf_tool_url(pg_conn, monkeypatch):
    user = "u_ssrf"
    fake_tool = Mock()
    fake_tool.get_config_requirements.return_value = {}
    fake_tool.get_actions_metadata.return_value = []
    monkeypatch.setattr(
        "application.api.user.agents.portability._tool_instance",
        lambda tool_type: fake_tool,
    )
    doc = _doc(
        name="SSRF Bot",
        _slug="ssrf",
        tools=[
            {
                "type": "mcp_tool",
                "name": "evil",
                "config": {"server_url": "http://169.254.169.254/latest/meta-data"},
            }
        ],
    )

    result = apply_import(pg_conn, user, doc)

    agent = AgentsRepository(pg_conn).get(result["agent_id"], user)
    assert agent["tools"] == []
    assert any("unsafe" in w.lower() for w in result["warnings"])


def test_import_rejects_unowned_source_mapping(pg_conn):
    owner, attacker = "u_owner", "u_attacker"
    src = SourcesRepository(pg_conn).create("Secret KB", user_id=owner, type="file")
    doc = _doc(name="IDOR Bot", _slug="idor", sources=[{"name": "Their Source"}])

    # Attacker maps the missing source to the owner's source id.
    result = apply_import(
        pg_conn, attacker, doc, resolution={"sources": {"Their Source": str(src["id"])}}
    )

    agent = AgentsRepository(pg_conn).get(result["agent_id"], attacker)
    assert list(agent["extra_source_ids"]) == []  # not linked
    assert any("not yours" in w for w in result["warnings"])


def test_apply_tolerates_plan_shaped_resolution(pg_conn):
    """Echoing the plan's list-shaped resolution back must not crash apply."""
    user = "u_shape"
    doc = _doc(name="Shape Bot", _slug="shape", sources=[{"name": "X"}])

    result = apply_import(
        pg_conn, user, doc, resolution={"sources": [], "tools": [], "models": []}
    )

    assert result["action"] == "created"


def test_update_clears_models_and_resets_prompt(pg_conn):
    """A re-imported file that drops models and prompt clears them on update."""
    user = "u_clear2"
    prompt = PromptsRepository(pg_conn).create(user, "Sys", "Be terse")
    agent = AgentsRepository(pg_conn).create(
        user,
        "Model Bot",
        "published",
        description="d",
        chunks=2,
        retriever="classic",
        prompt_id=str(prompt["id"]),
        models=["gpt-4o"],
        default_model_id="gpt-4o",
    )
    slug = ensure_agent_slug(pg_conn, agent, user)
    doc = {
        "apiVersion": API_VERSION,
        "kind": "Agent",
        "metadata": {"slug": slug},
        "spec": {
            "name": "Model Bot",
            "retriever": "classic",
            "prompt": "default",
            "model": {"default": "", "available": []},
        },
    }

    apply_import(pg_conn, user, doc)

    updated = AgentsRepository(pg_conn).get(str(agent["id"]), user)
    assert not updated["models"]
    assert not updated["default_model_id"]
    assert updated["prompt_id"] is None  # reset to default


def test_tool_skipped_when_encryption_fails(pg_conn, monkeypatch):
    user = "u_encfail"
    fake_tool = Mock()
    fake_tool.get_config_requirements.return_value = {
        "api_key": {"secret": True, "required": True}
    }
    fake_tool.get_actions_metadata.return_value = []
    monkeypatch.setattr(
        "application.api.user.agents.portability._tool_instance",
        lambda tool_type: fake_tool,
    )
    # Force credential encryption to fail (returns "").
    monkeypatch.setattr(
        "application.api.user.tools.routes.encrypt_credentials",
        lambda creds, user_id: "",
    )
    doc = _doc(
        name="EncFail Bot",
        _slug="encfail",
        tools=[{"type": "brave", "name": "X", "config": {}, "requires_secrets": ["api_key"]}],
    )

    result = apply_import(
        pg_conn,
        user,
        doc,
        resolution={"tools": {"tool-0": {"secrets": {"api_key": "K"}}}},
    )

    agent = AgentsRepository(pg_conn).get(result["agent_id"], user)
    assert agent["tools"] == []
    assert any("encryption failed" in w for w in result["warnings"])
