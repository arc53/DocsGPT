"""The analytics sweep: labels stored conversations in the background, newest first, into ``conversation_labels``.

A beat task every ``ANALYTICS_SWEEP_SECONDS`` on its own queue (``ANALYTICS_QUEUE``), kept out of
``docsgpt/api/user/tasks.py`` for the reason ``embeddings_tasks.py`` gives: a worker that imports it should not
import the parsing stack. Nothing runs in the request path. The worker reads rows, builds states and writes labels;
its model calls go through the decision client with ``Budget.BACKGROUND``, so they reach the decider sidecar, the
API process's model or the remote endpoint at background priority, and no worker loads a model.

One sweep, under a Redis lock so overlapping beats and several workers are safe. The sweep refreshes the lock as it
goes, only while it is still its own, and stops (``lock_lost``) once another sweep holds it:

1. **Pending pass.** ``resolution`` recomputed, without a model call, once a pending conversation passes the window.
   One that cannot be (no user message left, or no ``goal_met``) is deleted with its ``experience``, so it is not
   loaded again every sweep; the conversation pass writes both again with ``goal_met``.
2. **Message pass.** Unlabelled messages (``ConversationLabelsRepository.message_candidates``), a conversation at a
   time, taking turns between agents, each one's newest first: per message its turn, the reaction to the answer
   before it, its topic (the one-pick question over the agent's own topics and source folders) and its request
   type, batched ``ANALYTICS_BATCH_STATES`` states to a call (never more than ``DECISION_MAX_BATCH_STATES``). Each
   batch's rows, and the derived ``gap_type`` and ``topic_effective`` rows of its conversations, are written in one
   transaction. It may take ``MESSAGE_SHARE`` of the budget, counted between messages, so neither a backlog of
   messages nor one long conversation starves step 3; what the share leaves unasked is built again by its next turn.
3. **Conversation pass.** Idle conversations without current ``goal_met``: goal met and every topic that can overlap
   (a ``tag:<id>`` label) in one request, then the derived ``resolution`` and ``experience``. Changing the topics
   that can overlap asks it again; changing the others does not. What budget it leaves goes back to step 2.

It stops starting calls when its time budget is spent, when a call about more than one message answers nothing
(``unavailable``, or every state failed: nothing is written for that call and the next beat retries) or comes back
``timeout`` (the model is busy with chat). Items that timed out are not written and are picked up by the next sweep.
A state that could not be built, or that the model called ``bad_item`` while answering the rest of its call, is
written as an ``_error`` row and not retried until the schema or the model changes. A ``backend_error`` (the runtime
raised, the server refused the item or answered something else) is the backend's fault more often than the item's:
the message (or conversation) gets a ``_retry`` row counting the attempt and is asked again by a later sweep, and
only its ``ATTEMPTS``-th failure is an ``_error``. A call about a single message (or conversation) that answered
nothing tells the two apart only by the sweep's other calls: the message is set aside, and the sweep goes on; it
counts as an attempt once a call of the sweep has answered something, and not while none has, so a backend that
fails everything marks nothing. ``LONE_FAILURES`` conversations of such calls in a row end the pass (the next pass,
finding the backend still failing, ends at its first such call). What is set aside with no call answering gets a
``_retry`` row keeping its count and since when it has been set aside (``parked_since``); a candidate the backend
failed on is asked after those it never failed on, the least recently tried first, so a few messages the backend
always fails on never keep the rest from being labelled, and are counted once the others answer. One set aside
for ``PARKED_HOURS`` counts as an attempt all the same, so with nothing else to answer it still ends as ``_error``.

Every row a state yields records what the state was built from (``source_updated_at``, ``source_hash``: the message's,
or for a conversation's own rows the conversation's, as read), so an edit made while the call ran leaves the labels
stale and the next sweep asks again, while feedback or a finished background job, which change neither, ask nothing.
"""

from __future__ import annotations

import datetime
import logging
import os
import socket
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from sqlalchemy.exc import IntegrityError

from docsgpt import decisions
from docsgpt.analytics import derive, schema, states, topics
from docsgpt.analytics.config import AnalyticsConfig
from docsgpt.celery_init import celery
from docsgpt.core.settings import settings
from docsgpt.decisions import Budget, Request
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversation_labels import (
    ERROR,
    MARKERS,
    RETRY,
    ConversationLabelsRepository,
)
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

LOCK_KEY = "analytics:sweep"
#: Conversations a candidate query returns at a time.
PAGE = 50
#: The digest's period.
DIGEST_DAYS = 7
#: Gap groups a digest names.
DIGEST_GROUPS = 5
#: The share of what is left of a sweep's budget after the pending pass that the message pass may take before the
#: conversation pass runs; the message pass then resumes with whatever the conversation pass leaves.
MESSAGE_SHARE = 0.7
#: Failed attempts on a message or conversation (a ``backend_error``, or a call about it alone that answered
#: nothing while others did) before it is marked ``_error``; each one before is a ``_retry`` row, asked again by the
#: next sweep.
ATTEMPTS = 3
#: Conversations in a row whose calls, each about one message (or conversation), answered nothing before the pass
#: ends: past one or two the backend is failing, not the messages.
LONE_FAILURES = 3
#: Hours a message (or conversation) may be set aside uncounted (it failed alone, and no call of its sweeps
#: answered) before its next such failure counts as an attempt all the same.
PARKED_HOURS = 24
#: Seconds between two checks that the sweep still holds its lock, each extending it.
LOCK_REFRESH_SECONDS = 5
#: Extends the lock only while it holds this sweep's token, so a sweep whose lock ran out never extends another's.
_REFRESH_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
)
#: Deletes the lock only while it holds this sweep's token, so a sweep whose lock ran out never frees another's.
_RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
#: Why a state-less item failed: its state could not be built.
BUILD_FAILED = "build_failed"
#: Reasons a state was not answered that count an attempt on its message (or conversation); the others leave it to
#: the next sweep.
_RETRIED = ("backend_error", "bad_item")

TURN_QUESTIONS = {"answer_status": schema.ANSWER_STATUS, "unanswered_reason": schema.UNANSWERED_REASON}
REACTION_QUESTIONS = {"reaction": schema.REACTION, "frustrated": schema.FRUSTRATED,
                      "asks_human": schema.ASKS_HUMAN, "sentiment": schema.SENTIMENT}
