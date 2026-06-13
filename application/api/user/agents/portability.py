"""Agent YAML export / import.

Agents are mostly references (sources, tools, prompt, models). Export
translates those into portable identifiers and never emits a secret;
import resolves them back against the importing user — matching existing
resources or creating them from the file plus user-supplied tokens.

Re-import is idempotent at every level: the agent is matched by
``metadata.id`` then ``metadata.slug``, tools by ``(type, name)``,
prompts by ``(name, content)``, custom models by
``(display_name, upstream_model_id, base_url)`` — so the same file
applied twice updates rather than duplicating.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import yaml
from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource

from application.agents.default_tools import (
    default_tool_id,
    is_synthesized_tool_id,
    synthesize_tool_by_name,
    synthesized_tool_name_for_id,
)
from application.api import api
from application.core.model_utils import validate_model_id
from application.core.url_validation import SSRFError, validate_url
from application.security.safe_url import UnsafeUserUrlError, validate_user_base_url
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.prompts import PromptsRepository
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.user_custom_models import (
    UserCustomModelsRepository,
)
from application.storage.db.repositories.user_tools import UserToolsRepository
from application.storage.db.session import db_readonly, db_session


API_VERSION = "docsgpt.arc53.com/v1"
KIND = "Agent"

# Import safety bounds (DoS): cap the document size and the number of
# child resources a single import may reference / create.
MAX_IMPORT_BYTES = 512 * 1024
MAX_LIST_ITEMS = 100


class AgentImportError(Exception):
    """Raised when an agent YAML document is malformed or unsupported."""


class _SafeNoAliasLoader(yaml.SafeLoader):
    """SafeLoader that also rejects anchors/aliases (billion-laughs guard)."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.events.AliasEvent):
            raise AgentImportError("YAML anchors/aliases are not allowed")
        return super().compose_node(parent, index)


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------


def slugify(name: Optional[str]) -> str:
    """Turn an agent name into a url-safe slug; never empty."""
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "agent"


def _unique_slug(
    repo: AgentsRepository,
    user: str,
    base: str,
    *,
    exclude_id: Optional[str] = None,
) -> str:
    """Return ``base`` (slugified) or the first ``-N`` variant free for ``user``."""
    base = slugify(base)
    candidate = base
    n = 2
    while True:
        found = repo.find_by_slug(user, candidate)
        if found is None or (exclude_id and str(found["id"]) == str(exclude_id)):
            return candidate
        candidate = f"{base}-{n}"
        n += 1


def ensure_agent_slug(conn, agent: dict, user: str) -> str:
    """Return the agent's slug, lazily assigning and persisting one if absent."""
    existing = agent.get("slug")
    if existing:
        return str(existing)
    repo = AgentsRepository(conn)
    slug = _unique_slug(repo, user, agent.get("name"), exclude_id=str(agent["id"]))
    repo.update(str(agent["id"]), user, {"slug": slug})
    return slug


# ---------------------------------------------------------------------------
# Tool-manager access (lazy — avoids importing the tool registry at module load)
# ---------------------------------------------------------------------------


def _tool_manager():
    from application.api.user.tools.routes import tool_manager

    return tool_manager


def _tool_instance(tool_type: str):
    return _tool_manager().tools.get(tool_type)


def _secret_field_names(config_requirements: dict, *, required_only: bool = False) -> list:
    out = []
    for key, spec in (config_requirements or {}).items():
        if not isinstance(spec, dict) or not spec.get("secret"):
            continue
        if required_only and not spec.get("required"):
            continue
        out.append(key)
    return out


def _live_requires_secrets(tool_type: str) -> list:
    inst = _tool_instance(tool_type)
    if inst is None:
        return []
    return _secret_field_names(inst.get_config_requirements() or {})


