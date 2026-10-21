"""``agents.config.analytics``: its validation limits, its lenient read, and that it is not policy."""

from __future__ import annotations

import pytest

from docsgpt.analytics.config import AnalyticsConfig
from docsgpt.api.user.agents.routes import _policy_changed, normalize_agent_config
from docsgpt.core.settings import settings
from docsgpt.guardrails.config import AgentConfig


def _topic(i: int, **extra) -> dict:
    return {"id": f"topic{i:04d}", "name": f"Topic {i}", "description": "", "overlap": False, **extra}


def _overlap(i: int, **extra) -> dict:
    return _topic(i, **{"description": "Asks about something.", "overlap": True, **extra})


def _config(**analytics) -> dict:
    return {"analytics": analytics}


@pytest.mark.unit
class TestAnalyticsConfigValidation:
    def test_defaults(self):
        assert AgentConfig().model_dump(mode="json")["analytics"] == {
            "enabled": True, "topics": [], "hidden_folders": [], "digest": False,
        }

    def test_a_full_config_round_trips(self):
        raw = _config(enabled=False, digest=True, hidden_folders=["using"], topics=[
            _topic(1, name="Installation", description="Pages such as: Install; Upgrade"), _overlap(2)])
        assert normalize_agent_config(raw)["analytics"] == {
            "enabled": False, "digest": True, "hidden_folders": ["using"],
            "topics": [_topic(1, name="Installation", description="Pages such as: Install; Upgrade"), _overlap(2)],
        }

    def test_the_kinds(self):
        config = AnalyticsConfig.model_validate({"topics": [_topic(1), _overlap(2), _topic(3)]})
        assert [t.id for t in config.one_pick()] == ["topic0001", "topic0003"]
        assert [t.id for t in config.overlapping()] == ["topic0002"]

    def test_an_overlapping_topic_needs_no_description(self):
        config = normalize_agent_config(_config(topics=[_overlap(1, description=" ")]))
        assert config["analytics"]["topics"][0]["description"] == ""

    @pytest.mark.parametrize(
        "analytics, message",
        [
            ({"unknown": 1}, "Extra inputs"),
            ({"tags": []}, "Extra inputs"),
            ({"topics": {"mode": "auto"}}, "valid list"),
            ({"topics": [_topic(1, name="A"), _topic(2, name="a")]}, "duplicate topic 'a'"),
            ({"topics": [_topic(1, name="A"), _overlap(2, name="a")]}, "duplicate topic 'a'"),
            ({"topics": [_topic(1), _topic(1, name="Other")]}, "duplicate topic id"),
            ({"topics": [_topic(1, name=" ")]}, "needs a name"),
            ({"topics": [_topic(1, name="None of these")]}, "always offered"),
            ({"topics": [_overlap(1, name="None of these")]}, "always offered"),
            ({"topics": [_topic(1, name="n" * 61)]}, "60 characters"),
            ({"topics": [_topic(1, description="x" * 151)]}, "150 units"),
            ({"topics": [_topic(1, description="字" * 51)]}, "150 units"),
            ({"topics": [_overlap(1, description="x" * 301)]}, "300 units"),
            ({"topics": [_overlap(1, description="字" * 101)]}, "300 units"),
            ({"topics": [_topic(1, id="Topic-1")]}, "8 to 32 lowercase"),
            ({"topics": [_topic(1, id="abc")]}, "8 to 32 lowercase"),
            ({"hidden_folders": ["a", "A"]}, "duplicate hidden folder"),
            ({"hidden_folders": ["n" * 61]}, "60 characters"),
            ({"hidden_folders": [f"f{i}" for i in range(101)]}, "at most 100 hidden folders"),
        ],
    )
    def test_limits(self, analytics, message):
        with pytest.raises(ValueError, match=message):
            normalize_agent_config({"analytics": analytics})

    def test_a_150_unit_description_in_cjk_is_50_characters(self):
        topic = _topic(1, name="安装", description="字" * 50)
        assert normalize_agent_config(_config(topics=[topic]))["analytics"]["topics"] == [topic]

    def test_list_limits_follow_the_settings_per_kind(self, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_MAX_OVERLAPPING_TOPICS", 2)
        monkeypatch.setattr(settings, "ANALYTICS_MAX_TOPICS", 2)
        with pytest.raises(ValueError, match="at most 2 topics that can overlap"):
            normalize_agent_config(_config(topics=[_overlap(i) for i in range(3)]))
        with pytest.raises(ValueError, match="at most 2 topics that don't overlap"):
            normalize_agent_config(_config(topics=[_topic(i) for i in range(3)]))
        both = [_topic(0), _topic(1), _overlap(2), _overlap(3)]
        assert len(normalize_agent_config(_config(topics=both))["analytics"]["topics"]) == 4

    def test_no_overlapping_topics_when_the_server_allows_none(self, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_MAX_OVERLAPPING_TOPICS", 0)
        with pytest.raises(ValueError, match="at most 0 topics that can overlap"):
            normalize_agent_config(_config(topics=[_overlap(1)]))


@pytest.mark.unit
class TestLenientRead:
    def test_each_kind_past_a_lowered_limit_is_cut(self, monkeypatch):
        raw = {"enabled": True, "topics": [_overlap(i) for i in range(5)] + [_topic(i) for i in range(5, 9)]}
        monkeypatch.setattr(settings, "ANALYTICS_MAX_OVERLAPPING_TOPICS", 3)
        monkeypatch.setattr(settings, "ANALYTICS_MAX_TOPICS", 2)
        parsed = AnalyticsConfig.parse(raw)
        assert [t.id for t in parsed.overlapping()] == ["topic0000", "topic0001", "topic0002"]
        assert [t.id for t in parsed.one_pick()] == ["topic0005", "topic0006"]

    def test_a_broken_block_keeps_its_switches(self):
        parsed = AnalyticsConfig.parse({"enabled": False, "digest": True, "topics": "not a list"})
        assert (parsed.enabled, parsed.digest, parsed.topics) == (False, True, [])
        assert AnalyticsConfig.parse(None) == AnalyticsConfig()

    def test_the_shape_before_one_list_reads_as_the_defaults(self):
        old = {"enabled": False, "topics": {"mode": "custom", "items": [{"name": "A"}]},
               "tags": [{"id": "tag00001", "name": "T", "description": "d"}], "digest": True}
        parsed = AnalyticsConfig.parse(old)
        assert (parsed.enabled, parsed.digest, parsed.topics, parsed.hidden_folders) == (False, True, [], [])

    def test_analytics_past_a_lowered_limit_keeps_a_valid_allowlist(self, monkeypatch):
        raw = {"api_write_allowlist": ["tool1:send"], "analytics": {"topics": [_overlap(i) for i in range(5)]}}
        monkeypatch.setattr(settings, "ANALYTICS_MAX_OVERLAPPING_TOPICS", 3)
        parsed = AgentConfig.parse(raw)
        assert parsed.api_write_allowlist == ["tool1:send"] and len(parsed.analytics.topics) == 3

    def test_a_bad_allowlist_keeps_the_analytics_block(self):
        raw = {"api_write_allowlist": ["no-colon"], "analytics": {"enabled": False}}
        parsed = AgentConfig.parse(raw)
        assert parsed.api_write_allowlist == [] and parsed.analytics.enabled is False


@pytest.mark.unit
class TestNotPolicy:
    GUARDED = {"guardrails": {"enabled": True}, "api_write_allowlist": []}

    def test_an_analytics_only_change_is_not_a_policy_change(self):
        new = {**self.GUARDED, "analytics": {"enabled": False, "topics": [_overlap(1)]}}
        assert not _policy_changed({"config": self.GUARDED}, {"config": new})
        assert not _policy_changed({"config": {**self.GUARDED, "analytics": {"enabled": True}}}, {"config": new})

    def test_a_stored_config_from_before_analytics_is_unchanged_by_its_defaults(self):
        normalized = normalize_agent_config(self.GUARDED)
        stored = {key: value for key, value in normalized.items() if key != "analytics"}
        assert normalized["analytics"] == AnalyticsConfig().model_dump(mode="json")
        assert not _policy_changed({"config": stored}, {"config": normalized})

    def test_an_analytics_save_on_a_never_normalized_config_is_not_a_policy_change(self):
        # A workflow (or an older agent) stores ``{}``; the update normalizes to every default.
        new = normalize_agent_config({"analytics": {"enabled": False, "topics": [_overlap(1)]}})
        assert not _policy_changed({"config": {}}, {"config": new})
        assert not _policy_changed({"config": None}, {"config": new})

    def test_a_guardrails_change_still_is(self):
        new = {"guardrails": {"enabled": False}, "api_write_allowlist": [], "analytics": {}}
        assert _policy_changed({"config": self.GUARDED}, {"config": new})
        assert _policy_changed({"config": None}, {"config": {"guardrails": {"enabled": True}}})