MESSAGE_QUESTIONS = {"request_type": schema.INTENT}


def enabled() -> bool:
    """Whether the operator lets the model label conversations here: the switch, and the harness not off."""
    return bool(settings.DECISION_ANALYTICS_ENABLED) and decisions.get_decider().enabled


@dataclass
class _Item:
    """One state to ask about, and where its rows go; ``state`` is ``None`` when building it failed."""

    conversation_id: str
    user_id: str
    agent_id: Optional[str]
    level: str
    message_id: Optional[str]
    occurred_at: Any
    lang: str
    state: Any = None
    questions: dict = field(default_factory=dict)
    reply_message_id: Optional[str] = None
    hashes: dict = field(default_factory=dict)  # question key to the row's options_hash
    source_updated_at: Any = None  # the source message's (or conversation's) updated_at, as read
    source_hash: Optional[str] = None  # and its content hash, as read
    attempts: int = 0  # backend failures on the source as read (its current _retry row)
    parked_since: Any = None  # and since when it has failed alone uncounted, as read

    @property
    def source(self) -> Optional[str]:
        """The user message the state was built for: the reply, for a reaction; ``None`` for a conversation."""
        return self.reply_message_id or self.message_id

    @property
    def key(self) -> tuple[str, Optional[str]]:
        """What its marker labels: the conversation and the source message (``None`` for the conversation)."""
        return self.conversation_id, self.source


def _asked(items: list[_Item]) -> int:
    """The states among ``items`` that will be asked (not those that failed to build)."""
    return sum(item.state is not None for item in items)


class _Read:
    """The conversations a pass has read this sweep, and those its candidate query must still leave out.

    A conversation read leaves the query by itself once each source the pass built for it (a user message, or the
    conversation: ``None``) has its marker written, so only the rest is excluded: those queued, late, retried or set
    aside, about a call's worth plus what failed, whatever the size of the backfill. One the query returns again all
    the same (a marker stale since it was written: an edit during the call, a model change) is skipped and held out
    from then on, so a pass still reads a conversation once, as when every one read was excluded.
    """

    def __init__(self) -> None:
        self.read: set[str] = set()
        self.open: dict[str, set[Optional[str]]] = {}  # conversation to its sources without a marker written
        self.held: set[str] = set()  # returned again once read: excluded for the rest of the sweep

    def again(self, cid: str) -> bool:
        """Whether ``cid`` was read already, and so is skipped; it is then excluded from the next queries."""
        if cid not in self.read:
            return False
        self.held.add(cid)
        return True

    def add(self, cid: str, sources: Iterable[Optional[str]]) -> None:
        """``cid`` was read, and states built for ``sources``."""
        self.read.add(cid)
        self.open[cid] = set(sources)
        if not self.open[cid]:
            del self.open[cid]

    def written(self, cid: str, source: Optional[str]) -> None:
        """``source``'s marker was written (committed)."""
        sources = self.open.get(cid)
        if sources is not None:
            sources.discard(source)
            if not sources:
                del self.open[cid]

    def discard(self, cid: str) -> None:
        """Forget ``cid``: the pass reads and builds it again."""
        self.read.discard(cid)
        self.open.pop(cid, None)
        self.held.discard(cid)

    def exclude(self) -> set[str]:
        """What the candidate query leaves out."""
        return self.open.keys() | self.held


@dataclass
class _Agent:
    """What the sweep needs of one agent: its analytics settings and topic question."""

    row: dict
    config: AnalyticsConfig
    topic: Optional[dict] = None
    topic_hash: Optional[str] = None
    #: The hash of ``config``'s overlapping topics, as the candidate query computes it for the stored agent.
    tags_hash: Optional[str] = None


class _Lock:
    """The ``analytics:sweep`` lock; with no Redis the sweep runs unlocked (its writes are idempotent upserts)."""

    def __init__(self, ttl: int):
        from docsgpt.cache import get_redis_instance

        self.redis = get_redis_instance()
        self.ttl = ttl
        self.token = f"{socket.gethostname()}:{os.getpid()}:{time.monotonic()}"
        self._checked = time.monotonic()

    def acquire(self) -> bool:
        if self.redis is None:
            return True
        try:
            return bool(self.redis.set(LOCK_KEY, self.token, nx=True, ex=self.ttl))
        except Exception:  # noqa: BLE001 - a Redis outage skips one sweep rather than run uncoordinated
            logger.warning("Analytics sweep skipped: could not take its lock", exc_info=True)
            return False

    def refresh(self) -> bool:
        """Extend the lock while it is still this sweep's, asking Redis at most every ``LOCK_REFRESH_SECONDS``.

        Returns:
            ``False`` once the lock is not this sweep's (it ran out, and maybe another sweep took it); ``True``
            otherwise, also with no Redis or when Redis could not be asked, so an outage does not stop a sweep.
        """
        if self.redis is None:
            return True
        now = time.monotonic()
        if now - self._checked < LOCK_REFRESH_SECONDS:
            return True
        self._checked = now
        try:
            return bool(self.redis.eval(_REFRESH_LUA, 1, LOCK_KEY, self.token, self.ttl))
        except Exception:  # noqa: BLE001
            logger.debug("Analytics sweep: lock refresh failed", exc_info=True)
            return True

    def release(self) -> None:
        if self.redis is None:
            return
        try:
            self.redis.eval(_RELEASE_LUA, 1, LOCK_KEY, self.token)
        except Exception:  # noqa: BLE001
            logger.debug("Analytics sweep: lock release failed", exc_info=True)


def _answer(decision, key: str) -> dict[str, float]:
    """An answer as a row stores it: every option's probability, ``yes``/``no`` for a yes/no question."""
    answer = decision.answers[key]
    if answer["type"] == "noul":
        p = float(answer["noul"])
        return {"yes": p, "no": 1.0 - p}
    return {str(k): float(v) for k, v in answer["probabilities"].items()}


def _top(probabilities: dict[str, float]) -> tuple[Optional[str], Optional[float]]:
    if not probabilities:
        return None, None
    best = max(probabilities, key=probabilities.__getitem__)
    return best, probabilities[best]


