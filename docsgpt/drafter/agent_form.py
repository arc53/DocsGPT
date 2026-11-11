"""The agent form as the agent recipe drafts it: the guided build's steps and the fields each one sets, the guardrail
menu, and the caps a drafted value has.

Shared by the recipe (``docsgpt/drafter/agent_recipe.py``), its instructions
(``agent_instructions.py``) and its reading of the safety step's wording
(``safety_wording.py``).
"""

from __future__ import annotations

AGENT_TYPES = ("classic", "research")
BUILTIN_PROMPTS = ("default", "creative", "strict")

#: The guided build's steps, in order, and the fields each one sets.
STEPS = ("basics", "knowledge", "prompt", "safety")
STEP_FIELDS: dict[str, tuple[str, ...]] = {
    "basics": ("name", "description"),
    "knowledge": ("sources", "tools", "agent_type"),
    "prompt": ("prompt", "starters"),
    "safety": ("limits", "guardrails", "analytics"),
}
SAFETY_FIELDS = STEP_FIELDS["safety"]
FIELDS = tuple(name for step in STEPS for name in STEP_FIELDS[step])

#: The guardrail checks the safety step offers, each as the ``(stage, action)`` controls it adds.
GUARDRAIL_MENU: dict[str, tuple[tuple[str, str], ...]] = {
    "pii": (("input", "redact"), ("output", "redact")),
    "injection": (("input", "block"),),
    "groundedness": (("output", "flag"),),
    "secrets": (("output", "redact"),),
}
LIMIT_MODES = ("requests", "tokens", "none")
GUARDRAIL_MODES = ("monitor_only", "scan_all")

#: Lengths a drafted value may have. The agent routes store text without a cap; these keep a draft card-sized.
NAME_MAX = 100
DESCRIPTION_MAX = 500
PROMPT_NAME_MAX = 100
PROMPT_CONTENT_MAX = 20000
#: Most sources, and most tools, a proposal adds to those the form already has.
MAX_REFS = 30
#: Largest request or token limit a proposal sets.
LIMIT_MAX = 1_000_000_000
#: Most Insights topics one proposal adds.
MAX_NEW_TOPICS = 4
REASON_SUMMARY_MAX = 200
MAX_REASONS = 10
MAX_NOTES = 3
NOTE_MAX = 300
#: Most gaps an improve proposal lists, characters of a gap's example and of what it needs, and links per gap.
MAX_GAPS = 3
GAP_EXAMPLE_MAX = 160
GAP_NEEDS_MAX = 300
MAX_GAP_LINKS = 3
#: The guardrail check an improve proposal may add from Insights, and the gap type that calls for it.
INSIGHTS_CHECK = "groundedness"
UNGROUNDED = "confidently ungrounded"


def checks_on(guardrails: dict) -> set[str]:
    """The menu checks the form runs at every stage the menu gives them (one on at some stages only is not)."""
    on = {(c["check"], c["stage"]) for c in guardrails["controls"]}
    return {check for check, controls in GUARDRAIL_MENU.items() if all((check, stage) in on for stage, _ in controls)}
