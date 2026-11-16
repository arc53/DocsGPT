"""The limits a run is held to while it runs, checked before each of its model calls.

A run's limits are resolved once, when it starts (:meth:`RunLimits.start`):
its payer's allowance for ``all`` and the run's bucket, the window they count
over, and the agent's own token limit. They ride on the run's billing
(``billed_to(..., limits=...)``), and every model call of the run checks them
first (``BaseLLM._execute_with_fallback``), so a tool loop stops at the limit
instead of running past it. The call that crosses a limit completes; the next
one is refused with :class:`RunLimitReached`, which escapes provider fallback,
tool error recovery and workflow retries (``stops_run``).

The agent limit is checked before the payer's allowance, and the first one
used up is named. Only the agent's token limit applies inside a run: a run is
one request, so the run that crosses the request limit completes.

The check costs no query while neither the payer nor the agent has a limit,
and one read per call otherwise. A database error allows the call, as the
pre-run check does: a quota outage must not take chat down. A team principal
offered as the payer fails closed, at start, before anything is spent.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Mapping, Optional, Union

from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.quotas.agent_limits import WINDOW_HOURS, AgentLimitExceeded, _flag
from docsgpt.quotas.pause import PAYER_OUT_OF_ALLOWANCE
from docsgpt.quotas.providers import default_rows
from docsgpt.quotas.resolver import ResolvedLimits, resolve_limits
from docsgpt.quotas.service import REQUEST_BUCKETS, BucketStatus, NoPayerError, QuotaExceeded, QuotaExceededError
from docsgpt.quotas.windows import window_bounds
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.session import db_readonly
from docsgpt.workspaces.principal import is_principal_id

logger = logging.getLogger(__name__)

#: A headless run stopped by its agent's own limit (the value schedules already record for it).
AGENT_LIMIT_ERROR_TYPE = "budget_exceeded"

#: The ``error_type`` values a headless run stopped mid-way by a limit returns.
RUN_LIMIT_ERROR_TYPES = (PAYER_OUT_OF_ALLOWANCE, AGENT_LIMIT_ERROR_TYPE)


class RunLimitReached(QuotaExceededError):
    """A run refused another model call: its payer's allowance or its agent's limit is used up.

    A :class:`QuotaExceededError`, so headless callers and workflow retries
    stop on it, and ``stops_run`` makes it escape provider fallback and tool
    error recovery (``core.run_budget.is_budget_exhausted``).

    Attributes:
        exceeded: The :class:`QuotaExceeded` (payer) or :class:`AgentLimitExceeded` (agent).
        outside: The run is outside traffic on a published agent, whose caller
            is told only that the agent is paused.
    """

    stops_run = True

    def __init__(self, exceeded: Union[QuotaExceeded, AgentLimitExceeded], *, outside: bool = False) -> None:
        self.exceeded = exceeded
        self.outside = outside
        # Not ``QuotaExceededError.__init__``: that builds the client payload,
        # which calls the provider hook with the payer's id.
        Exception.__init__(self, self.message)

    @property
    def agent_limit(self) -> bool:
        """Whether the agent's own limit stopped the run (else the payer's allowance)."""
        return isinstance(self.exceeded, AgentLimitExceeded)

    @property
    def error_type(self) -> str:
        """The headless outcome's ``error_type``: ``budget_exceeded`` or ``payer_out_of_allowance``."""
        return AGENT_LIMIT_ERROR_TYPE if self.agent_limit else PAYER_OUT_OF_ALLOWANCE

    @property
    def message(self) -> str:
        """What the run's caller is told; an outside caller never learns the payer's numbers."""
        if self.agent_limit:
            return self.exceeded.message
        if self.outside:
            from docsgpt.api.owner_pause import PAUSED_MESSAGE

            return PAUSED_MESSAGE
        exceeded = self.exceeded
        if exceeded.budget == "cost":
            amounts = f"${exceeded.usage:.2f} of ${exceeded.limit:.2f}"
        else:
            amounts = f"{int(exceeded.usage):,} of {int(exceeded.limit):,} tokens"
        return f"Usage quota reached ({amounts}). It resets at {exceeded.resets_at.isoformat()}."


