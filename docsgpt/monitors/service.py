"""Creating, listing and ending monitors: what the ``monitor`` tool and the Monitors page call.

``create`` validates the request, refuses what can never deliver (a
conversation auto-resume does not apply to, a headless run, the per-user
cap), takes the baseline of a polled source right away (so the reply can say
"currently $52,140"), mints the link of a webhook or approval monitor and
stores everything in one transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from docsgpt.core.settings import settings
from docsgpt.monitors import links
from docsgpt.monitors.checks import CheckError, Content, evaluate
from docsgpt.monitors.events import publish_monitor_updated, wakes_left
from docsgpt.monitors.fetch import SourceError, SourceUnreachable, fetch_webpage
from docsgpt.monitors.spec import (
    MonitorRequest,
    SpecError,
    bounded_state,
    human_duration,
    next_tick,
    parse_iso,
    parse_request,
    substitute,
)
from docsgpt.storage.db.repositories.monitors import MonitorsRepository
from docsgpt.storage.db.repositories.trigger_links import TriggerLinksRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

#: Characters of the watched content kept as the excerpt a change is compared against.
EXCERPT_CHARS = 4000

#: The tool's actions (the model sees these names: ``monitor_create`` reads as ``monitor.create``).
CREATE = "monitor_create"
LIST = "monitor_list"
CANCEL = "monitor_cancel"


@dataclass
class Caller:
    """Who is creating or managing monitors, and from where.

    Attributes:
        user_id: The conversation's owner.
        conversation_id: The conversation a monitor wakes.
        agent_id: The conversation's agent (its tools are the sources), or None.
        headless: A scheduled, webhook or continuation run (nobody to ask; no creating).
        api_route: The OpenAI-compatible ``/v1`` route (can't be resumed).
        outside_caller: An API-key or public-link caller acting on the owner's agent.
        workflow: A workflow node (no conversation to resume).
        executor: The turn's ``ToolExecutor``, when there is one.
    """

    user_id: str
    conversation_id: Optional[str]
    agent_id: Optional[str] = None
    headless: bool = False
    api_route: bool = False
    outside_caller: bool = False
    workflow: bool = False
    executor: Any = None

    @classmethod
    def from_executor(cls, executor: Any, user_id: Optional[str]) -> "Caller":
        background = getattr(executor, "background", None)
        return cls(
            user_id=str(user_id or getattr(executor, "user", "") or ""),
            conversation_id=getattr(executor, "conversation_id", None),
            agent_id=str(executor.agent_id) if getattr(executor, "agent_id", None) else None,
            headless=bool(getattr(executor, "headless", False)),
            api_route=bool(getattr(background, "api_route", False)),
            outside_caller=bool(getattr(executor, "external_caller", False))
            or bool(getattr(executor, "public_link_caller", False)),
            workflow=bool(getattr(executor, "workflow_run_id", None)),
            executor=executor,
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


def refusal(caller: Caller) -> Optional[str]:
    """Why this caller can't create a monitor here, or None when it can.

    A monitor reports back only by resuming its conversation, so it is
    refused wherever that can't happen: no conversation, a headless or
    workflow run, ``/v1``, API-key and widget traffic, shared links, another
    user's agent, or auto-resume switched off.
    """
    if not settings.MONITORS_ENABLED:
        return "Monitors are turned off on this instance."
    if not settings.AUTO_RESUME_ENABLED:
        return "Monitors need auto-resume (AUTO_RESUME_ENABLED), which is off on this instance."
    if caller.headless:
        return "A monitor can only be created while the user is in the chat, never from a background run."
    if caller.workflow or not caller.conversation_id or not caller.user_id:
        return "A monitor needs a saved conversation to report back to."
    if caller.api_route or caller.outside_caller:
        return (
            "This conversation can't be resumed (API, widget or shared access), so a monitor here could never "
            "report back. Tell the user to set it up in the DocsGPT app instead."
        )
    from docsgpt.background.context import auto_resume_allowed

    with db_readonly() as conn:
        allowed = auto_resume_allowed(conn, str(caller.conversation_id), caller.user_id)
    if not allowed:
        return (
            "This conversation can't be resumed (it is shared, reached by API key, or runs another user's agent), "
            "so a monitor here could never report back."
        )
    return None


# ----------------------------------------------------------------------
# Approval at creation
# ----------------------------------------------------------------------


def create_needs_approval(executor: Any, action_name: str, arguments: Any) -> bool:
    """Whether ``monitor_create`` must ask for approval: its tool source would, in chat.

    Called by ``ToolExecutor.check_pause``. A request that is invalid or
    refused anyway needs no approval card (the tool returns why); a lookup
    that fails unexpectedly asks for approval rather than skip it.

    Args:
        executor: The turn's executor.
        action_name: The monitor action called.
        arguments: Its arguments.

    Returns:
        True when the approval card must be shown first.
    """
    if action_name != CREATE or not isinstance(arguments, dict):
        return False
    source = arguments.get("source")
    if not isinstance(source, dict) or source.get("type") != "tool":
        return False
    if getattr(executor, "headless", False):
        return False
    try:
        from docsgpt.monitors import sources

        tool_executor, tools = sources.build_executor(
            str(executor.user), getattr(executor, "agent_id", None), headless=False
        )
        resolved = sources.resolve_tool(tool_executor, tools, str(source.get("tool") or ""), source.get("action"))
        args = source.get("args") if isinstance(source.get("args"), dict) else {}
        decision = sources.gate(tool_executor, tools, resolved, substitute(args, now=_now()))
        return decision.requires_approval and not decision.refusal
    except SpecError:
        return False
    except Exception:
        logger.exception("monitor: deciding whether a source needs approval failed; asking for approval")
        return True


# ----------------------------------------------------------------------
# Create
# ----------------------------------------------------------------------


def source_summary(source: Dict[str, Any]) -> str:
    """One line naming what a monitor watches."""
    kind = source.get("type")
    if kind == "webpage":
        selector = source.get("css_selector")
        return f"the page {source.get('url')}" + (f" ({selector})" if selector else "")
    if kind == "tool":
        return f"the tool call {source.get('tool')}" + (f".{source['action']}" if source.get("action") else "")
    if kind == "ingest":
        return f"ingestion of source {source.get('source_id')}"
    if kind == "webhook":
        return "calls to a webhook link"
    return "a decision on an approval link"


def _baseline_summary(request: MonitorRequest, content: Content, evaluation) -> Dict[str, Any]:
    out: Dict[str, Any] = {"summary": evaluation.summary}
    if "value" in evaluation.detail:
        out["value"] = evaluation.detail["value"]
    if evaluation.detail.get("matches"):
        out["matches"] = evaluation.detail["matches"][:5]
    if request.check and request.check.get("type") == "new_items":
        out["items_now"] = len(evaluation.state.get("seen") or [])
    out["excerpt"] = content.text[:600]
    return out


def _take_baseline(caller: Caller, request: MonitorRequest, now: datetime):
    """Check a polled source once: ``(content, approval)``; raises SpecError/SourceError."""
    source = request.source
    if source["type"] == "webpage":
        return fetch_webpage(source["url"], source.get("css_selector")), None
    from docsgpt.monitors import sources

    tool_executor, tools = sources.build_executor(caller.user_id, caller.agent_id, headless=False)
    resolved = sources.resolve_tool(tool_executor, tools, source["tool"], source.get("action"))
    decision = sources.gate(tool_executor, tools, resolved, substitute(source["args"], now=now))
    if decision.refusal:
        raise SpecError(f"This source can't be monitored: {decision.refusal}")
    if decision.requires_approval:
        executor = caller.executor
        approved = executor is not None and executor.current_call_id in (executor.approved_call_ids or set())
        if not approved:
            raise SpecError(
                "This source needs the user's approval, which this call did not get. Call monitor_create again "
                "so the user is asked."
            )
    approval = sources.binding(resolved, source["args"], decision, now_iso=_iso(now))
    source["tool"] = resolved.llm_name
    source["action"] = resolved.action
    content = sources.run_call(
        user_id=caller.user_id,
        agent_id=caller.agent_id,
        conversation_id=caller.conversation_id,
        approval=approval,
        args_template=source["args"],
        placeholders={"now": now},
        call_tag="baseline",
    )
    return content, approval


def _cap_error(live: int, cap: int) -> Dict[str, Any]:
    if cap <= 0:
        return {"error": "Creating monitors is turned off on this instance."}
    return {
        "error": (
            f"The user already has {live} active or paused monitors (the limit is {cap}). Ask which one to "
            "cancel (monitor_list, or Settings > Monitors) before creating another."
        )
    }


def create(caller: Caller, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Create a monitor for this conversation.

    Args:
        caller: Who asks, from which conversation.
        arguments: ``monitor_create``'s arguments.

    Returns:
        The tool result: the monitor, its baseline or link, and what to tell the user;
        ``{"error": ...}`` when nothing was created.
    """
    refused = refusal(caller)
    if refused:
        return {"error": refused}
    now = _now()
    try:
        request = parse_request(arguments, now=now)
    except SpecError as exc:
        return {"error": str(exc)}
    with db_readonly() as conn:
        live = MonitorsRepository(conn).count_live_for_user(caller.user_id)
        if request.source["type"] == "ingest":
            from docsgpt.storage.db.repositories.sources import SourcesRepository

            found = SourcesRepository(conn).get_any(request.source["source_id"], caller.user_id)
            if found is None:
                return {"error": "`source.source_id` is not one of the user's sources."}
            request.source["source_id"] = str(found["id"])
    cap = int(settings.MONITOR_MAX_ACTIVE_PER_USER)
    if live >= cap:
        return _cap_error(live, cap)

    state: Dict[str, Any] = {}
    approval: Optional[Dict[str, Any]] = None
    baseline: Optional[Dict[str, Any]] = None
    already = False
    if request.polled:
        try:
            content, approval = _take_baseline(caller, request, now)
            evaluation = evaluate(request.check, content, None, baseline=True)
        except SpecError as exc:
            return {"error": str(exc)}
        except SourceUnreachable as exc:
            return {"error": f"The source can't be reached right now ({exc}); nothing was created. Try again later."}
        except SourceError as exc:
            return {"error": f"The source doesn't work as a monitor: {exc}. Nothing was created."}
        except CheckError as exc:
            return {"error": f"The check doesn't fit what the source returns: {exc}. Nothing was created."}
        state = bounded_state(
            {"hash": content.digest, "excerpt": content.text[:EXCERPT_CHARS], "check": evaluation.state}
        )
        baseline = _baseline_summary(request, content, evaluation)
        already = bool(evaluation.holds and request.check and request.check.get("type") in ("threshold", "status",
                                                                                              "regex"))

    link_token: Optional[str] = None
    secret: Optional[str] = None
    kind = request.source["type"]
    with db_session() as conn:
        repo = MonitorsRepository(conn)
        # Two creates racing past the earlier count can't both take the last slot.
        repo.lock_user(caller.user_id)
        live = repo.count_live_for_user(caller.user_id)
        if live >= cap:
            return _cap_error(live, cap)
        next_run = (
            next_tick(now, request.interval_seconds, request.expires_at) if request.polled else request.expires_at
        )
        monitor = repo.create(
            user_id=caller.user_id,
            conversation_id=str(caller.conversation_id),
            agent_id=caller.agent_id,
            description=request.description,
            source_type=kind,
            spec=request.spec(),
            on_match=request.on_match,
            end_at=request.expires_at,
            next_run_at=next_run,
            max_wakes=request.max_wakes,
            interval_seconds=request.interval_seconds,
            state=state,
            approval=approval,
            token_budget=int(settings.MONITOR_JUDGE_TOKEN_BUDGET) or None,
            check_count=1 if request.polled else 0,
            last_checked_at=now if request.polled else None,
        )
        if kind in ("webhook", "approval"):
            link_token = links.new_token(kind)
            scheme = request.source.get("signature", "none") if kind == "webhook" else "none"
            secret = links.new_secret(scheme) if kind == "webhook" else None
            TriggerLinksRepository(conn).create(
                monitor_id=monitor["id"],
                user_id=caller.user_id,
                conversation_id=str(caller.conversation_id),
                token_hash=links.token_hash(link_token),
                kind=kind,
                expires_at=request.expires_at,
                max_hits=links.WEBHOOK_MAX_HITS if kind == "webhook" else 1,
                signature_scheme=scheme,
                secret_encrypted=links.seal_secret(secret, caller.user_id),
                approval_spec=(
                    {k: request.source[k] for k in ("question", "details", "options", "allow_comment")
                     if k in request.source}
                    if kind == "approval"
                    else None
                ),
            )
    publish_monitor_updated(monitor)
    return _created_result(request, monitor, baseline=baseline, already=already, token=link_token, secret=secret)


def _created_result(
    request: MonitorRequest,
    monitor: Dict[str, Any],
    *,
    baseline: Optional[Dict[str, Any]],
    already: bool,
    token: Optional[str],
    secret: Optional[str],
) -> Dict[str, Any]:
    kind = request.source["type"]
    result: Dict[str, Any] = {
        "monitor_id": str(monitor["id"]),
        "status": "active",
        "description": request.description,
        "watching": source_summary(request.source),
        "check": request.check,
        "condition": request.condition,
        "expires_at": _iso(request.expires_at),
        "max_wakes": request.max_wakes,
    }
    if request.interval_seconds:
        result["interval"] = human_duration(request.interval_seconds)
        result["next_check_at"] = _iso(monitor.get("next_run_at"))
    if request.notes:
        result["notes"] = request.notes
    tell = (
        "Tell the user what is watched, how often and until when, and that you will report back here when it "
        "fires. Don't check it yourself in the meantime."
    )
    if baseline is not None:
        result["baseline"] = baseline
        result["already_matching"] = already
        if already:
            tell += (
                " The check already holds now, so it fires only when it newly holds again: tell the user the "
                "current state now."
            )
    if kind == "webhook" and token:
        url = links.trigger_url(token)
        scheme = request.source.get("signature", "none")
        result.update({"url": url, "method": "POST", "signature": scheme, "example_curl": links.example_curl(
            url, scheme, secret
        )})
        if secret:
            result["secret"] = secret
            result["signing"] = links.signing_instructions(scheme)
            tell += " Give the user the url and the secret now; the secret is shown only this once."
        else:
            tell += " Give the user the url (POST only; a GET does nothing)."
        _add_reachability(result, url)
    if kind == "approval" and token:
        url = links.approval_page_url(token)
        result.update({"url": url, "question": request.source["question"], "options": request.source["options"]})
        tell = (
            "Send this link to the person who decides, through a tool you have (email, Slack, ...) if the user "
            "asked you to, or give it to the user to forward. Never open, approve or reject it yourself: you are "
            "told the decision when that person makes it."
        )
        _add_reachability(result, url)
    if kind == "ingest":
        tell = "Tell the user you will report back here when the ingest of that source finishes or fails."
    result["next"] = tell
    return result


def _add_reachability(result: Dict[str, Any], url: str) -> None:
    public, note = links.reachability(url)
    result["reachable_from_internet"] = public
    if note:
        result["reachability_note"] = note


# ----------------------------------------------------------------------
# List and manage
# ----------------------------------------------------------------------


def view(monitor: Dict[str, Any], *, links_rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """A monitor as the tool and the Monitors page show it (no state, secrets or tokens)."""
    spec = monitor.get("monitor_spec") or {}
    source = spec.get("source") or {}
    out = {
        "monitor_id": str(monitor.get("id")),
        "description": monitor.get("description"),
        "status": monitor.get("status"),
        "source_type": monitor.get("source_type"),
        "watching": source_summary(source),
        "check": spec.get("check"),
        "condition": spec.get("condition"),
        "on_match": monitor.get("on_match"),
        "interval": human_duration(int(monitor["interval_seconds"])) if monitor.get("interval_seconds") else None,
        "interval_seconds": monitor.get("interval_seconds"),
        "conversation_id": str(monitor.get("conversation_id")) if monitor.get("conversation_id") else None,
        "agent_id": str(monitor.get("agent_id")) if monitor.get("agent_id") else None,
        "created_at": monitor.get("created_at"),
        "expires_at": monitor.get("end_at"),
        "next_check_at": monitor.get("next_run_at") if monitor.get("interval_seconds") else None,
        "last_checked_at": monitor.get("last_checked_at"),
        "last_changed_at": monitor.get("last_changed_at"),
        "last_woken_at": monitor.get("last_woken_at"),
        "check_count": int(monitor.get("check_count") or 0),
        "wake_count": int(monitor.get("wake_count") or 0),
        "max_wakes": int(monitor.get("max_wakes") or 0),
        "wakes_left": wakes_left(monitor),
        "last_error": monitor.get("last_error"),
        "paused_reason": monitor.get("paused_reason"),
        "approval_required": bool((monitor.get("approval") or {}).get("required")),
    }
    if links_rows is not None:
        out["links"] = [links.link_view(link) for link in links_rows]
    return out


def list_for_conversation(caller: Caller) -> List[Dict[str, Any]]:
    """This conversation's monitors, newest first."""
    if not caller.conversation_id:
        return []
    with db_readonly() as conn:
        rows = MonitorsRepository(conn).list_for_user(caller.user_id, conversation_id=str(caller.conversation_id))
    return [view(row) for row in rows]


def end(monitor_id: str, user_id: str, status: str, *, reason: Optional[str] = None,
        conversation_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Cancel, complete or pause an owned monitor; revokes its links when it ends.

    Args:
        monitor_id: The monitor.
        user_id: Its owner (anyone else gets None).
        status: ``cancelled``, ``completed`` or ``paused``.
        reason: Why (shown on the Monitors page).
        conversation_id: When set, the monitor must belong to this conversation.

    Returns:
        The monitor after the change, or None when it isn't the caller's or didn't change.
    """
    with db_session() as conn:
        repo = MonitorsRepository(conn)
        monitor = repo.get(monitor_id, user_id)
        if monitor is None or (conversation_id and str(monitor.get("conversation_id")) != str(conversation_id)):
            return None
        if not repo.finish(monitor_id, status, reason=reason):
            return None
        if status != "paused":
            TriggerLinksRepository(conn).revoke_for_monitor(monitor_id)
        monitor = repo.get_internal(monitor_id)
    publish_monitor_updated(monitor)
    return monitor


def resume(monitor_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Re-activate an owned paused monitor; a polled one checks again right away.

    Returns:
        The monitor, or None when it isn't the caller's, isn't paused or has expired.
    """
    with db_session() as conn:
        repo = MonitorsRepository(conn)
        monitor = repo.get(monitor_id, user_id)
        if monitor is None:
            return None
        next_run = _now() if monitor.get("interval_seconds") else parse_iso(monitor.get("end_at"))
        if not repo.resume(monitor_id, next_run):
            return None
        monitor = repo.get_internal(monitor_id)
    publish_monitor_updated(monitor)
    return monitor
