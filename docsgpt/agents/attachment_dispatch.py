"""What one LLM call needs to know about the turn's files besides its messages.

The agent hands an :class:`AttachmentDispatch` to every ``gen_stream`` call
(``_attachment_dispatch``). The LLM layer asks it two things:

* ``usage_tokens(messages)``: context the call's native parts take that the
  token counter cannot see (a Files-API id, an image data URL), so prompt
  usage is counted once — the files' text is already in the messages;
* ``for_fallback(fallback, messages)``: the turn's files re-planned for a
  fallback model's window and capabilities, so a fallback gets the documents
  in a form it can read and at a size it can take, instead of the primary's
  payload with file parts swapped for whole texts. The attachments tool is
  re-synced with that plan, so the statuses it lists match what the fallback
  was sent.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from docsgpt.agents.attachment_budget import (
    IMAGE_PART_TOKENS,
    AttachmentPlan,
    compute_attachment_budget,
    plan_attachments,
)

logger = logging.getLogger(__name__)


@dataclass
class FallbackAttachments:
    """The fallback's messages, with the files re-planned for it.

    Attributes:
        messages: The messages to send the fallback.
        dispatch: Usage of the fallback call's own native parts.
        built: The turn message the fallback's own provider built; its
            parts (a file id the fallback uploaded) are already the
            fallback's and must not be swapped again.
    """

    messages: List[Dict[str, Any]]
    dispatch: "FixedUsage"
    built: Optional[Dict[str, Any]] = None


class FixedUsage:
    """A dispatch for a call whose native parts are already known."""

    def __init__(self, native_tokens: int) -> None:
        """Remember the native parts' size.

        Args:
            native_tokens: Tokens of the call's native parts.
        """
        self.native_tokens = max(int(native_tokens or 0), 0)

    def usage_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Tokens of the call's native parts.

        Args:
            messages: The call's messages (unused).

        Returns:
            The native parts' size.
        """
        return self.native_tokens

    def for_fallback(self, fallback: Any, messages: List[Dict[str, Any]]) -> None:
        """A fallback's fallback is never re-planned."""
        return None

    def native_reads_for(self, fallback: Any, messages: List[Dict[str, Any]]) -> tuple:
        """A fallback's fallback keeps the messages it was given."""
        return messages, []