class Sweep:
    """One sweep's state: the running schema and model, its deadline, the queued states and its counts.

    Args:
        model_version: The running ``decisions.model_version()``.
        budget_seconds: Seconds it may spend starting calls; ``None`` for no limit (the backfill command).
        days: How far back to label; ``ANALYTICS_BACKFILL_DAYS`` when omitted.
        agent_id: Only this agent's conversations.
        lock: Refreshed as the sweep goes (``_going``), so a long backfill keeps it; once it is another sweep's,
            this one stops (``lock_lost``).
    """

    def __init__(self, model_version: str, budget_seconds: Optional[float] = None, days: Optional[int] = None,
                 agent_id: Optional[str] = None, lock: Optional[_Lock] = None):
        self.model_version = model_version
        self.deadline = None if budget_seconds is None else time.monotonic() + budget_seconds
        self.days = days or settings.ANALYTICS_BACKFILL_DAYS
        self.agent_id = agent_id
        self.lock = lock
        self.stats: Counter = Counter()
        self.stopped: Optional[str] = None
        self._agents: dict[str, Optional[_Agent]] = {}
        # The loaded rows of conversations with states queued (and the one being built), dropped once written
        # (``_release``), so a backfill holds about a call's worth of them.
        self._messages: dict[str, list[states.Message]] = {}
        self._conversations: dict[str, tuple[Any, Optional[str]]] = {}  # (updated_at, hash) as read
        self._queue: list[_Item] = []
        self._started = time.monotonic()
        self._pass_deadline: Optional[float] = None  # the message pass's share of the budget
        self._seen = _Read()  # conversations the message pass has read, across its two turns
        self._seen_conversations = _Read()  # and the conversation pass
        self._late: set[tuple] = set()  # item keys with a state not answered: none of their rows is written
        self._answered = False  # a call of this sweep answered something: the backend works
        self._parked: list[tuple[_Item, str]] = []  # failed alone before that, charged once a call answers
        self._failing: set[str] = set()  # conversations failed alone since a call last answered
        self._cut = False  # LONE_FAILURES of them: the running pass ends
        self._lone_stop: Optional[str] = None  # how the sweep reports parked items no call vouched for

    # ---- control --------------------------------------------------------------------------------------------------

    def _going(self) -> bool:
        """Whether the sweep may go on: not stopped, its budget not spent, and its lock still its own (refreshed)."""
        if self.stopped:
            return False
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.stopped = "budget"
            return False
        if self.lock is not None and not self.lock.refresh():
            logger.warning("Analytics sweep stopped: its lock ran out and is not its own any more")
            self.stopped = "lock_lost"
            return False
        return True

    def _in_pass(self) -> bool:
        """``_going``, the running pass not cut short (``LONE_FAILURES``) and its own share of the budget
        (``MESSAGE_SHARE``) not spent."""
        return (self._going() and not self._cut
                and (self._pass_deadline is None or time.monotonic() < self._pass_deadline))

    @staticmethod
    def _cap() -> int:
        """States per call: ``ANALYTICS_BATCH_STATES``, never more than the decision client takes."""
        return max(1, min(settings.ANALYTICS_BATCH_STATES, settings.DECISION_MAX_BATCH_STATES))

    def run(self) -> dict:
        """The passes, each while the sweep is still going: pending resolutions (no model call), messages until
        ``MESSAGE_SHARE`` of the budget left is spent, conversations, then messages again with what is left; then
        what failed alone with no call answering is set aside (``_park``)."""
        self.pending_pass()
        if self.deadline is not None and self._going():
            now = time.monotonic()
            self._pass_deadline = now + MESSAGE_SHARE * (self.deadline - now)
        for step in (self.message_pass, self.conversation_pass, self.message_pass):
            self._cut = False
            if self._going():
                step()
            self._pass_deadline = None
        if self._parked:  # failed alone and no call answered: the backend's fault, as a stop, unless told apart later
            self.stopped = self.stopped or self._lone_stop
            self._park()
        report = {**{k: self.stats.get(k, 0) for k in (
            "messages", "conversations", "resolutions", "calls", "states", "rows", "errors", "retries", "timeouts",
            "truncated")}, "stopped": self.stopped, "ms": round((time.monotonic() - self._started) * 1000)}
        return report

    # ---- loading --------------------------------------------------------------------------------------------------

    def _agent(self, conn, agent_id: Optional[str]) -> Optional[_Agent]:
        """The agent's analytics settings and topic question, once per sweep."""
        if not agent_id:
            return None
        if agent_id not in self._agents:
            row = AgentsRepository(conn).get_by_id(agent_id)
            agent = None
            if row is not None:
                config = AnalyticsConfig.parse((row.get("config") or {}).get("analytics"))
                agent = _Agent(row=row, config=config,
                               tags_hash=ConversationLabelsRepository(conn).tags_hash(row.get("config")))
                try:
                    options = topics.options(conn, row, config)
                except Exception:  # noqa: BLE001 - a broken source structure costs the topic, not the sweep
                    logger.warning("Analytics: no topic list for agent %s", agent_id, exc_info=True)
                    options = {}
                if options:
                    agent.topic = schema.topic_question(options)
                    agent.topic_hash = topics.options_hash(agent.topic["criteria"])
            self._agents[agent_id] = agent
        return self._agents[agent_id]

    def _load(self, conn, conversation_id: str) -> list[states.Message]:
        """The conversation's user messages, each with its source hash, and the conversation's own source."""
        loaded = ConversationLabelsRepository(conn).source_messages(conversation_id)
        msgs = states.messages(loaded["messages"])
        self._messages[conversation_id] = msgs
        self._conversations[conversation_id] = (loaded["updated_at"], loaded["hash"])
        return msgs

    def _release(self) -> None:
        """Drop the loaded rows of every conversation with nothing queued; ``_write_group`` loads any it needs."""
        queued = {item.conversation_id for item in self._queue}
        for cache in (self._messages, self._conversations):
            for cid in cache.keys() - queued:
                del cache[cid]

    # ---- message pass ---------------------------------------------------------------------------------------------

    def message_pass(self) -> None:
        """Label unlabelled messages, a conversation at a time, in ``message_candidates`` order.

        The pass's share is checked before every message, so one long conversation cannot spend the conversation
        pass's time. A conversation it ends in, and every conversation with states still queued, is left unseen with
        nothing queued, so the pass's next turn builds what is still unlabelled of it again.
        """
        cap = self._cap()
        while self._in_pass():
            with db_readonly() as conn:
                candidates = ConversationLabelsRepository(conn).message_candidates(
                    schema.SCHEMA_HASH, self.model_version, self.days, settings.ANALYTICS_TURN_SETTLE_SECONDS,
                    PAGE, agent_id=self.agent_id, exclude=self._seen.exclude(),
                )
            if not candidates:
                break
            for candidate in candidates:
                cid = candidate["conversation_id"]
                if self._seen.again(cid):
                    continue
                with db_readonly() as conn:
                    groups = self._message_items(conn, candidate)
                self._seen.add(cid, (group[0].source for group in groups))
                for group in groups:
                    if not self._in_pass():
                        self._seen.discard(cid)
                        break
                    # a message's states go in one call where the cap allows, so its marker is written with the rest
                    if self._queue and _asked(self._queue) + _asked(group) > cap:
                        self._flush("analytics_turn")
                    self._queue.extend(group)
                    if _asked(self._queue) >= cap:
                        self._flush("analytics_turn")
                self._release()
                if not self._in_pass():
                    break
        if self._queue:  # built already: asked while the pass may still call
            self._flush("analytics_turn")
        for item in self._queue:  # not asked: its conversation is built again by the next turn
            self._seen.discard(item.conversation_id)
        self._queue = []
        self._release()

    def _message_items(self, conn, candidate: dict) -> list[list[_Item]]:
        """The states of a conversation's unlabelled messages, one group per message; the request type is last,
        since its row marks the message labelled.

        A message the candidate query counts as unlabelled but ``states.messages`` leaves out (the two disagree
        on what is a user message) gets a state-less item, written as an ``_error`` marker, so it is never a
        candidate again and the message pass always ends.
        """
        cid = candidate["conversation_id"]
        unlabelled = ConversationLabelsRepository(conn).unlabelled_messages(
            cid, schema.SCHEMA_HASH, self.model_version, self.days, settings.ANALYTICS_TURN_SETTLE_SECONDS
        )
        agent = self._agent(conn, candidate["agent_id"])
        msgs = self._load(conn, cid)
        groups: list[list[_Item]] = []
        owner = dict(conversation_id=cid, user_id=candidate["user_id"], agent_id=candidate["agent_id"])
        for i, m in enumerate(msgs):
            if m.id not in unlabelled:
                continue
            base = dict(owner, message_id=m.id, occurred_at=m.timestamp, lang=states.lang(m.prompt),
                        source_updated_at=m.updated_at, source_hash=m.source_hash,
                        attempts=unlabelled[m.id].get("attempts") or 0,
                        parked_since=unlabelled[m.id].get("parked_since"))
            plan: list[tuple[str, Callable[[], Any], dict, dict]] = []
            if m.is_turn:
                plan.append(("turn", lambda i=i: states.turn(msgs, i), TURN_QUESTIONS, {}))
            if i and msgs[i - 1].is_turn:
                plan.append(("reaction", lambda i=i: states.reaction(msgs, i), REACTION_QUESTIONS, {}))
            if agent is not None and agent.topic is not None:
                plan.append(("message", lambda i=i: states.topic(msgs, i), {"topic": agent.topic},
                             {"topic": agent.topic_hash}))
            plan.append(("message", lambda i=i: states.message(msgs, i), MESSAGE_QUESTIONS, {}))
            items: list[_Item] = []
            for level, build, questions, hashes in plan:
                item = _Item(level=level, questions=questions, hashes=hashes, **base)
                if level == "reaction":  # sits on the answer reacted to, and names the reply it read
                    item.message_id, item.reply_message_id = msgs[i - 1].id, m.id
                try:
                    item.state = build()
                except Exception:  # noqa: BLE001 - written as an _error row, never retried for this schema
                    logger.warning("Analytics: could not build a %s state for message %s", level, m.id,
                                   exc_info=True)
                items.append(item)
            groups.append(items)
        for message_id in unlabelled.keys() - {m.id for m in msgs}:
            row = unlabelled[message_id]
            logger.warning("Analytics: message %s is a candidate but not a user message; marked as an error",
                           message_id)
            groups.append([_Item(level="message", message_id=message_id, occurred_at=row["timestamp"], lang="en",
                                 source_updated_at=row["updated_at"], source_hash=row["source_hash"], **owner)])
        return groups

    # ---- conversation pass ----------------------------------------------------------------------------------------

    def conversation_pass(self) -> None:
        """Ask goal met and the agent's tags of every idle conversation that needs them."""
        seen = self._seen_conversations
        cap = self._cap()
        while self._in_pass():
            with db_readonly() as conn:
                candidates = ConversationLabelsRepository(conn).conversation_candidates(
                    schema.SCHEMA_HASH, self.model_version, self.days, settings.ANALYTICS_CONVERSATION_IDLE_MINUTES,
                    PAGE, agent_id=self.agent_id, exclude=seen.exclude(),
                )
            if not candidates:
                break
            for candidate in candidates:
                if seen.again(candidate["conversation_id"]):
                    continue
                seen.add(candidate["conversation_id"], (None,))
                with db_readonly() as conn:
                    item = self._conversation_item(conn, candidate)
                self._queue.append(item)
                if _asked(self._queue) >= cap:
                    self._flush("analytics_conversation")
                self._release()
                if not self._in_pass():
                    break
        if self._queue:
            self._flush("analytics_conversation")
        self._queue = []  # what the budget left unasked: the next sweep asks it
        self._release()

    def _conversation_item(self, conn, candidate: dict) -> _Item:
        """The conversation's state; a state-less item, written as an ``_error`` marker, when the candidate query
        counts user messages the states leave out, so it is never a candidate again and the pass always ends."""
        cid = candidate["conversation_id"]
        msgs = self._load(conn, cid)
        updated_at, source_hash = self._conversations[cid]
        owner = dict(conversation_id=cid, user_id=candidate["user_id"], agent_id=candidate["agent_id"],
                     level="conversation", message_id=None, source_updated_at=updated_at, source_hash=source_hash,
                     attempts=candidate.get("attempts") or 0, parked_since=candidate.get("parked_since"))
        if not msgs:
            logger.warning("Analytics: conversation %s is a candidate but has no user message; marked as an error",
                           cid)
            return _Item(occurred_at=candidate["last_at"], lang="en", **owner)
        agent = self._agent(conn, candidate["agent_id"])
        if agent is not None and agent.tags_hash != candidate["tags_hash"]:
            # Its topics changed since the sweep read it: read it again, so this conversation is asked them.
            self._agents.pop(candidate["agent_id"], None)
            agent = self._agent(conn, candidate["agent_id"])
        questions = {"goal_met": schema.GOAL_MET}
        # The hash of the topics asked, so a change after they were read leaves the row stale, asked again.
        hashes = {"goal_met": agent.tags_hash if agent is not None else candidate["tags_hash"]}
        # An overlapping topic is asked in the model's trained tag form; without a description, by its name.
        for topic in agent.config.overlapping() if agent is not None else []:
            description = topic.description or topic.name
            questions[f"tag:{topic.id}"] = schema.tag_question(topic.name, description)
            hashes[f"tag:{topic.id}"] = topics.options_hash([topic.name, description])
        item = _Item(occurred_at=msgs[-1].timestamp, lang=states.lang("\n".join(m.prompt for m in msgs)),
                     questions=questions, hashes=hashes, **owner)
        try:
            item.state = states.conversation(msgs)
        except Exception:  # noqa: BLE001
            logger.warning("Analytics: could not build the state of conversation %s", cid, exc_info=True)
        return item

    # ---- pending pass ---------------------------------------------------------------------------------------------

    def pending_pass(self) -> None:
        """Settle resolutions still pending once their conversation is past the window; no model call.

        One that cannot be recomputed (no user message left, or no ``goal_met``) is deleted with its experience,
        so it is not loaded again every sweep; the conversation pass writes both again with ``goal_met``. Either
        way it is no candidate after, so none is excluded unless the query returns it again.
        """
        seen = _Read()
        while self._going():
            with db_readonly() as conn:
                candidates = ConversationLabelsRepository(conn).pending_resolutions(
                    schema.SCHEMA_HASH, self.model_version, settings.ANALYTICS_RESOLUTION_WINDOW_HOURS, PAGE,
                    agent_id=self.agent_id, exclude=seen.exclude(),
                )
            if not candidates:
                break
            for candidate in candidates:
                if not self._going():
                    break
                cid = candidate["conversation_id"]
                if seen.again(cid):
                    continue
                seen.add(cid, ())
                try:
                    with db_session() as conn:
                        repo = ConversationLabelsRepository(conn)
                        rows = self._conversation_rows(conn, candidate, self._load(conn, cid))
                        if rows:
                            repo.upsert_many(rows)
                        else:
                            repo.delete_outcome(cid)
                except IntegrityError:  # deleted meanwhile, as in ``_write``
                    logger.debug("Analytics: conversation %s changed while it was settled; skipped", cid)
                    rows = []
                self._release()
                if rows:
                    self.stats["resolutions"] += 1
                    self.stats["rows"] += len(rows)

    # ---- calls and writes -----------------------------------------------------------------------------------------

    def _flush(self, feature: str) -> None:
        """Ask the queued states, at most ``_cap()`` to a call, while the pass may, and write what came back; what
        it may not ask stays queued.

        A message with more states than the cap is split across calls, in order, so its marker (the request type,
        its last state) comes last and is skipped if an earlier part was not answered (``_late``).
        """
        batch, self._queue = self._queue, []
        cap = self._cap()
        while batch and self._in_pass():
            chunk, asked = [], 0
            while batch and (asked < cap or batch[0].state is None):
                item = batch.pop(0)
                chunk.append(item)
                asked += item.state is not None
            self._call(chunk, feature)
        self._queue = batch

    def _call(self, batch: list[_Item], feature: str) -> None:
        """Ask one call's states and write what came back; see the module docstring for what each outcome writes.

        A state not answered keeps every row of its message (or conversation) out of this call and of the
        sweep's later ones, so a marker is never written without the rest, except a ``bad_item`` in a call that
        answered others, which is the item's own fault and written as an ``_error`` beside its other rows.

        A call about one message (or conversation) that answered nothing (``backend_error`` or ``bad_item``) does
        not stop the sweep: the message is charged the attempt if a call of the sweep has answered, else parked and
        charged when one does (``_charge``), or set aside at the end of the sweep (``_park``). ``LONE_FAILURES``
        conversations failing so in a row end the pass.
        """
        batch = [item for item in batch if item.key not in self._late]
        asked = [item for item in batch if item.state is not None]
        outcome: dict[int, tuple[Any, Optional[str]]] = {}
        answered = False
        if asked:
            result = decisions.decide_batch([Request(i.state, i.questions) for i in asked], feature=feature,
                                            budget=Budget.BACKGROUND)
            self.stats["calls"] += 1
            self.stats["states"] += len(asked)
            outcome = {id(item): (decision, reason) for item, decision, reason in zip(asked, result, result.reasons)}
            answered = any(decision is not None for decision in result)
            lone = len({item.key for item in asked}) == 1
            if answered:
                self._answered = True
                self._failing.clear()
            if result.status == "timeout":
                self.stopped = "timeout"
            elif not answered:  # the backend's fault, unless the call was about one message alone
                stop = "unavailable" if result.status == "unavailable" else "failed"
                reasons = {r for r in result.reasons if r}
                if lone and reasons <= set(_RETRIED):  # the message's fault or the backend's: _charge tells
                    self._failing.add(asked[0].conversation_id)
                    self._lone_stop = stop
                    if len(self._failing) >= LONE_FAILURES:
                        self._cut = True
                else:
                    self.stopped = stop
                if self.stopped or self._cut:
                    logger.info("Analytics sweep %s: the decision model answered nothing (%s)",
                                "stopped" if self.stopped else "pass ended", ", ".join(sorted(reasons)))
                if not lone:
                    return
            version = next((d.model.version for d in result if d is not None), self.model_version)
            if version != self.model_version:  # the server changed models: label as the one that answered
                logger.info("Analytics sweep: model version changed from %s to %s", self.model_version, version)
                self.model_version = version
        # Per key, why its states were not all answered: an attempt to count ("retry") or nothing to write ("late").
        failed: dict[tuple, str] = {}
        first: dict[tuple, _Item] = {}
        for item in asked:
            decision, reason = outcome[id(item)]
            if decision is not None or (reason == "bad_item" and answered):
                continue
            kind = "retry" if reason in _RETRIED else "late"
            if failed.get(item.key) != "retry":
                failed[item.key], first[item.key] = kind, item
            if kind == "late":
                self.stats["timeouts"] += 1
        rows: list[dict] = []
        for item in batch:
            if item.key in failed:
                continue
            decision, reason = outcome.get(id(item), (None, BUILD_FAILED))
            if decision is not None:
                self.stats["truncated"] += int(decision.truncated)
                rows.extend(self._rows(item, decision))
            else:  # its state could not be built, or the model called it bad while answering the rest
                self.stats["errors"] += 1
                rows.append(self._marker(item, ERROR, reason))
        retried = [(first[key], outcome[id(first[key])][1]) for key, kind in failed.items() if kind == "retry"]
        if self._answered:
            rows += [self._charge(item, reason) for item, reason in retried]
        else:  # no call has answered yet: a failing backend, or the messages; told apart by the calls to come
            self._parked += retried
        self._late |= failed.keys()
        self._commit(rows, feature == "analytics_conversation")
        if self._answered and self._parked:  # the backend answers after all: what failed alone before is charged
            charged, self._parked = [self._charge(item, reason) for item, reason in self._parked], []
            for conversation_level in (False, True):
                self._commit([row for row in charged if (row["level"] == "conversation") == conversation_level],
                             conversation_level)

    def _park(self) -> None:
        """Write what failed alone while no call of the sweep answered: a ``_retry`` row keeping its count, naming
        since when it has been set aside (``parked_since``), so later sweeps ask it after the rest; or, set aside
        ``PARKED_HOURS`` already, the attempt counted all the same (``_charge``)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        rows = []
        for item, reason in self._parked:
            since = item.parked_since
            if since is not None and now - since >= datetime.timedelta(hours=PARKED_HOURS):
                rows.append(self._charge(item, reason))
            else:  # written again all the same, so its created_at says when it was last tried
                since = (since or now).isoformat()
                rows.append(self._marker(item, RETRY, reason, {"attempts": item.attempts, "parked_since": since}))
        self._parked = []
        for conversation_level in (False, True):
            self._commit([row for row in rows if (row["level"] == "conversation") == conversation_level],
                         conversation_level)

    def _charge(self, item: _Item, reason: Optional[str]) -> dict:
        """The row of a failed attempt on ``item``: a ``_retry`` counting it, or at the ``ATTEMPTS``-th an
        ``_error``."""
        attempts = item.attempts + 1
        if attempts >= ATTEMPTS:
            self.stats["errors"] += 1
            return self._marker(item, ERROR, reason)
        self.stats["retries"] += 1
        return self._marker(item, RETRY, reason, {"attempts": attempts})

    def _commit(self, rows: list[dict], conversation_level: bool) -> None:
        """Count rows as written, so a message queued when the budget ran out is not, and write them."""
        if conversation_level:
            done = {r["conversation_id"] for r in rows if r["label"] in ("goal_met", ERROR)}
            self.stats["conversations"] += len(done)
        else:
            self.stats["messages"] += len({r["message_id"] for r in rows if r["label"] in MARKERS})
        self._write(rows, conversation_level)

    def _marker(self, item: _Item, label: str, reason: Optional[str], probabilities: Optional[dict] = None) -> dict:
        """An ``_error`` or ``_retry`` row naming ``reason``, on the user message the state was built for (where it
        marks that message) or on the conversation."""
        row = self._row(item, label=label, probabilities=probabilities or {}, top=reason)
        row.update(message_id=item.source, reply_message_id=None)
        return row

    def _row(self, item: _Item, *, label: str, probabilities: dict, top: Optional[str] = None,
             p_top: Optional[float] = None) -> dict:
        return {
            "conversation_id": item.conversation_id, "message_id": item.message_id,
            "reply_message_id": item.reply_message_id, "user_id": item.user_id, "agent_id": item.agent_id,
            "level": item.level, "label": label, "top": top, "p_top": p_top, "probabilities": probabilities,
            "derived": False, "lang": item.lang, "options_hash": item.hashes.get(label),
            "schema_hash": schema.SCHEMA_HASH, "model_version": self.model_version,
            "occurred_at": item.occurred_at, "source_updated_at": item.source_updated_at,
            "source_hash": item.source_hash,
        }

    def _rows(self, item: _Item, decision) -> list[dict]:
        rows = []
        for key in item.questions:
            probabilities = _answer(decision, key)
            top, p_top = _top(probabilities)
            rows.append(self._row(item, label=key, probabilities=probabilities, top=top, p_top=p_top))
        return rows

    def _write(self, rows: list[dict], conversation_level: bool) -> None:
        """Write a call's rows and its conversations' derived rows: in one transaction, or, when a message went
        away meanwhile (a retry truncated it), one conversation at a time, skipping the gone one."""
        groups: dict[str, list[dict]] = {}
        for row in rows:
            groups.setdefault(row["conversation_id"], []).append(row)
        if not groups:
            return
        try:
            with db_session() as conn:
                for cid, group in groups.items():
                    self._write_group(conn, cid, group, conversation_level)
            self._written(rows, conversation_level)
            return
        except IntegrityError:
            logger.info("Analytics: a labelled message changed while the sweep ran; writing conversations singly")
        for cid, group in groups.items():
            try:
                with db_session() as conn:
                    self._write_group(conn, cid, group, conversation_level)
                self._written(group, conversation_level)
            except IntegrityError:
                logger.debug("Analytics: conversation %s changed while it was labelled; skipped", cid)

    def _written(self, rows: list[dict], conversation_level: bool) -> None:
        """Tell the pass's ``_Read`` which markers ``rows`` committed, so their conversations leave its exclusion."""
        seen, markers = (self._seen_conversations, ("goal_met", ERROR)) if conversation_level else (self._seen, MARKERS)
        for row in rows:
            if row["label"] in markers:
                seen.written(row["conversation_id"], row["message_id"])

    def _write_group(self, conn, cid: str, rows: list[dict], conversation_level: bool) -> None:
        repo = ConversationLabelsRepository(conn)
        self.stats["rows"] += repo.upsert_many(rows)
        if conversation_level and any(row["label"] == "goal_met" for row in rows):
            repo.delete_conversation_tags(cid, [row["label"] for row in rows if row["label"].startswith("tag:")])
        # Labelled now: the attempts counted before belong to an episode that ended.
        done = {row["message_id"] for row in rows if row["label"] in ("goal_met", "request_type")}
        done -= {row["message_id"] for row in rows if row["label"] in (RETRY, ERROR)}
        if done:
            repo.delete_retries(cid, done)
        msgs = self._messages.get(cid) or self._load(conn, cid)
        labels = self._labels(conn, cid)
        derived = self._message_rows(conn, cid, rows[0], msgs, labels)
        if conversation_level:
            derived += self._conversation_rows(conn, rows[0], msgs, labels)
        # Every call recomputes the conversation's derived rows; writing only those that changed keeps a long
        # conversation from rewriting all of them on each of its calls.
        derived = [row for row in derived if not _unchanged(row, labels)]
        if derived:
            self.stats["rows"] += repo.upsert_many(derived)

    # ---- derived rows ---------------------------------------------------------------------------------------------

    def _labels(self, conn, cid: str) -> dict[tuple[Optional[str], str], dict]:
        rows = ConversationLabelsRepository(conn).for_conversation(cid, schema.SCHEMA_HASH, self.model_version)
        return {(row["message_id"], row["label"]): row for row in rows}

    @staticmethod
    def _owned(ref: dict, labels: dict) -> dict:
        """``ref`` under the agent its conversation's labels were written under, once that agent is gone.

        A deleted agent leaves its conversations with no agent, but their labels keep its id, so a user's own
        views hide them (they name its owner's topics). Rows derived from them later keep that id too, rather
        than turn into rows of no agent that those views read.
        """
        if ref["agent_id"]:
            return ref
        owner = next((row["agent_id"] for row in labels.values() if row.get("agent_id")), None)
        return {**ref, "agent_id": owner} if owner else ref

    @staticmethod
    def _replies(labels: dict, label: str) -> dict[str, dict[str, float]]:
        """Reaction-level probabilities by the reply message they describe."""
        return {row["reply_message_id"]: row["probabilities"] for (_, name), row in labels.items()
                if name == label and row["reply_message_id"]}

    def _message_rows(self, conn, cid: str, ref: dict, msgs: list[states.Message],
                      labels: Optional[dict] = None) -> list[dict]:
        """``gap_type`` of every labelled turn and ``topic_effective`` of every message with a topic, from
        ``labels`` (the conversation's, read when not given)."""
        labels = self._labels(conn, cid) if labels is None else labels
        ref = self._owned(ref, labels)
        out = []
        for m in msgs:
            status = labels.get((m.id, "answer_status"))
            if status is None or status["derived"]:
                continue
            reason = labels.get((m.id, "unanswered_reason"))
            gap = derive.gap_type(status["probabilities"], reason["probabilities"] if reason else None, None,
                                  states.retrieval_relevance(m), None)
            out.append(self._derived(ref, m, "turn", "gap_type", gap, status["lang"]))
        reactions = self._replies(labels, "reaction")
        own = [labels.get((m.id, "topic")) for m in msgs]
        series = topics.effective_topics([
            (row["probabilities"] if row else None, row["options_hash"] if row else None, reactions.get(m.id))
            for m, row in zip(msgs, own)
        ])
        for m, row, effective in zip(msgs, own, series):
            if effective is not None:
                out.append(self._derived(ref, m, "message", "topic_effective", effective, row["lang"],
                                         options_hash=row["options_hash"]))
        return out

    def _derived(self, ref: dict, m: Optional[states.Message], level: str, label: str, probabilities: dict,
                 lang: Optional[str], options_hash: Optional[str] = None, top: Any = None,
                 p_top: Optional[float] = None) -> dict:
        if top is None:
            top, p_top = _top(probabilities)
        return {
            "conversation_id": ref["conversation_id"], "message_id": m.id if m else None, "reply_message_id": None,
            "user_id": ref["user_id"], "agent_id": ref["agent_id"], "level": level, "label": label, "top": top,
            "p_top": p_top, "probabilities": probabilities, "derived": True, "lang": lang,
            "options_hash": options_hash, "schema_hash": schema.SCHEMA_HASH, "model_version": self.model_version,
            "occurred_at": m.timestamp if m else ref["occurred_at"],
        }

    def _conversation_rows(self, conn, ref: dict, msgs: list[states.Message],
                           labels: Optional[dict] = None) -> list[dict]:
        """``resolution`` and ``experience`` from the stored labels (``labels``, read when not given); none
        before ``goal_met`` exists."""
        if not msgs:
            return []
        labels = self._labels(conn, ref["conversation_id"]) if labels is None else labels
        goal = labels.get((None, "goal_met"))
        if goal is None:
            return []
        reactions, asks, frustrated = (self._replies(labels, k) for k in ("reaction", "asks_human", "frustrated"))
        turns = []
        for m in msgs:
            status = labels.get((m.id, "answer_status"))
            turns.append(derive.Turn(
                answer_status=status["probabilities"] if status else {},
                reaction=reactions.get(m.id),
                asks_human=asks.get(m.id, {}).get("yes", 0.0),
                frustrated=frustrated.get(m.id, {}).get("yes", 0.0),
            ))
        ungrounded = [labels[(m.id, "gap_type")]["probabilities"].get("confidently ungrounded", 0.0)
                      for m in msgs if (m.id, "gap_type") in labels]
        last = msgs[-1].timestamp
        idle = (datetime.datetime.now(datetime.timezone.utc) - last).total_seconds() / 3600 if last else 0.0
        conversation = derive.Conversation(turns, goal_met=goal["probabilities"].get("yes", 0.0), idle_hours=idle,
                                           window_hours=settings.ANALYTICS_RESOLUTION_WINDOW_HOURS,
                                           confidently_ungrounded=ungrounded)
        resolution = derive.resolution(conversation)
        experience = derive.experience(conversation, resolution)
        ref = {**self._owned(ref, labels), "occurred_at": last}
        return [
            self._derived(ref, None, "conversation", "resolution", resolution, goal["lang"]),
            # not a distribution: the score and each component's contribution
            self._derived(ref, None, "conversation", "experience", experience, goal["lang"], top="score",
                          p_top=experience["score"]),
        ]