def _safe_export_config(stored_config: dict, config_requirements: dict) -> dict:
    """Return only config values provably non-secret (allowlist).

    Export must never leak a credential. A key is emitted ONLY if
    ``config_requirements`` declares it and does not mark it secret.
    Anything not described by requirements — e.g. ``api_tool``/MCP free-form
    ``headers``, ``url`` query strings, ``server_url`` that routinely embed
    tokens, or tools with empty ``config_requirements`` — is dropped. Reuse
    on import matches the existing tool; create re-collects config from the
    user. This blocklist-free approach can't be defeated by a stale or empty
    ``config_requirements``.
    """
    requirements = config_requirements or {}
    safe: dict[str, Any] = {}
    for key, value in (stored_config or {}).items():
        spec = requirements.get(key)
        if isinstance(spec, dict) and not spec.get("secret"):
            safe[key] = value
    return safe


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _serialize_prompt(conn, agent: dict, user: str):
    prompt_id = agent.get("prompt_id")
    if not prompt_id:
        return "default"
    row = PromptsRepository(conn).get(str(prompt_id), user)
    if not row:
        return "default"
    return {"name": row.get("name") or "", "content": row.get("content") or ""}


def _serialize_sources(conn, agent: dict, user: str) -> list:
    ids: list[str] = []
    if agent.get("source_id"):
        ids.append(str(agent["source_id"]))
    for sid in agent.get("extra_source_ids") or []:
        s = str(sid)
        if s and s not in ids:
            ids.append(s)
    repo = SourcesRepository(conn)
    out = []
    for sid in ids:
        row = repo.get(sid, user)
        if not row:
            continue
        out.append(
            {
                "name": row.get("name") or "",
                "type": row.get("type") or "",
                "ref": sid,
            }
        )
    return out


def _serialize_tools(conn, agent: dict, user: str) -> list:
    repo = UserToolsRepository(conn)
    out = []
    for tid in agent.get("tools") or []:
        tid_str = str(tid)
        if is_synthesized_tool_id(tid_str):
            out.append({"type": synthesized_tool_name_for_id(tid_str), "builtin": True})
            continue
        row = repo.get_any(tid_str, user)
        if not row:
            continue
        requirements = row.get("config_requirements") or {}
        requires_secrets = _secret_field_names(requirements)
        entry: dict[str, Any] = {
            "type": row.get("name") or "",
            # Raw custom_name (may be "") so import matching is symmetric and
            # idempotent — see _find_user_tool.
            "name": row.get("custom_name") or "",
            "display_name": row.get("display_name") or "",
            "description": row.get("description") or "",
            "config": _safe_export_config(row.get("config") or {}, requirements),
            "ref": tid_str,
        }
        if requires_secrets:
            entry["requires_secrets"] = requires_secrets
        out.append(entry)
    return out


def _serialize_models(conn, agent: dict, user: str) -> dict:
    repo = UserCustomModelsRepository(conn)

    def describe(model_id: str):
        mid = str(model_id)
        if looks_like_uuid(mid):
            row = repo.get(mid, user)
            if not row:
                return None
            return {
                "type": "custom",
                "display_name": row.get("display_name") or "",
                "upstream_model_id": row.get("upstream_model_id") or "",
                "base_url": row.get("base_url") or "",
                "capabilities": row.get("capabilities") or {},
                "requires_secrets": ["api_key"],
                "ref": mid,
            }
        return mid

    available = []
    for m in agent.get("models") or []:
        described = describe(m)
        if described is not None:
            available.append(described)

    default_value = ""
    raw_default = agent.get("default_model_id") or ""
    if raw_default:
        described = describe(raw_default)
        if isinstance(described, dict):
            default_value = described["display_name"]
        elif isinstance(described, str):
            default_value = described
    return {"default": default_value, "available": available}


def serialize_agent(conn, agent: dict, user: str) -> dict:
    """Build the portable export document for an agent row."""
    spec = {
        "name": agent.get("name") or "",
        "description": agent.get("description") or "",
        "agent_type": agent.get("agent_type") or "classic",
        "retriever": agent.get("retriever") or "classic",
        "chunks": int(agent["chunks"]) if agent.get("chunks") is not None else None,
        "prompt": _serialize_prompt(conn, agent, user),
        "model": _serialize_models(conn, agent, user),
        "sources": _serialize_sources(conn, agent, user),
        "tools": _serialize_tools(conn, agent, user),
        "limits": {
            "limited_token_mode": bool(agent.get("limited_token_mode", False)),
            "token_limit": agent.get("token_limit"),
            "limited_request_mode": bool(agent.get("limited_request_mode", False)),
            "request_limit": agent.get("request_limit"),
        },
        "json_schema": agent.get("json_schema"),
        "allow_system_prompt_override": bool(agent.get("allow_system_prompt_override", False)),
    }
    return {
        "apiVersion": API_VERSION,
        "kind": KIND,
        "metadata": {"id": str(agent["id"]), "slug": agent.get("slug") or ""},
        "spec": spec,
    }


