"""The analytics sweep: labels stored conversations in the background, newest first, into ``conversation_labels``.

A beat task every ``ANALYTICS_SWEEP_SECONDS`` on its own queue (``ANALYTICS_QUEUE``), kept out of
``docsgpt/api/user/tasks.py`` for the reason ``embeddings_tasks.py`` gives: a worker that imports it should not
import the parsing stack. Nothing runs in the request path. The worker reads rows, builds states and writes labels;
its model calls go through the decision client with ``Budget.BACKGROUND``, so they reach the decider sidecar, the
API process's model or the remote endpoint at background priority, and no worker loads a model.

One sweep, under a Redis lock so overlapping beats and several workers are safe:

1. **Message pass.** Unlabelled messages (``ConversationLabelsRepository.message_candidates``), a conversation at a
   time, newest first: per message its turn, the reaction to the answer before it, its topic (the one-pick question
   over the agent's own topics and source folders) and its request type,
   batched ``ANALYTICS_BATCH_STATES`` states to a call. Each batch's rows, and the derived ``gap_type`` and
   ``topic_effective`` rows of its conversations, are written in one transaction.
2. **Conversation pass.** Idle conversations without current ``goal_met``: goal met and every topic that can overlap
   (a ``tag:<id>`` label) in one request, then the derived ``resolution`` and ``experience``. Changing the topics
   that can overlap asks it again; changing the others does not.
3. **Pending pass.** ``resolution`` recomputed, without a model call, once a pending conversation passes the window.

It stops starting calls when its time budget is spent, when a call comes back ``unavailable`` (nothing is written for
that call; the next beat retries) or ``timeout`` (the model is busy with chat). Items that timed out are not written
and are picked up by the next sweep; a state that could not be built, or came back ``bad_item``, is written as an
``_error`` row and not retried until the schema or the model changes.

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
from typing import Any, Callable, Optional

from sqlalchemy.exc import IntegrityError

from docsgpt import decisions
from docsgpt.analytics import derive, schema, states, topics
from docsgpt.analytics.config import AnalyticsConfig
from docsgpt.celery_init import celery
from docsgpt.core.settings import settings
from docsgpt.decisions import Budget, Request
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversation_labels import ERROR, ConversationLabelsRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

LOCK_KEY = "analytics:sweep"
#: Conversations a candidate query returns at a time.
PAGE = 50
#: The digest's period.
DIGEST_DAYS = 7
#: Gap groups a digest names.
DIGEST_GROUPS = 5

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

    @property
    def source(self) -> Optional[str]:
        """The user message the state was built for: the reply, for a reaction; ``None`` for a conversation."""
        return self.reply_message_id or self.message_id


def _asked(items: list[_Item]) -> int:
    """The states among ``items`` that will be asked (not those that failed to build)."""
    return sum(item.state is not None for item in items)


@dataclass
class _Agent:
    """What the sweep needs of one agent: its analytics settings and topic question."""

    row: dict
    config: AnalyticsConfig
    topic: Optional[dict] = None
    topic_hash: Optional[str] = None


class _Lock:
    """The ``analytics:sweep`` lock; with no Redis the sweep runs unlocked (its writes are idempotent upserts)."""

    def __init__(self, ttl: int):
        from docsgpt.cache import get_redis_instance

        self.redis = get_redis_instance()
        self.ttl = ttl
        self.token = f"{socket.gethostname()}:{os.getpid()}:{time.monotonic()}"

    def acquire(self) -> bool:
        if self.redis is None:
            return True
        try:
            return bool(self.redis.set(LOCK_KEY, self.token, nx=True, ex=self.ttl))
        except Exception:  # noqa: BLE001 - a Redis outage skips one sweep rather than run uncoordinated
            logger.warning("Analytics sweep skipped: could not take its lock", exc_info=True)
            return False

    def refresh(self) -> None:
        if self.redis is not None:
            try:
                self.redis.expire(LOCK_KEY, self.ttl)
            except Exception:  # noqa: BLE001
                logger.debug("Analytics sweep: lock refresh failed", exc_info=True)

    def release(self) -> None:
        if self.redis is None:
            return
        try:
            held = self.redis.get(LOCK_KEY)
            if (held.decode() if isinstance(held, bytes) else held) == self.token:
                self.redis.delete(LOCK_KEY)
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
        lock: Refreshed after every call, so a long backfill keeps it.
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
        self._messages: dict[str, list[states.Message]] = {}
        self._conversations: dict[str, tuple[Any, Optional[str]]] = {}  # (updated_at, hash) as read
        self._queue: list[_Item] = []
        self._started = time.monotonic()

    # ---- control --------------------------------------------------------------------------------------------------

    def _going(self) -> bool:
        if self.stopped:
            return False
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.stopped = "budget"
            return False
        return True

    def run(self) -> dict:
        """The three passes, in order, each while the sweep is still going."""
        self.message_pass()
        if self._going():
            self.conversation_pass()
        if self._going():
            self.pending_pass()
        report = {**{k: self.stats.get(k, 0) for k in (
            "messages", "conversations", "resolutions", "calls", "states", "rows", "errors", "timeouts",
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
                agent = _Agent(row=row, config=config)
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

    # ---- message pass ---------------------------------------------------------------------------------------------

    def message_pass(self) -> None:
        """Label unlabelled messages, the conversation with the newest one first."""
        seen: set[str] = set()
        while self._going():
            with db_readonly() as conn:
                candidates = ConversationLabelsRepository(conn).message_candidates(
                    schema.SCHEMA_HASH, self.model_version, self.days, settings.ANALYTICS_TURN_SETTLE_SECONDS,
                    PAGE, agent_id=self.agent_id, exclude=seen,
                )
            if not candidates:
                break
            for candidate in candidates:
                seen.add(candidate["conversation_id"])
                with db_readonly() as conn:
                    groups = self._message_items(conn, candidate)
                for group in groups:
                    # a message's states go in one call, so its marker is never written without the rest
                    if self._queue and _asked(self._queue) + _asked(group) > settings.ANALYTICS_BATCH_STATES:
                        self._flush("analytics_turn")
                    self._queue.extend(group)
                    if _asked(self._queue) >= settings.ANALYTICS_BATCH_STATES:
                        self._flush("analytics_turn")
                if not self._going():
                    break
        if self._queue and self._going():
            self._flush("analytics_turn")

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
            self.stats["messages"] += 1
            base = dict(owner, message_id=m.id, occurred_at=m.timestamp, lang=states.lang(m.prompt),
                        source_updated_at=m.updated_at, source_hash=m.source_hash)
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
            self.stats["messages"] += 1
            groups.append([_Item(level="message", message_id=message_id, occurred_at=row["timestamp"], lang="en",
                                 source_updated_at=row["updated_at"], source_hash=row["source_hash"], **owner)])
        return groups

    # ---- conversation pass ----------------------------------------------------------------------------------------

    def conversation_pass(self) -> None:
        """Ask goal met and the agent's tags of every idle conversation that needs them."""
        seen: set[str] = set()
        while self._going():
            with db_readonly() as conn:
                candidates = ConversationLabelsRepository(conn).conversation_candidates(
                    schema.SCHEMA_HASH, self.model_version, self.days, settings.ANALYTICS_CONVERSATION_IDLE_MINUTES,
                    PAGE, agent_id=self.agent_id, exclude=seen,
                )
            if not candidates:
                break
            for candidate in candidates:
                seen.add(candidate["conversation_id"])
                with db_readonly() as conn:
                    item = self._conversation_item(conn, candidate)
                if item is None:
                    continue
                self.stats["conversations"] += 1
                self._queue.append(item)
                if _asked(self._queue) >= settings.ANALYTICS_BATCH_STATES:
                    self._flush("analytics_conversation")
                if not self._going():
                    break
        if self._queue and self._going():
            self._flush("analytics_conversation")

    def _conversation_item(self, conn, candidate: dict) -> Optional[_Item]:
        cid = candidate["conversation_id"]
        msgs = self._load(conn, cid)
        if not msgs:
            return None
        agent = self._agent(conn, candidate["agent_id"])
        questions = {"goal_met": schema.GOAL_MET}
        hashes = {"goal_met": candidate["tags_hash"]}
        # An overlapping topic is asked in the model's trained tag form; without a description, by its name.
        for topic in agent.config.overlapping() if agent is not None else []:
            description = topic.description or topic.name
            questions[f"tag:{topic.id}"] = schema.tag_question(topic.name, description)
            hashes[f"tag:{topic.id}"] = topics.options_hash([topic.name, description])
        updated_at, source_hash = self._conversations[cid]
        item = _Item(conversation_id=cid, user_id=candidate["user_id"], agent_id=candidate["agent_id"],
                     level="conversation", message_id=None, occurred_at=msgs[-1].timestamp,
                     lang=states.lang("\n".join(m.prompt for m in msgs)), questions=questions, hashes=hashes,
                     source_updated_at=updated_at, source_hash=source_hash)
        try:
            item.state = states.conversation(msgs)
        except Exception:  # noqa: BLE001
            logger.warning("Analytics: could not build the state of conversation %s", cid, exc_info=True)
        return item

    # ---- pending pass ---------------------------------------------------------------------------------------------

    def pending_pass(self) -> None:
        """Settle resolutions still pending once their conversation is past the window; no model call."""
        seen: set[str] = set()
        while self._going():
            with db_readonly() as conn:
                candidates = ConversationLabelsRepository(conn).pending_resolutions(
                    schema.SCHEMA_HASH, self.model_version, settings.ANALYTICS_RESOLUTION_WINDOW_HOURS, PAGE,
                    exclude=seen,
                )
            if not candidates:
                break
            for candidate in candidates:
                seen.add(candidate["conversation_id"])
                with db_session() as conn:
                    msgs = self._load(conn, candidate["conversation_id"])
                    rows = self._conversation_rows(conn, candidate, msgs)
                    ConversationLabelsRepository(conn).upsert_many(rows)
                self.stats["resolutions"] += 1
                self.stats["rows"] += len(rows)

    # ---- calls and writes -----------------------------------------------------------------------------------------

    def _flush(self, feature: str) -> None:
        """Ask the queued states in one call and write what came back; an unavailable call writes nothing."""
        batch, self._queue = self._queue, []
        if not self._going():
            return
        asked = [item for item in batch if item.state is not None]
        decided: list = []
        reasons: list = []
        if asked:
            result = decisions.decide_batch([Request(i.state, i.questions) for i in asked], feature=feature,
                                            budget=Budget.BACKGROUND)
            self.stats["calls"] += 1
            self.stats["states"] += len(asked)
            if self.lock is not None:
                self.lock.refresh()
            if result.status == "unavailable":
                logger.info("Analytics sweep stopped: the decision model is unavailable (%s)",
                            ", ".join(sorted({r for r in result.reasons if r})))
                self.stopped = "unavailable"
                return
            if result.status == "timeout":
                self.stopped = "timeout"
            decided, reasons = list(result), list(result.reasons)
            answered = next((d.model.version for d in decided if d is not None), self.model_version)
            if answered != self.model_version:  # the server changed models: label as the one that answered
                logger.info("Analytics sweep: model version changed from %s to %s", self.model_version, answered)
                self.model_version = answered
        rows: list[dict] = []
        outcome = dict(zip(map(id, asked), zip(decided, reasons)))
        # A message with a state not answered in time keeps no rows from this call, so it has no marker and the
        # next sweep labels all of it again.
        late = {item.source for item in asked if outcome[id(item)][0] is None and outcome[id(item)][1] != "bad_item"}
        for item in batch:
            decision, reason = outcome.get(id(item), (None, "build_failed"))
            if item.source in late and item.source is not None:
                if decision is None and reason not in ("bad_item", "build_failed"):
                    self.stats["timeouts"] += 1
                continue
            if decision is not None:
                self.stats["truncated"] += int(decision.truncated)
                rows.extend(self._rows(item, decision))
            elif reason in ("bad_item", "build_failed"):
                self.stats["errors"] += 1
                # on the user message it was built for, where it marks that message labelled
                error = self._row(item, label=ERROR, probabilities={}, top=reason)
                error.update(message_id=item.source, reply_message_id=None)
                rows.append(error)
            else:  # a conversation's state, not answered in time
                self.stats["timeouts"] += 1
        self._write(rows, feature == "analytics_conversation")

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
            return
        except IntegrityError:
            logger.info("Analytics: a labelled message changed while the sweep ran; writing conversations singly")
        for cid, group in groups.items():
            try:
                with db_session() as conn:
                    self._write_group(conn, cid, group, conversation_level)
            except IntegrityError:
                logger.debug("Analytics: conversation %s changed while it was labelled; skipped", cid)

    def _write_group(self, conn, cid: str, rows: list[dict], conversation_level: bool) -> None:
        repo = ConversationLabelsRepository(conn)
        self.stats["rows"] += repo.upsert_many(rows)
        if conversation_level and any(row["label"] == "goal_met" for row in rows):
            repo.delete_conversation_tags(cid, [row["label"] for row in rows if row["label"].startswith("tag:")])
        msgs = self._messages.get(cid) or self._load(conn, cid)
        derived = self._message_rows(conn, cid, rows[0], msgs)
        if conversation_level:
            derived += self._conversation_rows(conn, rows[0], msgs)
        self.stats["rows"] += repo.upsert_many(derived)

    # ---- derived rows ---------------------------------------------------------------------------------------------

    def _labels(self, conn, cid: str) -> dict[tuple[Optional[str], str], dict]:
        rows = ConversationLabelsRepository(conn).for_conversation(cid, schema.SCHEMA_HASH, self.model_version)
        return {(row["message_id"], row["label"]): row for row in rows}

    @staticmethod
    def _replies(labels: dict, label: str) -> dict[str, dict[str, float]]:
        """Reaction-level probabilities by the reply message they describe."""
        return {row["reply_message_id"]: row["probabilities"] for (_, name), row in labels.items()
                if name == label and row["reply_message_id"]}

    def _message_rows(self, conn, cid: str, ref: dict, msgs: list[states.Message]) -> list[dict]:
        """``gap_type`` of every labelled turn and ``topic_effective`` of every message with a topic."""
        labels = self._labels(conn, cid)
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

    def _conversation_rows(self, conn, ref: dict, msgs: list[states.Message]) -> list[dict]:
        """``resolution`` and ``experience`` from the stored labels; none before ``goal_met`` exists."""
        if not msgs:
            return []
        labels = self._labels(conn, ref["conversation_id"])
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
        ref = {**ref, "occurred_at": last}
        return [
            self._derived(ref, None, "conversation", "resolution", resolution, goal["lang"]),
            # not a distribution: the score and each component's contribution
            self._derived(ref, None, "conversation", "experience", experience, goal["lang"], top="score",
                          p_top=experience["score"]),
        ]


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
    """
    from docsgpt.decisions.latency import ANALYTICS

    with db_readonly() as conn:
        counts = ConversationLabelsRepository(conn).count_message_candidates(
            schema.SCHEMA_HASH, decisions.model_version() or "", days, agent_id=agent_id
        )
    per_turn = decisions.predict_s(ANALYTICS)
    compute = None if per_turn is None else round(per_turn * counts["turns"], 1)
    return {
        "enabled": enabled(), "days": days, "agent_id": agent_id, **counts,
        "seconds_per_turn": None if per_turn is None else round(per_turn, 3),
        "estimated_compute_s": compute,
        "estimated_wall_s": None if compute is None else round(compute / settings.DECISION_BACKGROUND_SHARE, 1),
    }
