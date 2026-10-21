"""Pydantic contract for ``agents.config.analytics``: whether an agent's conversations are labelled, and how.

Strict on write like the rest of ``AgentConfig``; ``parse`` is the lenient read the sweep uses, so a row written
under looser limits (an operator lowering ``ANALYTICS_MAX_OVERLAPPING_TOPICS``) still labels with what fits. None
of this is policy: an editor without ``edit_policy`` may change it.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from docsgpt.analytics.schema import NONE_OPTION, units

logger = logging.getLogger(__name__)

TOPIC_NAME_CHARS = 60
#: One-pick topics share one question, so each description gets less room than an overlapping topic's own question.
TOPIC_DESCRIPTION_UNITS = 150
OVERLAP_DESCRIPTION_UNITS = 300
TOPIC_ID = re.compile(r"^[a-z0-9]{8,32}$")
#: Folders an owner may hide; far past any agent's folder count.
MAX_HIDDEN_FOLDERS = 100


def _limits():
    from docsgpt.core.settings import settings

    return settings.ANALYTICS_MAX_TOPICS, settings.ANALYTICS_MAX_OVERLAPPING_TOPICS


class AnalyticsTopic(BaseModel):
    """One of the owner's topics; its id keeps an overlapping topic's history across renames.

    A topic that doesn't overlap is an option of the one-pick question asked of every user message, next to the
    agent's source folders. One that overlaps is its own yes/no question on every idle conversation (a ``tag:<id>``
    label: the model's trained wording says "tag").
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    overlap: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not TOPIC_ID.match(value or ""):
            raise ValueError("topic ids are 8 to 32 lowercase letters or digits")
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        name = (value or "").strip()
        if not name:
            raise ValueError("a topic needs a name")
        if len(name) > TOPIC_NAME_CHARS:
            raise ValueError(f"topic names are at most {TOPIC_NAME_CHARS} characters")
        if name.lower() == NONE_OPTION:
            raise ValueError(f"'{NONE_OPTION}' is always offered and cannot be a topic")
        return name

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        return (value or "").strip()

    @model_validator(mode="after")
    def _description_fits(self) -> "AnalyticsTopic":
        cap = OVERLAP_DESCRIPTION_UNITS if self.overlap else TOPIC_DESCRIPTION_UNITS
        if units(self.description) > cap:
            # CJK characters count 3 units and Cyrillic 1.2: the text is part of the model's question.
            raise ValueError(f"topic descriptions are at most {cap} units (about as many Latin characters; a "
                             "Chinese character counts 3)")
        return self


class AnalyticsConfig(BaseModel):
    """Per-agent conversation analytics, stored in ``agents.config.analytics``.

    Attributes:
        enabled: Whether the agent's conversations are labelled while ``DECISION_ANALYTICS_ENABLED`` is on.
        topics: The owner's topics, both kinds, in the order they were added.
        hidden_folders: Source folders left out of the one-pick question (an edited folder is hidden and re-added
            as the owner's own topic).
        digest: Send the owner the weekly in-app docs-gap digest.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    topics: List[AnalyticsTopic] = []
    hidden_folders: List[str] = []
    digest: bool = False

    @field_validator("topics")
    @classmethod
    def _topics(cls, value: List[AnalyticsTopic]) -> List[AnalyticsTopic]:
        max_topics, max_overlapping = _limits()
        if sum(not t.overlap for t in value) > max_topics:
            raise ValueError(f"at most {max_topics} topics that don't overlap")
        if sum(t.overlap for t in value) > max_overlapping:
            raise ValueError(f"at most {max_overlapping} topics that can overlap")
        ids, names = set(), set()
        for topic in value:
            if topic.id in ids:
                raise ValueError(f"duplicate topic id '{topic.id}'")
            if topic.name.lower() in names:
                raise ValueError(f"duplicate topic '{topic.name}'")
            ids.add(topic.id)
            names.add(topic.name.lower())
        return value

    @field_validator("hidden_folders")
    @classmethod
    def _hidden(cls, value: List[str]) -> List[str]:
        if len(value) > MAX_HIDDEN_FOLDERS:
            raise ValueError(f"at most {MAX_HIDDEN_FOLDERS} hidden folders")
        out, seen = [], set()
        for raw in value:
            name = (raw or "").strip()
            if not name or len(name) > TOPIC_NAME_CHARS:
                raise ValueError(f"hidden folder names are 1 to {TOPIC_NAME_CHARS} characters")
            if name.lower() in seen:
                raise ValueError(f"duplicate hidden folder '{name}'")
            seen.add(name.lower())
            out.append(name)
        return out

    def one_pick(self) -> List[AnalyticsTopic]:
        """The owner's topics that are options of the one-pick question."""
        return [t for t in self.topics if not t.overlap]

    def overlapping(self) -> List[AnalyticsTopic]:
        """The owner's topics asked as their own yes/no question per conversation."""
        return [t for t in self.topics if t.overlap]

    @classmethod
    def parse(cls, raw: Optional[dict]) -> "AnalyticsConfig":
        """Lenient read: never raises.

        Each kind longer than its current limit is cut to it; anything else that no longer validates falls back to
        the defaults, keeping the two switches when they are booleans.
        """
        if not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:
            pass
        max_topics, max_overlapping = _limits()
        trimmed = dict(raw)
        if isinstance(raw.get("topics"), list):
            kept, picks, overlaps = [], 0, 0
            for topic in raw["topics"]:
                overlap = isinstance(topic, dict) and topic.get("overlap") is True
                if overlap and overlaps < max_overlapping:
                    overlaps += 1
                    kept.append(topic)
                elif not overlap and picks < max_topics:
                    picks += 1
                    kept.append(topic)
            trimmed["topics"] = kept
        try:
            return cls.model_validate(trimmed)
        except Exception:
            logger.warning("Agent analytics config is unusable; labelling with the defaults until it is re-saved")
        switches = {key: raw[key] for key in ("enabled", "digest") if isinstance(raw.get(key), bool)}
        return cls(**switches)