class AttachmentDispatch:
    """The agent's attachments, as one LLM call sees them."""

    def __init__(self, agent: Any) -> None:
        """Bind to the agent whose turn this is.

        Args:
            agent: The agent; its plan and turn message are read at call time.
        """
        self._agent = agent

    # ---- usage ----

    def usage_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Context the call's native parts take beyond what its messages show.

        With a plan, that is the plan's native size once the plan is merged
        into a message of this call. Without one (workflow nodes, headless
        runs), the provider sends the files it takes natively and the rest
        go in as text; the text is in the messages already.

        Args:
            messages: The call's messages.

        Returns:
            Tokens to add to the counted prompt.
        """
        agent = self._agent
        plan = getattr(agent, "attachment_plan", None)
        if isinstance(plan, AttachmentPlan):
            carrier = getattr(agent, "_current_turn_message", None)
            merged = getattr(agent, "_attachments_merged", False)
            if merged and carrier is not None and any(m is carrier for m in messages or []):
                return plan.native_tokens
            return 0
        if getattr(agent, "attachment_planning", False):
            return 0
        return self._unplanned_native_tokens()

    def _unplanned_native_tokens(self) -> int:
        """Native parts the provider sends for an unplanned turn."""
        attachments = [a for a in (getattr(self._agent, "attachments", None) or []) if isinstance(a, dict)]
        if not attachments:
            return 0
        try:
            supported = set(self._agent.llm.get_supported_attachment_types() or [])
        except Exception:
            return 0
        tokens = 0
        for attachment in attachments:
            mime_type = str(attachment.get("mime_type") or "")
            if mime_type not in supported:
                continue
            if mime_type.startswith("image/"):
                tokens += IMAGE_PART_TOKENS
            else:
                tokens += _int(attachment.get("token_count"))
        return tokens

    # ---- fallback ----

    def native_reads_for(self, fallback: Any, messages: List[Dict[str, Any]]) -> tuple:
        """The turn's requested images, formatted for ``fallback``.

        The follow-up messages that show the images ``attachments_read``
        queued were built by the primary's provider (image parts, image
        blocks or inline bytes). Each is rebuilt from the images it carries
        with the fallback's own provider, or as a note when it reads no
        images. ``messages`` is not changed.

        Args:
            fallback: The fallback LLM.
            messages: The primary call's messages.

        Returns:
            The messages for the fallback, and the messages rebuilt for it.
        """
        from docsgpt.llm.handlers.base import render_native_reads

        registry = getattr(self._agent, "_native_read_messages", None)
        if not isinstance(registry, list) or not registry:
            return messages, []
        rebuilt: List[Dict[str, Any]] = []
        result = list(messages or [])
        for entry in registry:
            index = next((i for i, m in enumerate(result) if m is entry.get("message")), None)
            if index is None:
                continue
            _, note = render_native_reads(
                fallback,
                [],
                list(entry.get("labels") or []),
                list(entry.get("attachments") or []),
                check_vision=True,
            )
            result[index] = note
            rebuilt.append(note)
        return (result, rebuilt) if rebuilt else (messages, [])

    def for_fallback(self, fallback: Any, messages: List[Dict[str, Any]]) -> Optional[FallbackAttachments]:
        """The turn's files re-planned for ``fallback``.

        Rebuilds the turn's message from what the user sent, plans the files
        against the fallback's window (what is left of it once everything
        else in ``messages`` is counted) and native formats, and merges that
        plan with the fallback's own provider. ``messages`` is not changed.

        Args:
            fallback: The fallback LLM.
            messages: The primary call's messages.

        Returns:
            The re-planned messages, or None when this call has no merged plan
            (the generic part swap then applies).
        """
        agent = self._agent
        plan = getattr(agent, "attachment_plan", None)
        carrier = getattr(agent, "_current_turn_message", None)
        if not isinstance(plan, AttachmentPlan) or not getattr(agent, "_attachments_merged", False):
            return None
        index = next((i for i, m in enumerate(messages or []) if m is carrier), None)
        if index is None or not hasattr(agent, "_turn_content_before_merge"):
            return None

        from docsgpt.api.answer.services.compression.token_counter import TokenCounter
        from docsgpt.core.model_utils import get_token_limit
        from docsgpt.core.settings import settings

        window = int(get_token_limit(fallback.model_id, user_id=getattr(fallback, "model_user_id", None)))
        capabilities = _capabilities_for(plan.capabilities, fallback, window)
        fresh = {**carrier, "content": copy.deepcopy(agent._turn_content_before_merge)}
        rebuilt = [*messages[:index], fresh, *messages[index + 1 :]]
        budget = compute_attachment_budget(
            window=window,
            share=float(settings.ATTACHMENT_BUDGET_SHARE),
            system_tokens=TokenCounter.count_message_tokens(rebuilt),
        )
        current = [a for a in (getattr(agent, "attachments", None) or []) if isinstance(a, dict)]
        earlier = [a for a in (getattr(agent, "earlier_attachments", None) or []) if isinstance(a, dict)]
        replanned = plan_attachments(
            current,
            capabilities,
            budget=budget,
            earlier=earlier,
            max_native_parts=int(settings.ATTACHMENT_MAX_NATIVE_PARTS),
        )
        _, merged, _ = agent.llm_handler.merge_attachment_plan(fallback, [fresh], fresh, replanned)
        rebuilt[index] = merged
        # The attachments tool lists each file's status and reads images by
        # the model's vision; it must describe what the fallback was sent.
        sync_tool = getattr(agent, "_sync_attachments_tool", None)
        if callable(sync_tool):
            sync_tool(plan=replanned, capabilities=capabilities)
        logger.info(
            "Attachments re-planned for fallback %s: budget %d, inline %d tokens (%s)",
            getattr(fallback, "model_id", None),
            replanned.budget,
            replanned.inline_tokens,
            ", ".join(f"{f.ref}={f.status.value}" for f in replanned.files),
        )
        return FallbackAttachments(messages=rebuilt, dispatch=FixedUsage(replanned.native_tokens), built=merged)


def _capabilities_for(capabilities: Any, fallback: Any, window: int) -> Any:
    """The turn's capabilities with the fallback's window and native formats.

    Tools stay what the turn sends: the fallback gets the same tool list.
    """
    try:
        supported = fallback.get_supported_attachment_types() or []
    except Exception:
        supported = []
    types = tuple(t for t in supported if isinstance(t, str))
    return dataclasses.replace(
        capabilities,
        vision=any(t.startswith("image/") for t in types),
        native_pdf="application/pdf" in types,
        window=int(window),
        supported_attachment_types=types,
    )


def _int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0
