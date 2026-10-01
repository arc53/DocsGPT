"""The typed error for a turn that cannot fit the model's context window."""

from __future__ import annotations

from typing import Optional


class ContextOverflowError(ValueError):
    """A turn needs more context than the model has, and nothing can shrink it.

    Raised before any provider call (and before any compression call), so a
    hopeless request costs nothing. Routes can map it to an honest message,
    or to an OpenAI-shaped ``context_length_exceeded`` on ``/v1``. Subclasses
    ``ValueError`` so existing ``except ValueError`` handlers still catch it.

    Attributes:
        needed_tokens: Estimated tokens the turn needs.
        available_tokens: Tokens the model's window offers.
        stage: Where the overflow was found: ``"pre_compression"`` (setup,
            before history is compressed), ``"build"`` (message building) or
            ``"dispatch"`` (the pre-send gate).
    """

    def __init__(
        self,
        message: str,
        *,
        needed_tokens: int,
        available_tokens: int,
        stage: str,
        detail: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.needed_tokens = int(needed_tokens)
        self.available_tokens = int(available_tokens)
        self.stage = stage
        self.detail = detail
