"""Who pays for a run.

The payer of a run is always a person, fixed when the run starts, and every
model call that belongs to the run bills them (``token_usage.user_id``): its
title, compression, guardrail and fallback calls, its workflow steps and
sub-agents, and the continuation that carries it on.

A chat bills the person chatting through its own token, so it needs nothing
here. A run that executes as someone else (a schedule or a continuation runs
as the agent's owner, with the owner's sources, tools and model) opens
:func:`billed_to` with its payer for its whole length; the usage decorators
then record the payer instead of the identity the run executes as.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Optional

from docsgpt import tracing


@dataclass(frozen=True)
class RunBilling:
    """The billing of the run in progress.

    Attributes:
        payer: The person the run's model calls bill, or None to bill the
            identity each call's LLM was built with.
        request_id: The request id its calls record when their LLM carries
            none, so the whole run counts as one request toward an agent's
            request limit.
    """

    payer: Optional[str]
    request_id: str


# Carried into the threads a run hands work to (guardrail checks, workflow loop items).
_current: ContextVar[Optional[RunBilling]] = tracing.carry(ContextVar("docsgpt_run_billing", default=None))


def current_run_billing() -> Optional[RunBilling]:
    """Return the billing of the run in progress, or None outside a run that set one."""
    return _current.get()


@contextmanager
def billed_to(payer: Optional[str], request_id: Optional[str] = None) -> Iterator[RunBilling]:
    """Bill every model call made inside the block to ``payer``, as one request.

    Args:
        payer: The run's payer, fixed when it starts.
        request_id: The request id for calls that have none; a new one by default.

    Yields:
        The run's :class:`RunBilling`.
    """
    billing = RunBilling(payer=payer or None, request_id=request_id or str(uuid.uuid4()))
    token = _current.set(billing)
    try:
        yield billing
    finally:
        _current.reset(token)


def published_access_payer(agent: Mapping[str, Any]) -> Optional[str]:
    """Who pays for outside traffic on this agent: its API key, widget, webhook and public link.

    The one place that answers it. Today it is the agent's owner; a later step
    gives the agent a published-access payer of its own and reads it here.

    Args:
        agent: The agent row (``user_id``) or the legacy shape (``user``).

    Returns:
        The payer's user id, or None when the agent names no owner.
    """
    return agent.get("user_id") or agent.get("user") or None
