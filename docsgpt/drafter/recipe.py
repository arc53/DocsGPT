"""Recipes: what one drafter screen reads, how it instructs the model and what it may propose.

A recipe is data plus four functions; the runner (``docsgpt/drafter/runner.py``)
is the same for every screen. Recipes register themselves by id; the
``recipe`` field of a ``POST /api/drafter/stream`` body picks one.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union

from docsgpt.drafter.catalog import Workspace

#: Characters of an id a request sends (an agent, a prompt, a source).
ID_CHARS = 100
#: Characters of a proposal's message to the user.
MESSAGE_MAX = 600


def clean_id(value: Any) -> Optional[str]:
    """An id from a request's context, stripped and cut to :data:`ID_CHARS`.

    Args:
        value: The raw value.

    Returns:
        The id, or None when ``value`` isn't a string with something besides spaces.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:ID_CHARS]


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
        can_correct: Whether a :class:`ProposalInvalid` from the answer being validated still gets the turn's
            corrected try (the runner keeps it current). A check that guards wording rather than the draft raises
            only while this is True, so it never costs the turn.
    """

    user_id: str
    recipe: str
    messages: list[dict]
    context: dict
    request_id: str
    can_correct: bool = True

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
        tools_for: Narrows ``read_tools`` per turn, ``(request, workspace) -> names``, when what a turn may read
            depends on what was loaded (the agent recipe offers its Insights reads only with Insights data); a
            name outside ``read_tools`` is never offered. None offers ``read_tools`` every turn.
        proposal_description: The ``submit_proposal`` tool description.
        questions: Whether the model may ask questions (``ask_user``) before proposing, or a
            ``(request) -> bool`` deciding it per turn (the prompt recipe asks only before writing).
        reads_workspace: Whether ``load_workspace`` reads anything; a recipe that drafts on the
            screen's own values (a prompt) sends no ``reading`` status, so the panel shows no counts.
        check_questions: Checks and reshapes a turn's normalized questions for the recipe's own rules,
            ``(questions, request, workspace) -> questions``; raises :class:`ProposalInvalid` on a fixable problem.
            None takes them as they are.
    """

    id: str
    parse_context: Callable[[Any], dict]
    load_workspace: Callable[[str, dict], Workspace]
    instructions: Callable[[DraftRequest, Workspace], str]
    context_data: Callable[[DraftRequest, Workspace], dict]
    proposal_schema: dict
    validate: Callable[[dict, DraftRequest, Workspace], dict]
    read_tools: tuple[str, ...] = field(default_factory=tuple)
    tools_for: Optional[Callable[[DraftRequest, Workspace], tuple[str, ...]]] = None
    proposal_description: str = "Hand the finished draft to the user's form. Ends your turn."
    questions: Union[bool, Callable[[DraftRequest], bool]] = True
    reads_workspace: bool = True
    check_questions: Optional[Callable[[list[dict], DraftRequest, Workspace], list[dict]]] = None

    def asks(self, req: DraftRequest) -> bool:
        """Whether this turn of ``req`` may ask questions at all."""
        return self.questions(req) if callable(self.questions) else self.questions

    def offered_tools(self, req: DraftRequest, ws: Workspace) -> tuple[str, ...]:
        """The read tools this turn of ``req`` offers, given its workspace."""
        if self.tools_for is None:
            return self.read_tools
        picked = set(self.tools_for(req, ws))
        return tuple(name for name in self.read_tools if name in picked)


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
