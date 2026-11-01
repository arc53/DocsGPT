"""Recipes: what one drafter screen reads, how it instructs the model and what it may propose.

A recipe is data plus four functions; the runner (``docsgpt/drafter/runner.py``)
is the same for every screen. Recipes register themselves by id; the
``recipe`` field of a ``POST /api/drafter/stream`` body picks one.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from docsgpt.drafter.catalog import Workspace


class BadDraftRequest(ValueError):
    """The request can't be drafted (unknown recipe, malformed context); the message is safe to show."""


class ProposalInvalid(ValueError):
    """The model's proposal broke a rule it can fix; ``problems`` go back to it for one corrected try.

    Attributes:
        problems: One sentence per broken rule, addressed to the model.
    """

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class DraftRequest:
    """One draft turn, with everything taken from the Flask request before streaming starts.

    Attributes:
        user_id: The caller.
        recipe: The recipe id.
        messages: The conversation so far, cleaned: ``[{role, content}]``, ending with a user message.
        context: The recipe's cleaned context (its ``parse_context`` output).
        request_id: The id the draft's LLM calls are recorded under.
    """

    user_id: str
    recipe: str
    messages: list[dict]
    context: dict
    request_id: str

    def user_text(self) -> str:
        """Everything the user wrote in this conversation, joined (for "did they ask for X" checks)."""
        return "\n".join(m["content"] for m in self.messages if m.get("role") == "user")


@dataclass(frozen=True)
class Recipe:
    """One screen's drafting recipe.

    Attributes:
        id: The ``recipe`` value that picks it.
        parse_context: Cleans the request's ``context``; raises :class:`BadDraftRequest` when unusable.
        load_workspace: Reads what the recipe may see, scoped to the caller: ``(user_id, context) -> Workspace``.
        instructions: The recipe's part of the system prompt: ``(request, workspace) -> str``.
        context_data: The form or screen values fenced next to the request: ``(request, workspace) -> dict``.
        proposal_schema: JSON schema of the ``submit_proposal`` arguments.
        validate: Turns valid ``submit_proposal`` arguments into the ``proposal`` event payload:
            ``(arguments, request, workspace) -> dict``; raises :class:`ProposalInvalid` on a fixable problem.
        read_tools: Names of the read tools offered (``docsgpt/drafter/read_tools.py``).
        proposal_description: The ``submit_proposal`` tool description.
        questions: Whether the model may ask questions (``ask_user``) before proposing; a screen
            that takes one request and returns one result (a prompt) turns it off.
    """

    id: str
    parse_context: Callable[[Any], dict]
    load_workspace: Callable[[str, dict], Workspace]
    instructions: Callable[[DraftRequest, Workspace], str]
    context_data: Callable[[DraftRequest, Workspace], dict]
    proposal_schema: dict
    validate: Callable[[dict, DraftRequest, Workspace], dict]
    read_tools: tuple[str, ...] = field(default_factory=tuple)
    proposal_description: str = "Hand the finished draft to the user's form. Ends your turn."
    questions: bool = True


_RECIPES: dict[str, Recipe] = {}

#: Modules that register the built-in recipes, imported on first lookup.
_BUILTIN_MODULES: tuple[str, ...] = (
    "docsgpt.drafter.agent_recipe",
    "docsgpt.drafter.prompt_recipe",
    "docsgpt.drafter.topics_recipe",
)
_loaded = False


def register(recipe: Recipe) -> Recipe:
    """Make ``recipe`` available under its id (a later registration replaces an earlier one)."""
    _RECIPES[recipe.id] = recipe
    return recipe


def get_recipe(recipe_id: Any) -> Optional[Recipe]:
    """The recipe registered as ``recipe_id``, or None."""
    global _loaded
    if not _loaded:
        for module in _BUILTIN_MODULES:
            importlib.import_module(module)
        _loaded = True
    if not isinstance(recipe_id, str):
        return None
    return _RECIPES.get(recipe_id)