#: What a derived row's value is: a stored row equal in these needs no write.
_DERIVED_VALUE = ("level", "top", "p_top", "probabilities", "lang", "options_hash", "occurred_at", "agent_id")


def _unchanged(row: dict, labels: dict) -> bool:
    """Derived ``row`` is stored as it is, among the conversation's ``labels``."""
    stored = labels.get((row["message_id"], row["label"]))
    return stored is not None and stored["derived"] and all(stored.get(k) == row[k] for k in _DERIVED_VALUE)


def sweep(budget_seconds: Optional[float] = None, days: Optional[int] = None,
          agent_id: Optional[str] = None) -> dict:
    """Run one sweep, under the lock; see the module docstring.

    Args:
        budget_seconds: Seconds it may spend starting calls; ``None`` for no limit.
        days: How far back to label; ``ANALYTICS_BACKFILL_DAYS`` when omitted.
        agent_id: Only this agent's conversations.

    Returns:
        The counts logged for the sweep, or ``{"skipped": reason}``.
    """
    if not enabled():
        return {"skipped": "disabled"}
    if not settings.POSTGRES_URI:
        return {"skipped": "POSTGRES_URI not set"}
    model_version = decisions.model_version()
    if model_version is None:
        return {"skipped": "no_model"}
    budget = budget_seconds if budget_seconds is not None else settings.ANALYTICS_SWEEP_BUDGET_SECONDS
    lock = _Lock(int(budget + settings.DECISION_BACKGROUND_TIMEOUT + 60))
    if not lock.acquire():
        return {"skipped": "locked"}
    try:
        report = Sweep(model_version, budget_seconds, days, agent_id, lock).run()
    finally:
        lock.release()
    logger.info("analytics_sweep", extra={"analytics": report, "model_version": model_version})
    return report


