"""What one chat turn can do with the files attached to it.

Computed once per turn, after the final tool list and the model's tool
support are known (``BaseAgent._prepare_tools``). The attachment budget
planner, the per-turn manifest and anything else that has to tell the model
how to reach a file read this one object, so they can never disagree about
which tools exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Tuple

# Tool-dict ``name`` of the server-side tool that reads attachments. The
# planner and the manifest only send a file to it once a tool by this name is
# really part of the turn; until then such files are "not included".
ATTACHMENTS_TOOL_NAME = "attachments"

# Tool-dict ``name`` of the code execution tool that can stage attachments as
# sandbox inputs.
SANDBOX_TOOL_NAME = "code_executor"


@dataclass(frozen=True)
class TurnCapabilities:
    """The attachment-relevant capabilities of a single turn.

    Attributes:
        tool_calling: The model accepts tools and this turn sends at least one.
        vision: The model reads images natively.
        native_pdf: The model reads PDFs natively (a file part).
        sandbox: The code execution tool is in this turn's tools and a sandbox
            backend is configured.
        window: The model's context window in tokens.
        is_v1: The turn came through ``/v1/chat/completions``.
        attachments_tool: The server-side attachments tool is in this turn's
            tools, so files left out of the context can be read on demand.
        sandbox_action: LLM-visible name of the code execution action, when
            ``sandbox`` is true.
        attachments_actions: LLM-visible names of the attachments tool's
            actions, when ``attachments_tool`` is true.
        supported_attachment_types: MIME types the provider takes natively.
    """

    tool_calling: bool
    vision: bool
    native_pdf: bool
    sandbox: bool
    window: int
    is_v1: bool
    attachments_tool: bool = False
    sandbox_action: Optional[str] = None
    attachments_actions: Tuple[str, ...] = ()
    supported_attachment_types: Tuple[str, ...] = ()

    @property
    def synthetic_pdf(self) -> bool:
        """PDFs reach the model as page images (vision without native PDF)."""
        return self.vision and not self.native_pdf

    def reads_natively(self, mime_type: Optional[str]) -> bool:
        """Whether a file of ``mime_type`` can be handed to the model as a native part.

        Args:
            mime_type: The attachment's MIME type.

        Returns:
            True for a type the provider takes natively, and for PDFs on a
            vision model (sent as page images).
        """
        if not mime_type:
            return False
        if mime_type in self.supported_attachment_types:
            return True
        return mime_type == "application/pdf" and self.synthetic_pdf


def build_turn_capabilities(
    *,
    supported_attachment_types: Optional[Iterable[str]],
    tool_calling: bool,
    server_tools: Mapping[str, object],
    window: int,
    is_v1: bool,
    sandbox_available: bool,
) -> TurnCapabilities:
    """Assemble a turn's capabilities from what the agent resolved.

    Args:
        supported_attachment_types: MIME types the provider takes natively.
        tool_calling: The model accepts tools and the turn sends some.
        server_tools: Server-side (not client-executed) tools in the turn,
            mapping the tool-dict ``name`` to its LLM-visible action name, or
            to a list of them.
        window: The model's context window in tokens.
        is_v1: The turn came through ``/v1/chat/completions``.
        sandbox_available: A sandbox backend is configured.

    Returns:
        The frozen capabilities.
    """
    types = tuple(t for t in (supported_attachment_types or ()) if isinstance(t, str))
    sandbox_action = _first_action(server_tools.get(SANDBOX_TOOL_NAME))
    attachments_actions = _all_actions(server_tools.get(ATTACHMENTS_TOOL_NAME))
    sandbox = bool(tool_calling and sandbox_available and sandbox_action)
    attachments_tool = bool(tool_calling and attachments_actions)
    return TurnCapabilities(
        tool_calling=bool(tool_calling),
        vision=any(t.startswith("image/") for t in types),
        native_pdf="application/pdf" in types,
        sandbox=sandbox,
        window=int(window),
        is_v1=bool(is_v1),
        attachments_tool=attachments_tool,
        sandbox_action=sandbox_action if sandbox else None,
        attachments_actions=attachments_actions if attachments_tool else (),
        supported_attachment_types=types,
    )


def _all_actions(value: object) -> Tuple[str, ...]:
    """Normalise a ``server_tools`` value to a tuple of action names."""
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(sorted(str(v) for v in value if v))
    return ()


def _first_action(value: object) -> Optional[str]:
    """The first action name of a ``server_tools`` value, if any."""
    actions = _all_actions(value)
    return actions[0] if actions else None
