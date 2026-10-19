"""``agents.config.analytics``: its validation limits, its lenient read, and that it is not policy."""

from __future__ import annotations

import pytest

from docsgpt.analytics.config import AnalyticsConfig
from docsgpt.api.user.agents.routes import _policy_changed, normalize_agent_config
from docsgpt.core.settings import settings
from docsgpt.guardrails.config import AgentConfig


def _tag(i: int, **extra) -> dict:
    return {"id": f"tag{i:05d}", "name": f"Tag {i}", "description": "Asks about something.", **extra}


def _config(**analytics) -> dict:
    return {"analytics": analytics}


@pytest.mark.unit
class TestAnalyticsConfigValidation:
    def test_defaults(self):
        assert AgentConfig().model_dump(mode="json")["analytics"] == {
            "enabled": True, "topics": {"mode": "auto", "items": []}, "tags": [], "digest": False,
        }

    def test_a_full_config_round_trips(self):
        raw = _config(enabled=False, digest=True, topics={"mode": "custom", "items": [
            {"name": "Installation", "description": "Pages such as: Install; Upgrade"}]}, tags=[_tag(1)])
        assert normalize_agent_config(raw)["analytics"] == {
            "enabled": False, "digest": True,
            "topics": {"mode": "custom", "items": [{"name": "Installation",
                                                     "description": "Pages such as: Install; Upgrade"}]},
            "tags": [_tag(1)],
        }

    @pytest.mark.parametrize(
        "analytics, message",
        [
            ({"unknown": 1}, "Extra inputs"),
            ({"topics": {"mode": "clusters"}}, "topics.mode"),
            ({"topics": {"items": [{"name": "A"}, {"name": "a"}]}}, "duplicate topic"),
            ({"topics": {"items": [{"name": " "}]}}, "needs a name"),
            ({"topics": {"items": [{"name": "None of these"}]}}, "always offered"),
            ({"topics": {"items": [{"name": "A", "description": "x" * 151}]}}, "150 units"),
            ({"topics": {"items": [{"name": "A", "description": "字" * 51}]}}, "150 units"),
            ({"tags": [_tag(1, id="Tag-1")]}, "8 to 32 lowercase"),
            ({"tags": [_tag(1, id="abc")]}, "8 to 32 lowercase"),
            ({"tags": [_tag(1), _tag(1, name="Other")]}, "duplicate tag id"),
            ({"tags": [_tag(1), _tag(2, name="tag 1")]}, "duplicate tag 'tag 1'"),
            ({"topics": {"items": [{"name": "n" * 61}]}}, "60 characters"),
            ({"tags": [_tag(1, name="n" * 61)]}, "60 characters"),
            ({"tags": [_tag(1, description="d" * 301)]}, "300 characters"),
            ({"tags": [_tag(1, description="  ")]}, "needs a description"),
        ],
    )
    def test_limits(self, analytics, message):
        with pytest.raises(ValueError, match=message):
            normalize_agent_config({"analytics": analytics})

    def test_a_150_unit_description_in_cjk_is_50_characters(self):
        topic = {"name": "安装", "description": "字" * 50}
        assert normalize_agent_config(_config(topics={"items": [topic]}))["analytics"]["topics"]["items"] == [topic]

    def test_list_limits_follow_the_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_MAX_TAGS", 2)
        monkeypatch.setattr(settings, "ANALYTICS_MAX_TOPICS", 2)
        with pytest.raises(ValueError, match="at most 2 tags"):
            normalize_agent_config(_config(tags=[_tag(i) for i in range(3)]))
        with pytest.raises(ValueError, match="at most 2 topics"):
            normalize_agent_config(_config(topics={"items": [{"name": n} for n in "abc"]}))
        assert len(normalize_agent_config(_config(tags=[_tag(i) for i in range(2)]))["analytics"]["tags"]) == 2


@pytest.mark.unit
class TestLenientRead:
    def test_a_list_past_a_lowered_limit_is_cut(self, monkeypatch):
        raw = {"enabled": True, "tags": [_tag(i) for i in range(5)]}
        monkeypatch.setattr(settings, "ANALYTICS_MAX_TAGS", 3)
        assert [t.id for t in AnalyticsConfig.parse(raw).tags] == ["tag00000", "tag00001", "tag00002"]

    def test_a_broken_block_keeps_its_switches(self):
        parsed = AnalyticsConfig.parse({"enabled": False, "digest": True, "tags": "not a list"})
        assert (parsed.enabled, parsed.digest, parsed.tags) == (False, True, [])
        assert AnalyticsConfig.parse(None) == AnalyticsConfig()

    def test_analytics_past_a_lowered_limit_keeps_a_valid_allowlist(self, monkeypatch):
        raw = {"api_write_allowlist": ["tool1:send"], "analytics": {"tags": [_tag(i) for i in range(5)]}}
        monkeypatch.setattr(settings, "ANALYTICS_MAX_TAGS", 3)
        parsed = AgentConfig.parse(raw)
        assert parsed.api_write_allowlist == ["tool1:send"] and len(parsed.analytics.tags) == 3

    def test_a_bad_allowlist_keeps_the_analytics_block(self):
        raw = {"api_write_allowlist": ["no-colon"], "analytics": {"enabled": False}}
        parsed = AgentConfig.parse(raw)
        assert parsed.api_write_allowlist == [] and parsed.analytics.enabled is False


@pytest.mark.unit
class TestNotPolicy:
    GUARDED = {"guardrails": {"enabled": True}, "api_write_allowlist": []}

    def test_an_analytics_only_change_is_not_a_policy_change(self):
        new = {**self.GUARDED, "analytics": {"enabled": False, "tags": [_tag(1)]}}
        assert not _policy_changed({"config": self.GUARDED}, {"config": new})
        assert not _policy_changed({"config": {**self.GUARDED, "analytics": {"enabled": True}}}, {"config": new})

    def test_a_stored_config_from_before_analytics_is_unchanged_by_its_defaults(self):
        normalized = normalize_agent_config(self.GUARDED)
        stored = {key: value for key, value in normalized.items() if key != "analytics"}
        assert normalized["analytics"] == AnalyticsConfig().model_dump(mode="json")
        assert not _policy_changed({"config": stored}, {"config": normalized})

    def test_a_guardrails_change_still_is(self):
        new = {"guardrails": {"enabled": False}, "api_write_allowlist": [], "analytics": {}}
        assert _policy_changed({"config": self.GUARDED}, {"config": new})
        assert _policy_changed({"config": None}, {"config": {"guardrails": {"enabled": True}}})