@celery.task(bind=True, acks_late=False)
def analytics_sweep(self):
    """Beat task: one time-budgeted sweep; returns at once while ``DECISION_ANALYTICS_ENABLED`` is off."""
    return sweep(budget_seconds=settings.ANALYTICS_SWEEP_BUDGET_SECONDS)


@celery.task(bind=True, acks_late=False)
def cleanup_conversation_labels(self):
    """Delete ``conversation_labels`` rows older than ``ANALYTICS_RETENTION_DAYS``, by message time."""
    if not settings.POSTGRES_URI:
        return {"deleted": 0, "skipped": "POSTGRES_URI not set"}
    days = settings.ANALYTICS_RETENTION_DAYS
    with db_session() as conn:
        deleted = ConversationLabelsRepository(conn).purge_older_than(days)
    return {"deleted": deleted, "ttl_days": days}


def _count(value: float) -> str:
    return f"{value:.1f}" if value < 10 else f"{value:.0f}"


def gap_digest(now: Optional[datetime.datetime] = None) -> dict:
    """Notify each owner whose agent has analytics and the digest on of its last week's docs gaps.

    The notification (kind ``docs_gaps``) is titled with the agent's name; its body is the top gap topics and
    their expected counts (owner text and numbers only, so the app words it), or the total for an agent without
    topics; Open goes to the agent's docs-gap table. An agent with under half an expected gap gets none.

    Returns:
        ``{"sent": n}``, or ``{"skipped": reason}``.
    """
    if not enabled():
        return {"skipped": "disabled"}
    if not settings.POSTGRES_URI:
        return {"skipped": "POSTGRES_URI not set"}
    from docsgpt.notifications.notify import notify_user

    now = now or datetime.datetime.now(datetime.timezone.utc)
    since = now - datetime.timedelta(days=DIGEST_DAYS)
    sent = 0
    with db_readonly() as conn:
        repo = ConversationLabelsRepository(conn)
        agents = repo.digest_agents()
        reports = [(agent, repo.docs_gaps(agent["id"], schema.SCHEMA_HASH, since, now)) for agent in agents]
    for agent, gaps in reports:
        if gaps["expected"] < 0.5:
            continue
        top = sorted(gaps["topics"].items(), key=lambda kv: (-kv[1], kv[0]))
        top = [(name, value) for name, value in top if name != schema.NONE_OPTION and value >= 0.5][:DIGEST_GROUPS]
        body = " · ".join(f"{name} {_count(value)}" for name, value in top) or _count(gaps["expected"])
        notify_user(user_id=agent["user_id"], conversation_id=None, kind="docs_gaps", title=agent["name"],
                    body=body, url=f"/agents/manage/insights/{agent['id']}#docs-gaps")
        sent += 1
    return {"sent": sent}


