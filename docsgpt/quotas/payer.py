"""Who pays for a run.

The payer of a run is always a person, fixed when the run starts, and every
model call that belongs to the run bills them (``token_usage.user_id``): its
title, compression, guardrail and fallback calls, its workflow steps and
sub-agents, and the continuation that carries it on.

Every run opens :func:`billed_to` for its whole length, chats included,
naming its payer, its kind (:data:`RUN_KINDS`) and the team workspace it runs
in. A run that executes as someone else (a schedule or a continuation runs as
the agent's owner, with the owner's sources, tools and model) still bills its
payer: the usage decorators record the payer instead of the identity the run
executes as, and stamp each row with the run's kind and workspace.

A team principal (the owner of a team's items) is never a payer: a team agent
runs as it, but its outside traffic bills the agent's published-access payer
(``agents.access_payer_id``), and with none that traffic is refused
(:data:`NO_PAYER_CODE`).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Optional, Tuple

from sqlalchemy import text

from docsgpt import tracing
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.session import db_readonly
from docsgpt.workspaces.principal import is_principal_id, team_of_principal

#: The code an outside request (key, widget, webhook, public link, ``/v1``) is refused with when the agent names
#: nobody to pay for it: a team agent whose published access has no payer.
NO_PAYER_CODE = "no_payer"
NO_PAYER_MESSAGE = "This agent has nobody to pay for its use right now, so it can't answer."

#: What a run is, as its usage rows record it (``token_usage.run_kind``): a person's chat (drafts count with
#: chats in reports), a schedule, outside traffic on a published agent (key, widget, link, ``/v1``, MCP,
#: webhook), building a source's knowledge, a monitor's judge, or the drafter.
RUN_KINDS = ("chat", "schedule", "published", "knowledge", "monitor", "drafter")


@dataclass(frozen=True)
class RunBilling:
    """The billing of the run in progress.

    Attributes:
        payer: The person the run's model calls bill, or None to bill the
            identity each call's LLM was built with.
        request_id: The request id its calls record when their LLM carries
            none, so the whole run counts as one request toward an agent's
            request limit.
        kind: What the run is (one of :data:`RUN_KINDS`), or None when unknown.
        team_id: The team workspace the run's spend belongs to; None is Personal.
        limits: The payer's limits, resolved when the run starts, that each
            model call is checked against; None checks nothing during the run.
    """

    payer: Optional[str]
    request_id: str
    kind: Optional[str] = None
    team_id: Optional[str] = None
    limits: Optional[Any] = None


# Carried into the threads a run hands work to (guardrail checks, workflow loop items).
_current: ContextVar[Optional[RunBilling]] = tracing.carry(ContextVar("docsgpt_run_billing", default=None))


def current_run_billing() -> Optional[RunBilling]:
    """Return the billing of the run in progress, or None outside a run that set one."""
    return _current.get()


@contextmanager
def billed_to(
    payer: Optional[str],
    request_id: Optional[str] = None,
    *,
    kind: Optional[str] = None,
    team_id: Optional[str] = None,
    limits: Optional[Any] = None,
) -> Iterator[RunBilling]:
    """Bill every model call made inside the block to ``payer``, as one request.

    A block that names no ``kind`` inside a run with the same payer is part of
    that run (a guardrail judge, a background job re-stating its payer): it
    keeps the run's kind, workspace and limits unless it names its own.

    Args:
        payer: The run's payer, fixed when it starts.
        request_id: The request id for calls that have none; a new one by default.
        kind: What the run is, one of :data:`RUN_KINDS`.
        team_id: The team workspace the run belongs to; None is Personal.
        limits: The payer's limits each model call of the run is checked against.

    Yields:
        The run's :class:`RunBilling`.

    Raises:
        ValueError: ``kind`` is not one of :data:`RUN_KINDS`.
    """
    if kind is not None and kind not in RUN_KINDS:
        raise ValueError(f"unknown run kind: {kind!r}")
    payer = payer or None
    team_id = str(team_id) if team_id else None
    outer = _current.get()
    if kind is None and outer is not None and outer.payer == payer:
        kind = outer.kind
        team_id = team_id or outer.team_id
        limits = limits if limits is not None else outer.limits
    billing = RunBilling(
        payer=payer, request_id=request_id or str(uuid.uuid4()), kind=kind, team_id=team_id, limits=limits
    )
    token = _current.set(billing)
    try:
        yield billing
    finally:
        _current.reset(token)


def published_access_payer(agent: Mapping[str, Any]) -> Optional[str]:
    """Who pays for outside traffic on this agent: its API key, widget, webhook and public link.

    The one place that answers it: the agent's published-access payer
    (``access_payer_id``, set when a team Admin turns outside access on or by a
    move), else the owner when the owner is a person. A team principal is
    never returned: a team agent with no published-access payer has none, and
    its outside traffic is refused.

    Args:
        agent: The agent row (``user_id``, ``access_payer_id``) or the legacy shape (``user``).

    Returns:
        The payer's user id, or None when nobody pays.
    """
    explicit = agent.get("access_payer_id")
    if explicit and not is_principal_id(explicit):
        return str(explicit)
    owner = agent.get("user_id") or agent.get("user") or None
    if owner and not is_principal_id(owner):
        return str(owner)
    return None


def agent_payer_and_team(
    agent_id: Optional[str] = None, api_key: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Who pays for the outside traffic of the agent with this id (or key), and the team that owns it.

    Args:
        agent_id: The agent's id.
        api_key: The agent's key, used when no id is given.

    Returns:
        ``(payer, team_id)``: :func:`published_access_payer` of the agent and
        its team (None for a personal agent); both None when no such agent exists.
    """
    if agent_id and looks_like_uuid(str(agent_id)):
        clause, params = "id = CAST(:v AS uuid)", {"v": str(agent_id)}
    elif api_key:
        clause, params = "key = :v", {"v": str(api_key)}
    else:
        return None, None
    with db_readonly() as conn:
        row = conn.execute(
            text(f"SELECT user_id, access_payer_id FROM agents WHERE {clause}"), params
        ).fetchone()
    if row is None:
        return None, None
    agent = dict(row._mapping)
    return published_access_payer(agent), team_of_principal(agent.get("user_id"))


def agent_access_payer(agent_id: Optional[str] = None, api_key: Optional[str] = None) -> Optional[str]:
    """:func:`published_access_payer` of the agent with this id (or key), read from the database.

    Args:
        agent_id: The agent's id.
        api_key: The agent's key, used when no id is given.

    Returns:
        The payer, or None when nobody pays or no such agent exists.
    """
    return agent_payer_and_team(agent_id, api_key)[0]


def payer_for(identity: Optional[str], agent_id: Optional[str] = None) -> Optional[str]:
    """Who pays for work that runs as ``identity`` outside any run that set a payer.

    A person pays for their own work. Work that runs as a team principal (a
    team agent reached by its key, or a conversation that traffic left) bills
    the agent's published-access payer.

    Args:
        identity: The user id the work runs as.
        agent_id: The agent it runs through, if any.

    Returns:
        A person's id, or None when nobody can be billed.
    """
    if not identity:
        return None
    if not is_principal_id(identity):
        return str(identity)
    return agent_access_payer(agent_id)
