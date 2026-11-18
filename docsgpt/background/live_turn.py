"""A continuation turn's message while it runs, written the way a chat turn writes its own.

A continuation used to run unseen and append its message only once it had
finished: the chat showed nothing while it worked, a reload could not pick it
up, and Stop had no message to stop. :class:`LiveTurn` gives it what a chat
turn has. Its message row is reserved as ``streaming`` before the turn runs,
its events go to the message journal in the chat stream's wire shape, its
heartbeat keeps the row alive, and ``message.started`` / ``message.finished``
go out on the user's event stream. An open chat then tails it, the sidebar
marks it working, a reload resumes it and Stop reaches it, all through the
paths a chat turn uses.

A silent turn (``NO_REPLY``) must still say nothing. Answer text is held back
while it could still turn out to be ``NO_REPLY``, and a turn that ends silent
or fails takes its row back out (:meth:`LiveTurn.discard`).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from docsgpt.activity.flags import clear_stop, stop_requested
from docsgpt.storage.db.repositories.conversations import ConversationsRepository, MessageUpdateOutcome
from docsgpt.storage.db.session import db_session
from docsgpt.streaming.message_journal import BatchedJournalWriter, record_event
from docsgpt.utils import strip_null_bytes

logger = logging.getLogger(__name__)

#: Seconds between heartbeats on the row, as a chat stream stamps its own.
HEARTBEAT_SECONDS = 30

#: Seconds between checks for the user's Stop.
STOP_POLL_SECONDS = 1.0


def _could_be_silent(text: str) -> bool:
    """Whether answer text seen so far could still be the whole of a ``NO_REPLY``."""
    from docsgpt.background.wake import NO_REPLY

    cleaned = text.strip().strip("`'\".").strip().upper()
    return NO_REPLY.startswith(cleaned)


class LiveTurn:
    """The message a continuation turn writes as it runs.

    Use :meth:`open` to reserve the row; feed it each event the agent yields
    with :meth:`event`; poll :meth:`stopped`; end it with :meth:`finish` or
    :meth:`discard`.
    """

    def __init__(self, conversation: Dict[str, Any], message_id: str) -> None:
        """Bind to the turn; nothing is written until :meth:`open`.

        Args:
            conversation: The conversation row.
            message_id: The id the turn's message is written under.
        """
        from docsgpt.api.answer.services.artifact_delivery import ArtifactDescriber

        self.conversation_id = str(conversation["id"])
        self.user_id = str(conversation["user_id"])
        self.message_id = message_id
        self._describer = ArtifactDescriber(self.user_id, self.conversation_id)
        self._journal = BatchedJournalWriter(message_id)
        self._sequence = -1
        self._partial: Dict[str, Any] = {"answer": "", "thought": "", "sources": [], "tool_calls": []}
        self._held = ""
        self._released = False
        self._stop = threading.Event()
        self._done = threading.Event()
        self._ticker: Optional[threading.Thread] = None
        self._closed = False

    @classmethod
    def open(
        cls, conversation: Dict[str, Any], message_id: str, *, prompt: str, metadata: Dict[str, Any]
    ) -> Optional["LiveTurn"]:
        """Reserve the turn's row and announce it; None when the row could not be written.

        Args:
            conversation: The conversation row.
            message_id: The id the turn's message is written under.
            prompt: The event text the turn answers (shown as the wake, never as the user's).
            metadata: The row's ``message_metadata`` (its wake).

        Returns:
            The live turn, or None: the caller then appends the message when the turn ends.
        """
        from docsgpt.api.answer.services.conversation_service import TERMINATED_RESPONSE_PLACEHOLDER

        turn = cls(conversation, message_id)
        try:
            with db_session() as conn:
                repo = ConversationsRepository(conn)
                repo.append_message(
                    turn.conversation_id,
                    {
                        "id": message_id,
                        "prompt": prompt,
                        "response": TERMINATED_RESPONSE_PLACEHOLDER,
                        "status": "streaming",
                        "metadata": metadata,
                    },
                )
                repo.heartbeat_message(message_id)
        except Exception:
            logger.exception("continuation %s: reserving its message failed; it is appended when done", message_id)
            return None
        turn._publish("message.started")
        turn._ticker = threading.Thread(target=turn._tick, name="docsgpt-continuation-ticker", daemon=True)
        turn._ticker.start()
        return turn

    def event(self, event: Dict[str, Any]) -> None:
        """Journal one event the agent yielded, as the chat stream would send it."""
        if self._closed:
            return
        for field in ("answer", "thought"):
            if field in event:
                self._partial[field] += str(event[field])
        for field in ("sources", "tool_calls"):
            if field in event:
                self._partial[field] = event[field]
        if "answer" in event:
            self._answer(str(event["answer"]))
            return
        if event.get("type") == "tool_call":
            # A call means the turn is doing something: the text before it is not a silent reply.
            self._release()
            self._emit({**event, "data": self._describer.tool_call(event.get("data"))})
        elif "thought" in event:
            self._emit({"type": "thought", "thought": event["thought"]})
        elif "sources" in event:
            self._emit({"type": "source", "source": [_short_source(s) for s in event["sources"] or []]})
        elif "tool_calls" in event:
            self._emit({"type": "tool_calls", "tool_calls": self._describer.tool_calls(event["tool_calls"])})

    def partial_outcome(self) -> Dict[str, Any]:
        """Return streamed progress if the runner exits before returning an outcome."""
        return dict(self._partial)

    def stopped(self) -> bool:
        """Whether the user pressed Stop on this turn."""
        return self._stop.is_set()

    def finish(
        self,
        outcome: Dict[str, Any],
        *,
        metadata: Dict[str, Any],
        stopped: bool = False,
    ) -> MessageUpdateOutcome:
        """Write the turn's result to its row and end its journal.

        Args:
            outcome: ``run_agent_headless``'s outcome.
            metadata: Keys merged into the row's ``message_metadata``.
            stopped: The user stopped the turn. With no text it is saved as
                failed with the ``stopped`` code, as a stopped chat turn is.

        Returns:
            The row update's outcome; ``NOT_FOUND`` when the row was deleted
            meanwhile (the user retried or edited an earlier message).
        """
        from docsgpt.api.answer.services.conversation_service import TERMINATED_RESPONSE_PLACEHOLDER

        answer = outcome.get("answer") or ""
        self._release()
        fields: Dict[str, Any] = {
            "response": answer,
            "status": "complete",
            "thought": outcome.get("thought") or "",
            "sources": outcome.get("sources") or [],
            "tool_calls": outcome.get("tool_calls") or [],
            "metadata": dict(metadata),
        }
        if outcome.get("model_id"):
            fields["model_id"] = outcome["model_id"]
        terminal: Dict[str, Any] = {"type": "end"}
        if outcome.get("error_type") == "TimeLimit":
            fields["status"] = "failed"
            fields["metadata"].update({"error": "Stopped: time limit.", "error_code": "time_limit"})
            terminal = {"type": "error", "error": "Stopped: time limit.", "code": "time_limit"}
        elif stopped and not answer.strip():
            fields["status"] = "failed"
            fields["response"] = TERMINATED_RESPONSE_PLACEHOLDER
            fields["metadata"].update(
                {"error": "Stopped by its user before any response was produced.", "error_code": "stopped"}
            )
            terminal = {"type": "error", "error": "Stopped before any response was produced.", "code": "stopped"}
        else:
            artifacts = self._describer.summary()
            if artifacts:
                terminal["artifacts"] = artifacts
        try:
            with db_session() as conn:
                repo = ConversationsRepository(conn)
                result = repo.update_message_by_id(
                    self.message_id, strip_null_bytes(fields), only_if_non_terminal=True
                )
                if result is MessageUpdateOutcome.UPDATED:
                    repo.confirm_executed_tool_calls(self.message_id)
        except Exception:
            logger.exception("continuation %s: saving its message failed", self.message_id)
            result = MessageUpdateOutcome.INVALID
        if result is MessageUpdateOutcome.UPDATED:
            self._end(terminal)
        else:
            self._close()
        return result

    def discard(self) -> None:
        """Take the row back out: the turn ended silent, or failed before it could say anything."""
        try:
            with db_session() as conn:
                ConversationsRepository(conn).delete_in_flight_message(self.message_id)
        except Exception:
            logger.exception("continuation %s: removing its message failed", self.message_id)
        self._close()

    # ------------------------------------------------------------------

    def _answer(self, chunk: str) -> None:
        if self._released:
            self._emit({"type": "answer", "answer": chunk})
            return
        self._held += chunk
        if not _could_be_silent(self._held):
            self._release()

    def _release(self) -> None:
        """Send the answer text held back while it could have been ``NO_REPLY``."""
        if self._released:
            return
        self._released = True
        if self._held:
            self._emit({"type": "answer", "answer": self._held})
            self._held = ""

    def _emit(self, payload: Dict[str, Any]) -> None:
        self._sequence += 1
        self._journal.record(self._sequence, str(payload.get("type") or "data"), payload)

    def _end(self, terminal: Dict[str, Any]) -> None:
        """Journal the terminal event after everything buffered, then close."""
        self._journal.flush()
        self._journal.close()
        self._sequence += 1
        record_event(self.message_id, self._sequence, str(terminal["type"]), terminal)
        self._close()

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._done.set()
        try:
            self._journal.flush()
            self._journal.close()
        except Exception:
            logger.debug("continuation %s: closing its journal failed", self.message_id, exc_info=True)
        clear_stop(self.message_id)
        self._publish("message.finished")

    def _tick(self) -> None:
        """Keep the row alive and watch for the user's Stop until the turn ends."""
        next_beat = time.monotonic() + HEARTBEAT_SECONDS
        while not self._done.wait(STOP_POLL_SECONDS):
            if not self._stop.is_set() and stop_requested(self.message_id):
                self._stop.set()
            if time.monotonic() >= next_beat:
                next_beat = time.monotonic() + HEARTBEAT_SECONDS
                try:
                    with db_session() as conn:
                        ConversationsRepository(conn).heartbeat_message(self.message_id)
                except Exception:
                    logger.debug("continuation %s: heartbeat failed", self.message_id, exc_info=True)

    def _publish(self, kind: str) -> None:
        from docsgpt.events.publisher import publish_user_event

        try:
            publish_user_event(
                self.user_id,
                kind,
                {"conversation_id": self.conversation_id, "message_id": self.message_id},
                scope={"kind": "conversation", "id": self.conversation_id},
            )
        except Exception:
            logger.debug("continuation %s: publishing %s failed", self.message_id, kind, exc_info=True)


def _short_source(source: Any) -> Any:
    """A source as the chat stream sends it: its text cut to a preview."""
    if not isinstance(source, dict) or not isinstance(source.get("text"), str):
        return source
    return {**source, "text": source["text"][:100].strip() + "..."}