@celery.task(bind=True, acks_late=False)
def analytics_gap_digest(self):
    """Weekly beat task: ``gap_digest``."""
    return gap_digest()


def backfill_estimate(days: int, agent_id: Optional[str] = None) -> dict:
    """What ``docsgpt analytics backfill --dry-run`` prints: the candidates and a time estimate.

    The estimate is one analytics turn call (``latency.ANALYTICS``) per unlabelled turn, as measured where the
    model runs; ``None`` until it has been measured. Wall time is longer at background priority.

    A message counts when it has no label from the model a real run would label with. In API mode that is the
    model the decision server runs, which the client knows only once the server has told it, so the server is
    asked once (``GET /v1/models``, as ``docsgpt decisions status`` does); before that the client assumes the
    registry's default for a server, and labels another model wrote would all count. If the server does not
    answer, the counts keep that assumption and ``warning`` says so.

    Args:
        days: How many days back to count.
        agent_id: Count only this agent's conversations.

    Returns:
        The counts (``messages``, ``conversations``, ``turns``), the ``model_version`` they were counted against,
        the timing estimate, and ``warning`` when the decision server did not answer.
    """
    from docsgpt.decisions.latency import ANALYTICS

    decider = decisions.get_decider()
    answered = decider.probe()
    model_version = decider.model_version()
    with db_readonly() as conn:
        counts = ConversationLabelsRepository(conn).count_message_candidates(
            schema.SCHEMA_HASH, model_version or "", days, agent_id=agent_id
        )
    per_turn = decisions.predict_s(ANALYTICS)
    compute = None if per_turn is None else round(per_turn * counts["turns"], 1)
    report = {
        "enabled": enabled(), "days": days, "agent_id": agent_id, **counts, "model_version": model_version,
        "seconds_per_turn": None if per_turn is None else round(per_turn, 3),
        "estimated_compute_s": compute,
        "estimated_wall_s": None if compute is None else round(compute / settings.DECISION_BACKGROUND_SHARE, 1),
    }
    if answered is False:
        report["warning"] = (f"The decision server did not answer, so the counts assume it runs {model_version}; "
                             "messages labelled by the model it does run are counted as unlabelled.")
    return report
