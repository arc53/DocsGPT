"""Pydantic contract for ``agents.config.analytics``: whether an agent's conversations are labelled, and how.

Strict on write like the rest of ``AgentConfig``; ``parse`` is the lenient read the sweep uses, so a row written
under looser limits (an operator lowering ``ANALYTICS_MAX_TAGS``) still labels with what fits. None of this is
policy: an editor without ``edit_policy`` may change it.
"""

from __future__ import annotations

import logging
import re
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from docsgpt.analytics.schema import NONE_OPTION, units

logger = logging.getLogger(__name__)

TOPIC_NAME_CHARS = 60
TOPIC_DESCRIPTION_UNITS = 150
TAG_NAME_CHARS = 60
TAG_DESCRIPTION_CHARS = 300
TAG_ID = re.compile(r"^[a-z0-9]{8,32}$")


def _limits():
    from docsgpt.core.settings import settings

    return settings.ANALYTICS_MAX_TOPICS, settings.ANALYTICS_MAX_TAGS


class AnalyticsTopic(BaseModel):
    """One documentation section a message can be about."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""

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
        description = (value or "").strip()
        if units(description) > TOPIC_DESCRIPTION_UNITS:
            # CJK characters count 3 units and Cyrillic 1.2: every option's text is part of the question.
            raise ValueError(f"topic descriptions are at most {TOPIC_DESCRIPTION_UNITS} units (about as many "
                             "Latin characters; a Chinese character counts 3)")
        return description


class AnalyticsTopics(BaseModel):
    """How an agent's topic question is built: from its sources, from the owner's list, or not at all."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto", "custom", "off"] = "auto"
    items: List[AnalyticsTopic] = []

    @field_validator("items")
    @classmethod
    def _items(cls, value: List[AnalyticsTopic]) -> List[AnalyticsTopic]:
        max_topics, _ = _limits()
        if len(value) > max_topics:
            raise ValueError(f"at most {max_topics} topics")
        seen = set()
        for topic in value:
            key = topic.name.lower()
            if key in seen:
                raise ValueError(f"duplicate topic '{topic.name}'")
            seen.add(key)
        return value


class AnalyticsTag(BaseModel):
    """A custom yes/no label the owner defines; its id keeps its history across renames."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not TAG_ID.match(value or ""):
            raise ValueError("tag ids are 8 to 32 lowercase letters or digits")
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        name = (value or "").strip()
        if not name:
            raise ValueError("a tag needs a name")
        if len(name) > TAG_NAME_CHARS:
            raise ValueError(f"tag names are at most {TAG_NAME_CHARS} characters")
        return name

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        description = (value or "").strip()
        if not description:
            raise ValueError("a tag needs a description: it is what the model reads")
        if len(description) > TAG_DESCRIPTION_CHARS:
            raise ValueError(f"tag descriptions are at most {TAG_DESCRIPTION_CHARS} characters")
        return description


class AnalyticsConfig(BaseModel):
    """Per-agent conversation analytics, stored in ``agents.config.analytics``.

    Attributes:
        enabled: Whether the agent's conversations are labelled while ``DECISION_ANALYTICS_ENABLED`` is on.
        topics: The topic question.
        tags: Custom tags, each asked once per idle conversation.
        digest: Send the owner the weekly in-app docs-gap digest.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    topics: AnalyticsTopics = AnalyticsTopics()
    tags: List[AnalyticsTag] = []
    digest: bool = False

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: List[AnalyticsTag]) -> List[AnalyticsTag]:
        _, max_tags = _limits()
        if len(value) > max_tags:
            raise ValueError(f"at most {max_tags} tags")
        ids, names = set(), set()
        for tag in value:
            if tag.id in ids:
                raise ValueError(f"duplicate tag id '{tag.id}'")
            if tag.name.lower() in names:
                raise ValueError(f"duplicate tag '{tag.name}'")
            ids.add(tag.id)
            names.add(tag.name.lower())
        return value

    @classmethod
    def parse(cls, raw: Optional[dict]) -> "AnalyticsConfig":
        """Lenient read: never raises.

        A list longer than the current limit is cut to it; anything else that no longer validates falls back to
        the defaults, keeping the two switches when they are booleans.
        """
        if not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:
            pass
        max_topics, max_tags = _limits()
        trimmed = dict(raw)
        if isinstance(raw.get("tags"), list):
            trimmed["tags"] = raw["tags"][:max_tags]
        if isinstance(raw.get("topics"), dict) and isinstance(raw["topics"].get("items"), list):
            trimmed["topics"] = {**raw["topics"], "items": raw["topics"]["items"][:max_topics]}
        try:
            return cls.model_validate(trimmed)
        except Exception:
            logger.warning("Agent analytics config is unusable; labelling with the defaults until it is re-saved")
        switches = {key: raw[key] for key in ("enabled", "digest") if isinstance(raw.get(key), bool)}
        return cls(**switches)