class _AgentTokenLimit:
    """The agent's token limit over its rolling window, and how its rows are found."""

    __slots__ = ("agent_id", "api_key", "limit")

    def __init__(self, agent_id: Optional[str], api_key: Optional[str], limit: int) -> None:
        self.agent_id = agent_id
        self.api_key = api_key
        self.limit = limit


def _agent_token_limit(agent: Optional[Mapping[str, Any]]) -> Optional[_AgentTokenLimit]:
    """The agent's token limit when it has one switched on, read from its row; no query."""
    if not agent or not _flag(agent.get("limited_token_mode", False)):
        return None
    raw_id = agent.get("id") or agent.get("_id")
    agent_id = str(raw_id) if raw_id and looks_like_uuid(str(raw_id)) else None
    api_key = agent.get("key") or None
    if agent_id is None and api_key is None:
        return None
    limit = int(agent.get("token_limit") or settings.DEFAULT_AGENT_LIMITS["token_limit"])
    return _AgentTokenLimit(agent_id, api_key, limit) if limit > 0 else None


def _agent_row(conn: Any, agent_id: Optional[str], api_key: Optional[str]) -> Optional[dict]:
    """The agent's limit columns, by id or else by key."""
    if agent_id and looks_like_uuid(str(agent_id)):
        clause, params = "id = CAST(:v AS uuid)", {"v": str(agent_id)}
    elif api_key:
        clause, params = "key = :v", {"v": str(api_key)}
    else:
        return None
    row = conn.execute(
        text(f"SELECT id, key, limited_token_mode, token_limit FROM agents WHERE {clause}"), params
    ).fetchone()
    return dict(row._mapping) if row is not None else None