class _AgentYamlDumper(yaml.SafeDumper):
    """SafeDumper that renders multi-line strings as block scalars."""


def _str_representer(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_AgentYamlDumper.add_representer(str, _str_representer)


def agent_to_yaml(export: dict) -> str:
    """Serialize an export document to YAML, preserving key order."""
    return yaml.dump(
        export,
        Dumper=_AgentYamlDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def parse_agent_yaml(text: str) -> dict:
    """Parse and shallow-validate an agent YAML document."""
    if text and len(text) > MAX_IMPORT_BYTES:
        raise AgentImportError("Import document too large")
    try:
        doc = yaml.load(text, Loader=_SafeNoAliasLoader)
    except yaml.YAMLError as exc:
        raise AgentImportError(f"Invalid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise AgentImportError("Top-level YAML must be a mapping")
    if doc.get("kind") != KIND:
        raise AgentImportError(f"Unsupported kind {doc.get('kind')!r}; expected {KIND!r}")
    if not str(doc.get("apiVersion") or "").startswith("docsgpt."):
        raise AgentImportError(f"Unsupported apiVersion {doc.get('apiVersion')!r}")
    spec = doc.get("spec")
    if not isinstance(spec, dict):
        raise AgentImportError("Missing or invalid 'spec'")
    if not spec.get("name"):
        raise AgentImportError("spec.name is required")
    if spec.get("agent_type") == "workflow":
        raise AgentImportError("Workflow agents are not supported for import yet")
    for key in ("sources", "tools"):
        value = spec.get(key)
        if isinstance(value, list) and len(value) > MAX_LIST_ITEMS:
            raise AgentImportError(f"Too many {key} (max {MAX_LIST_ITEMS})")
    available = (spec.get("model") or {}).get("available")
    if isinstance(available, list) and len(available) > MAX_LIST_ITEMS:
        raise AgentImportError(f"Too many models (max {MAX_LIST_ITEMS})")
    return doc


# ---------------------------------------------------------------------------
# Reference resolution (shared by plan + apply)
# ---------------------------------------------------------------------------


def _resolve_target(conn, user: str, metadata: dict) -> dict:
    repo = AgentsRepository(conn)
    metadata = metadata or {}
    agent_id = metadata.get("id")
    if agent_id and looks_like_uuid(str(agent_id)):
        row = repo.get(str(agent_id), user)
        if row:
            return {"action": "update", "agent_id": str(row["id"]), "matched_by": "id"}
    slug = metadata.get("slug")
    if slug:
        row = repo.find_by_slug(user, str(slug))
        if row:
            return {"action": "update", "agent_id": str(row["id"]), "matched_by": "slug"}
    return {"action": "create", "agent_id": None, "matched_by": None}


def _find_user_tool(user_tools: list, tool_type: str, custom_name: str):
    """Match a stored tool by ``(type, custom_name)`` for idempotent reuse.

    Compares against the stored ``custom_name`` directly (export emits the
    raw value), so a named tool matches exactly and an unnamed one (``""``)
    reuses the first same-type tool rather than spawning a duplicate.
    """
    target = custom_name or ""
    for row in user_tools:
        if (row.get("name") or "") != tool_type:
            continue
        if (row.get("custom_name") or "") == target:
            return row
    return None


def _find_custom_model(customs: list, spec_model: dict):
    for row in customs:
        if (
            (row.get("display_name") or "") == (spec_model.get("display_name") or "")
            and (row.get("upstream_model_id") or "") == (spec_model.get("upstream_model_id") or "")
            and (row.get("base_url") or "") == (spec_model.get("base_url") or "")
        ):
            return row
    return None


def _tool_key(index: int) -> str:
    return f"tool-{index}"


# ---------------------------------------------------------------------------
# Plan (dry run)
# ---------------------------------------------------------------------------


def plan_import(conn, user: str, doc: dict) -> dict:
    """Resolve every reference without writing; returns a resolution report."""
    spec = doc["spec"]
    target = _resolve_target(conn, user, doc.get("metadata") or {})

    sources_repo = SourcesRepository(conn)
    sources = []
    for src in spec.get("sources") or []:
        name = src.get("name") or ""
        match = sources_repo.find_by_name(user, name)
        sources.append(
            {
                "name": name,
                "type": src.get("type") or "",
                "status": "matched" if match else "missing",
                "target_id": str(match["id"]) if match else None,
            }
        )

    user_tools = UserToolsRepository(conn).list_for_user(user)
    tools = []
    for index, tool in enumerate(spec.get("tools") or []):
        tool_type = tool.get("type") or ""
        if tool.get("builtin"):
            available = synthesize_tool_by_name(tool_type) is not None
            tools.append(
                {
                    "key": _tool_key(index),
                    "type": tool_type,
                    "builtin": True,
                    "status": "builtin" if available else "unavailable",
                    "target_id": default_tool_id(tool_type) if available else None,
                }
            )
            continue
        custom_name = tool.get("name") or ""
        match = _find_user_tool(user_tools, tool_type, custom_name)
        if match:
            tools.append(
                {
                    "key": _tool_key(index),
                    "type": tool_type,
                    "name": custom_name,
                    "status": "reuse",
                    "target_id": str(match["id"]),
                }
            )
            continue
        available = _tool_instance(tool_type) is not None
        tools.append(
            {
                "key": _tool_key(index),
                "type": tool_type,
                "name": custom_name,
                "status": "create" if available else "unavailable",
                "requires_secrets": tool.get("requires_secrets") or _live_requires_secrets(tool_type),
            }
        )

    prompt_spec = spec.get("prompt")
    if isinstance(prompt_spec, dict):
        existing = PromptsRepository(conn).find(
            user, prompt_spec.get("name") or "", prompt_spec.get("content") or ""
        )
        prompt = {"status": "reuse" if existing else "create", "name": prompt_spec.get("name") or ""}
    else:
        prompt = {"status": "default"}

    customs = UserCustomModelsRepository(conn).list_for_user(user)
    models = []
    for entry in (spec.get("model") or {}).get("available") or []:
        if isinstance(entry, str):
            models.append(
                {
                    "id": entry,
                    "status": "matched" if validate_model_id(entry, user) else "unavailable",
                }
            )
        elif isinstance(entry, dict):
            match = _find_custom_model(customs, entry)
            models.append(
                {
                    "display_name": entry.get("display_name") or "",
                    "status": "reuse" if match else "create",
                    "requires_secrets": ["api_key"] if not match else [],
                }
            )

    return {"target": target, "sources": sources, "tools": tools, "prompt": prompt, "models": models}


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def _apply_prompt(conn, user: str, spec: dict) -> Optional[str]:
    prompt_spec = spec.get("prompt")
    if not isinstance(prompt_spec, dict):
        return None
    row = PromptsRepository(conn).find_or_create(
        user, prompt_spec.get("name") or "Imported prompt", prompt_spec.get("content") or ""
    )
    return str(row["id"])


def _apply_sources(conn, user: str, spec: dict, resolution: dict, warnings: list) -> list:
    repo = SourcesRepository(conn)
    mapping = resolution.get("sources")
    if not isinstance(mapping, dict):
        mapping = {}
    resolved: list[str] = []
    for src in spec.get("sources") or []:
        name = src.get("name") or ""
        mapped = mapping.get(name)
        if mapped:
            # Ownership-check the client-supplied id before linking (IDOR guard).
            owned = repo.get_any(str(mapped), user)
            if owned:
                resolved.append(str(owned["id"]))
            else:
                warnings.append(f"Source mapping for '{name}' is not yours; ignored")
            continue
        match = repo.find_by_name(user, name)
        if match:
            resolved.append(str(match["id"]))
        else:
            warnings.append(f"Source '{name}' not found; left unattached")
    seen: set = set()
    out = []
    for sid in resolved:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _validate_tool_urls(tool_type: str, config: dict) -> Optional[str]:
    """SSRF-guard imported tool config to parity with the create routes.

    Returns an error message if a URL is unsafe, else None.
    """
    try:
        if tool_type == "mcp_tool":
            server_url = (config.get("server_url") or "").strip()
            if server_url:
                validate_url(server_url)
        elif tool_type == "api_tool":
            url = (config.get("url") or "").strip()
            if url:
                validate_url(url)
    except SSRFError:
        return f"Tool '{tool_type}' has an unsafe URL; not created"
    return None


def _create_tool_from_spec(conn, user: str, tool: dict, secrets: dict, warnings: list) -> Optional[str]:
    from application.api.user.tools.routes import _encrypt_secret_fields, transform_actions

    tool_type = tool.get("type") or ""
    inst = _tool_instance(tool_type)
    if inst is None:
        warnings.append(f"Tool type '{tool_type}' not available on this instance; skipped")
        return None
    config_requirements = inst.get_config_requirements() or {}
    config = dict(tool.get("config") or {})
    config.update(secrets or {})
    missing = [k for k in _secret_field_names(config_requirements, required_only=True) if not config.get(k)]
    if missing:
        warnings.append(f"Tool '{tool_type}' needs secret(s) {missing}; not created")
        return None
    url_error = _validate_tool_urls(tool_type, config)
    if url_error:
        warnings.append(url_error)
        return None
    provided_secrets = [k for k in _secret_field_names(config_requirements) if config.get(k)]
    storage_config = _encrypt_secret_fields(config, config_requirements, user)
    if provided_secrets and not storage_config.get("encrypted_credentials"):
        warnings.append(f"Tool '{tool_type}' secret encryption failed; not created")
        return None
    actions = transform_actions(inst.get_actions_metadata() or [])
    created = UserToolsRepository(conn).create(
        user,
        tool_type,
        config=storage_config,
        custom_name=tool.get("name") or "",
        display_name=tool.get("display_name") or tool_type,
        description=tool.get("description") or "",
        config_requirements=config_requirements,
        actions=actions,
        status=True,
    )
    return str(created["id"])


def _apply_tools(conn, user: str, spec: dict, resolution: dict, warnings: list) -> list:
    repo = UserToolsRepository(conn)
    user_tools = repo.list_for_user(user)
    decisions = resolution.get("tools")
    if not isinstance(decisions, dict):
        decisions = {}
    out: list[str] = []
    for index, tool in enumerate(spec.get("tools") or []):
        tool_type = tool.get("type") or ""
        decision = decisions.get(_tool_key(index))
        if not isinstance(decision, dict):
            decision = {}
        choice = decision.get("decision")

        if tool.get("builtin"):
            if synthesize_tool_by_name(tool_type) is None:
                warnings.append(f"Built-in tool '{tool_type}' unavailable; skipped")
                continue
            out.append(default_tool_id(tool_type))
            continue

        if choice == "skip":
            continue
        if choice == "reuse" and decision.get("tool_id"):
            # Ownership-check the client-supplied id before linking (IDOR guard).
            tid = str(decision["tool_id"])
            if is_synthesized_tool_id(tid) or repo.get_any(tid, user):
                out.append(tid)
            else:
                warnings.append(f"Tool reuse id '{tid}' is not yours; ignored")
            continue

        custom_name = tool.get("name") or ""
        match = _find_user_tool(user_tools, tool_type, custom_name)
        if match and choice != "create":
            out.append(str(match["id"]))
            continue

        created_id = _create_tool_from_spec(conn, user, tool, decision.get("secrets") or {}, warnings)
        if created_id:
            out.append(created_id)
            # Record so a later identical spec entry reuses rather than re-creates.
            user_tools.append({"id": created_id, "name": tool_type, "custom_name": custom_name})
    return out


def _apply_models(conn, user: str, spec: dict, resolution: dict, warnings: list):
    model_spec = spec.get("model") or {}
    repo = UserCustomModelsRepository(conn)
    customs = repo.list_for_user(user)
    decisions = resolution.get("models")
    if not isinstance(decisions, dict):
        decisions = {}
    name_to_id: dict[str, str] = {}
    models: list[str] = []

    for entry in model_spec.get("available") or []:
        if isinstance(entry, str):
            if validate_model_id(entry, user):
                models.append(entry)
                name_to_id[entry] = entry
            else:
                warnings.append(f"Model '{entry}' not available; skipped")
            continue
        if not isinstance(entry, dict):
            continue
        display_name = entry.get("display_name") or ""
        match = _find_custom_model(customs, entry)
        if match:
            models.append(str(match["id"]))
            name_to_id[display_name] = str(match["id"])
            continue
        decision = decisions.get(display_name)
        api_key = decision.get("api_key") if isinstance(decision, dict) else None
        if not api_key:
            warnings.append(f"Custom model '{display_name}' needs an API key; skipped")
            continue
        base_url = entry.get("base_url") or ""
        try:
            validate_user_base_url(base_url)
        except UnsafeUserUrlError:
            warnings.append(f"Custom model '{display_name}' has an unsafe base URL; skipped")
            continue
        created = repo.create(
            user,
            entry.get("upstream_model_id") or "",
            display_name,
            base_url,
            api_key,
            capabilities=entry.get("capabilities") or {},
        )
        if not created.get("api_key_encrypted"):
            warnings.append(f"Custom model '{display_name}' key encryption failed; skipped")
            continue
        models.append(str(created["id"]))
        name_to_id[display_name] = str(created["id"])

    default_id = ""
    raw_default = model_spec.get("default") or ""
    if raw_default:
        if raw_default in name_to_id:
            default_id = name_to_id[raw_default]
        elif validate_model_id(raw_default, user):
            default_id = raw_default
        else:
            # Custom-model default carried as its display_name — resolve against
            # the user's own models even if it wasn't in `available`.
            owned = next(
                (c for c in customs if (c.get("display_name") or "") == raw_default), None
            )
            if owned:
                default_id = str(owned["id"])
            else:
                warnings.append(f"Default model '{raw_default}' not resolved")
    return (models or None), (default_id or None)


def _limit(spec: dict, key: str):
    return (spec.get("limits") or {}).get(key)


def apply_import(conn, user: str, doc: dict, resolution: Optional[dict] = None) -> dict:
    """Create or update an agent from a parsed YAML doc. Always lands as draft.

    On update the YAML is authoritative: fields it specifies are written even
    when that clears a value (e.g. removing all models, dropping ``json_schema``,
    or switching ``prompt`` back to default), so re-importing an edited file is
    a true sync rather than an additive merge.
    """
    if not isinstance(resolution, dict):
        resolution = {}
    spec = doc["spec"]
    metadata = doc.get("metadata") or {}
    warnings: list[str] = []

    target = _resolve_target(conn, user, metadata)

    prompt_id = _apply_prompt(conn, user, spec)
    source_ids = _apply_sources(conn, user, spec, resolution, warnings)
    tool_ids = _apply_tools(conn, user, spec, resolution, warnings)
    models, default_model_id = _apply_models(conn, user, spec, resolution, warnings)

    agents_repo = AgentsRepository(conn)
    is_update = bool(target.get("action") == "update" and target.get("agent_id"))
    exclude_id = str(target["agent_id"]) if is_update else None
    slug = _unique_slug(agents_repo, user, metadata.get("slug") or spec.get("name"), exclude_id=exclude_id)

    try:
        chunks_value = int(spec["chunks"]) if spec.get("chunks") is not None else 2
    except (TypeError, ValueError):
        chunks_value = 2

    # YAML-authoritative fields — written even when the resolved value is None,
    # so a re-import can CLEAR models / json_schema / prompt-to-default. On
    # create, AgentsRepository.create() skips None kwargs, so Nones become
    # column defaults.
    authoritative: dict[str, Any] = {
        "description": spec.get("description") or "",
        "agent_type": spec.get("agent_type") or "classic",
        "chunks": chunks_value,
        "prompt_id": prompt_id,
        "tools": tool_ids,
        "json_schema": spec.get("json_schema"),
        "models": models,
        "default_model_id": default_model_id,
        "extra_source_ids": source_ids,
        "limited_token_mode": bool(_limit(spec, "limited_token_mode")),
        "limited_request_mode": bool(_limit(spec, "limited_request_mode")),
        "allow_system_prompt_override": bool(spec.get("allow_system_prompt_override")),
        "slug": slug,
    }
    # Optional fields — applied only when present so a partial file doesn't wipe them.
    optional = {
        "retriever": spec.get("retriever") or ("classic" if not source_ids else None),
        "token_limit": _limit(spec, "token_limit"),
        "request_limit": _limit(spec, "request_limit"),
    }
    optional = {k: v for k, v in optional.items() if v is not None}

    if is_update:
        fields = {**authoritative, **optional, "name": spec.get("name"), "status": "draft"}
        if agents_repo.update(str(target["agent_id"]), user, fields):
            return {
                "agent_id": str(target["agent_id"]),
                "action": "updated",
                "slug": slug,
                "warnings": warnings,
            }
        # Row vanished between resolve and write — fall through to create.

    row = agents_repo.create(user, spec.get("name"), "draft", **{**authoritative, **optional})
    return {"agent_id": str(row["id"]), "action": "created", "slug": slug, "warnings": warnings}


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

agents_portability_ns = Namespace(
    "agents", description="Agent import/export operations", path="/api"
)


def _read_import_payload(req):
    """Pull (yaml_text, resolution) from a JSON body or uploaded file.

    Enforces a body-size cap before reading so a giant document can't be
    buffered into memory.
    """
    if req.content_length and req.content_length > MAX_IMPORT_BYTES:
        raise AgentImportError("Import document too large")
    content_type = req.content_type or ""
    if "application/json" in content_type:
        data = req.get_json(silent=True) or {}
        resolution = data.get("resolution")
        return (
            data.get("yaml") or data.get("content") or "",
            resolution if isinstance(resolution, dict) else {},
        )
    if "file" in req.files:
        raw = req.files["file"].read(MAX_IMPORT_BYTES + 1)
        if len(raw) > MAX_IMPORT_BYTES:
            raise AgentImportError("Import document too large")
        return raw.decode("utf-8", "replace"), {}
    # Raw body: read from the stream with a hard cap so a chunked request
    # (no Content-Length) can't be buffered unbounded into memory.
    raw = req.stream.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise AgentImportError("Import document too large")
    return raw.decode("utf-8", "replace"), {}


@agents_portability_ns.route("/export_agent")
class ExportAgent(Resource):
    @api.doc(params={"id": "Agent ID"}, description="Export an agent as YAML")
    def get(self):
        if not (decoded_token := request.decoded_token):
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        agent_id = request.args.get("id")
        if not agent_id:
            return make_response(jsonify({"success": False, "message": "id is required"}), 400)
        with db_session() as conn:
            repo = AgentsRepository(conn)
            agent = repo.get_any(agent_id, user)
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Agent not found"}), 404
                )
            if (agent.get("agent_type") or "") == "workflow":
                return make_response(
                    jsonify(
                        {"success": False, "message": "Workflow agents can't be exported yet"}
                    ),
                    400,
                )
            agent["slug"] = ensure_agent_slug(conn, agent, user)
            export = serialize_agent(conn, agent, user)
        body = agent_to_yaml(export)
        filename = f"{export['metadata'].get('slug') or 'agent'}.agent.yaml"
        response = make_response(body, 200)
        response.headers["Content-Type"] = "application/x-yaml; charset=utf-8"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


@agents_portability_ns.route("/import_agent/plan")
class ImportAgentPlan(Resource):
    @api.doc(description="Dry-run an agent YAML import and return the resolution plan")
    def post(self):
        if not (decoded_token := request.decoded_token):
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            yaml_text, _ = _read_import_payload(request)
            doc = parse_agent_yaml(yaml_text)
        except AgentImportError as exc:
            return make_response(jsonify({"success": False, "message": str(exc)}), 400)
        try:
            with db_readonly() as conn:
                plan = plan_import(conn, user, doc)
        except Exception:
            current_app.logger.error("Agent import plan failed", exc_info=True)
            return make_response(
                jsonify({"success": False, "message": "Could not analyze the agent file"}), 500
            )
        return make_response(jsonify({"success": True, "plan": plan}), 200)


@agents_portability_ns.route("/import_agent")
class ImportAgent(Resource):
    @api.doc(description="Import an agent from YAML (created as a draft)")
    def post(self):
        if not (decoded_token := request.decoded_token):
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            yaml_text, resolution = _read_import_payload(request)
            doc = parse_agent_yaml(yaml_text)
        except AgentImportError as exc:
            return make_response(jsonify({"success": False, "message": str(exc)}), 400)
        try:
            with db_session() as conn:
                result = apply_import(conn, user, doc, resolution)
        except Exception:
            current_app.logger.error("Agent import failed", exc_info=True)
            return make_response(
                jsonify({"success": False, "message": "Import failed"}), 500
            )
        return make_response(jsonify({"success": True, **result}), 200)