class RunLimits:
    """A run's payer limits and agent limit, resolved at start and checked before each model call.

    Attributes:
        payer: The person the run bills.
        outside: The run is outside traffic on a published agent.
        reached: The stop, once a call was refused; every later call is
            refused with it, without another query.
    """

    def __init__(
        self,
        payer: str,
        *,
        limits: Optional[dict[str, ResolvedLimits]] = None,
        window_start: Optional[datetime.datetime] = None,
        resets_at: Optional[datetime.datetime] = None,
        agent: Optional[_AgentTokenLimit] = None,
        outside: bool = False,
    ) -> None:
        self.payer = payer
        # Only the buckets with a limit; checked in order (``all`` first).
        self._limits = {bucket: resolved for bucket, resolved in (limits or {}).items() if not resolved.unlimited}
        self._window_start = window_start
        self._resets_at = resets_at
        self._agent = agent
        self.outside = outside
        self.reached: Optional[RunLimitReached] = None

    @classmethod
    def start(
        cls,
        payer: Optional[str],
        *,
        bucket: str,
        agent: Optional[Mapping[str, Any]] = None,
        agent_id: Optional[str] = None,
        api_key: Optional[str] = None,
        outside: bool = False,
        now: Optional[datetime.datetime] = None,
    ) -> Optional["RunLimits"]:
        """Resolve a run's limits as it starts.

        Args:
            payer: The run's payer.
            bucket: ``direct`` for a run with no agent, ``agent`` for one through an agent.
            agent: The agent row, when the caller has it (no read is needed).
            agent_id: The agent's id, read when ``agent`` is not given.
            api_key: The agent's key, read when neither ``agent`` nor ``agent_id`` is given.
            outside: The run is outside traffic on a published agent.
            now: Reference instant, for tests.

        Returns:
            The run's limits, or None when there is no payer to check.

        Raises:
            NoPayerError: ``payer`` is a team principal. This fails closed,
                before any lookup.
            ValueError: An unknown bucket.
        """
        if is_principal_id(payer):
            raise NoPayerError(payer)
        if not payer:
            return None
        if bucket not in REQUEST_BUCKETS:
            raise ValueError(f"unknown request bucket: {bucket!r}")
        start, resets_at = window_bounds(settings.QUOTA_PERIOD, now)
        resolved: dict[str, ResolvedLimits] = {}
        agent_limit = _agent_token_limit(agent)
        try:
            with db_readonly() as conn:
                if agent is None and (agent_id or api_key):
                    agent_limit = _agent_token_limit(_agent_row(conn, agent_id, api_key))
                rows = QuotaPoliciesRepository(conn).policies_for_user(payer) + default_rows(payer)
            for name in ("all", bucket):
                resolved[name] = resolve_limits(rows, name)
        except Exception:
            # As the pre-run check: a quota outage must not take the run down.
            logger.exception("run limits could not be read; the run is not checked", extra={"user_id": payer})
            resolved = {}
        return cls(
            payer, limits=resolved, window_start=start, resets_at=resets_at, agent=agent_limit, outside=outside
        )

    @property
    def limited(self) -> bool:
        """Whether anything is checked: a limited budget or an agent token limit."""
        return bool(self._limits) or self._agent is not None

    def check_call(self) -> None:
        """Refuse the next model call when a limit is used up.

        Costs no query when nothing is limited, or once the run was stopped.

        Raises:
            RunLimitReached: The agent's token limit or the payer's allowance is used up.
        """
        if self.reached is not None:
            raise self.reached
        if not self.limited:
            return
        try:
            exceeded = self._exceeded()
        except Exception:
            logger.exception("run limit check failed; allowing the call", extra={"user_id": self.payer})
            return
        if exceeded is not None:
            self.reached = RunLimitReached(exceeded, outside=self.outside)
            raise self.reached

    def _exceeded(self) -> Optional[Union[QuotaExceeded, AgentLimitExceeded]]:
        """The agent limit used up, else the payer's first budget used up, else None (one connection)."""
        with db_readonly() as conn:
            repo = TokenUsageRepository(conn)
            agent = self._agent
            if agent is not None:
                end = datetime.datetime.now(datetime.timezone.utc)
                used = int(
                    repo.sum_tokens_in_range(
                        start=end - datetime.timedelta(hours=WINDOW_HOURS),
                        end=end,
                        api_key=agent.api_key,
                        agent_id=agent.agent_id,
                    )
                    or 0
                )
                if used >= agent.limit:
                    return AgentLimitExceeded(
                        agent_id=agent.agent_id, dimension="tokens", usage=used, limit=agent.limit
                    )
            if not self._limits:
                return None
            if self._resets_at is not None and datetime.datetime.now(datetime.timezone.utc) >= self._resets_at:
                # A run that outlived its period counts from the new one, as the next run would.
                self._window_start, self._resets_at = window_bounds(settings.QUOTA_PERIOD)
            totals = repo.usage_totals_for_buckets(self.payer, self._window_start, tuple(self._limits))
        for bucket, resolved in self._limits.items():
            tokens_used, cost_used = totals.get(bucket, (0, 0.0))
            status = BucketStatus(bucket, resolved, tokens_used, cost_used, self._resets_at)
            budget = status.exceeded_budget()
            if budget is None:
                continue
            limit = resolved.tokens if budget == "tokens" else resolved.cost
            return QuotaExceeded(
                user_id=self.payer,
                bucket=bucket,
                budget=budget,
                usage=tokens_used if budget == "tokens" else cost_used,
                limit=limit.limit,
                source=limit.source,
                source_id=limit.source_id,
                resets_at=self._resets_at,
            )
        return None


def limits_stop() -> Optional[RunLimitReached]:
    """The stop of the run in progress, when one of its model calls was refused (even if something swallowed it)."""
    from docsgpt.quotas.payer import current_run_billing

    billing = current_run_billing()
    limits = getattr(billing, "limits", None) if billing is not None else None
    reached = getattr(limits, "reached", None)
    return reached if isinstance(reached, RunLimitReached) else None
