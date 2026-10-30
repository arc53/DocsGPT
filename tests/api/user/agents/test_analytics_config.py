"""``agents.config.analytics``: its validation limits, its lenient read, and that it is not policy."""

from __future__ import annotations

import pytest

from docsgpt.analytics.config import AnalyticsConfig, AnalyticsConfigError
from docsgpt.api.user.agents.routes import _policy_changed, normalize_agent_config
from docsgpt.core.settings import settings
from docsgpt.guardrails.config import AgentConfig


def _topic(i: int, **extra) -> dict:
    return {"id": f"topic{i:04d}", "name": f"Topic {i}", "description": "", "overlap": False, **extra}


def _overlap(i: int, **extra) -> dict:
    return _topic(i, **{"description": "Asks about something.", "overlap": True, **extra})


def _config(**analytics) -> dict:
    return {"analytics": analytics}


TWO_CONTROLS = {
    "enabled": True,
    "mode": "scan_all",
    "controls": [
        {"check": "secrets", "stage": "output", "action": "redact"},
        {"check": "pii", "stage": "output", "action": "redact"},
    ],
}


@pytest.fixture
def narrowed_checks(monkeypatch):
    """Only ``pii`` allowed, as after an operator tightened ``GUARDRAILS_CHECKS_ENABLED``: ``secrets`` controls
    no longer validate."""
    from docsgpt.guardrails.guardrail_creator import GuardrailCreator

    monkeypatch.setattr(settings, "GUARDRAILS_CHECKS_ENABLED", ["pii"])
    monkeypatch.setattr(GuardrailCreator, "_bootstrapped", False)
    yield


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

    def test_dropping_a_control_that_no_longer_validates_is(self, narrowed_checks):
        # The lenient read drops a control whose check the operator turned off; it comes back once turned on
        # again, so a save without it removes a control, not a dead entry.
        stored = {"guardrails": TWO_CONTROLS, "api_write_allowlist": []}
        new = normalize_agent_config({"guardrails": {**TWO_CONTROLS, "controls": TWO_CONTROLS["controls"][1:]},
                                      "analytics": {"enabled": False}})
        assert _policy_changed({"config": stored}, {"config": new})

    def test_a_block_that_no_longer_validates_dropped_whole_is(self):
        stored = {"guardrails": {**TWO_CONTROLS, "mode": "legacy_mode"}}
        assert _policy_changed({"config": stored}, {"config": normalize_agent_config({"analytics": {}})})

    def test_a_guardrails_change_still_is(self):
        new = {"guardrails": {"enabled": False}, "api_write_allowlist": [], "analytics": {}}
        assert _policy_changed({"config": self.GUARDED}, {"config": new})
        assert _policy_changed({"config": None}, {"config": {"guardrails": {"enabled": True}}})


@pytest.mark.unit
class TestLoweredLimits:
    """An operator lowering a limit leaves agents past it saveable, as long as they don't grow."""

    STORED = _config(topics=[_overlap(i) for i in range(5)] + [_topic(i) for i in range(5, 9)])

    @pytest.mark.parametrize("limit", [3, 0])
    def test_a_stored_count_past_a_lowered_limit_still_saves(self, monkeypatch, limit):
        monkeypatch.setattr(settings, "ANALYTICS_MAX_OVERLAPPING_TOPICS", limit)
        monkeypatch.setattr(settings, "ANALYTICS_MAX_TOPICS", 2)
        renamed = _config(topics=[_overlap(0, name="Renamed")] + self.STORED["analytics"]["topics"][1:])
        saved = normalize_agent_config(renamed, stored=self.STORED)
        assert len(saved["analytics"]["topics"]) == 9

    def test_fewer_still_saves(self, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_MAX_OVERLAPPING_TOPICS", 3)
        fewer = _config(topics=[_overlap(i) for i in range(4)])
        assert len(normalize_agent_config(fewer, stored=self.STORED)["analytics"]["topics"]) == 4

    def test_growing_past_the_limit_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_MAX_OVERLAPPING_TOPICS", 3)
        grown = _config(topics=self.STORED["analytics"]["topics"] + [_overlap(9)])
        with pytest.raises(AnalyticsConfigError, match="at most 5 topics that can overlap"):
            normalize_agent_config(grown, stored=self.STORED)
        # A topic moved to the other kind grows that kind.
        monkeypatch.setattr(settings, "ANALYTICS_MAX_TOPICS", 4)
        moved = _config(topics=[_overlap(0, overlap=False, description="")]
                        + self.STORED["analytics"]["topics"][1:])
        with pytest.raises(AnalyticsConfigError, match="at most 4 topics that don't overlap"):
            normalize_agent_config(moved, stored=self.STORED)

    def test_without_a_stored_config_the_limits_hold(self, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_MAX_OVERLAPPING_TOPICS", 3)
        with pytest.raises(AnalyticsConfigError, match="at most 3 topics that can overlap"):
            normalize_agent_config(self.STORED)
        with pytest.raises(AnalyticsConfigError):
            normalize_agent_config(self.STORED, stored={"analytics": "not an object"})

    def test_only_analytics_failures_are_analytics_errors(self):
        with pytest.raises(ValueError) as caught:
            normalize_agent_config({"guardrails": {"controls": [{"check": "nope", "stage": "input"}]}})
        assert not isinstance(caught.value, AnalyticsConfigError)
        with pytest.raises(AnalyticsConfigError):
            normalize_agent_config(_config(hidden_folders=["n" * 61]))


def _put(app, pg_conn, user: str, agent_id: str, body: dict):
    from contextlib import contextmanager
    from unittest.mock import patch

    from docsgpt.api.user.agents.routes import UpdateAgent

    @contextmanager
    def _yield():
        yield pg_conn

    with patch("docsgpt.api.user.agents.routes.db_session", _yield), \
            patch("docsgpt.api.user.agents.routes.db_readonly", _yield), \
            app.test_request_context(f"/api/update_agent/{agent_id}", method="PUT", json=body):
        from flask import request
        request.decoded_token = {"sub": user}
        return UpdateAgent().put(agent_id)


@pytest.fixture
def app():
    from flask import Flask

    return Flask(__name__)


class TestUpdateAgentRoute:
    def _agent(self, pg_conn, config: dict, **extra) -> dict:
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        return AgentsRepository(pg_conn).create("owner", "a", "draft", config=config, **extra)

    def _saved(self, pg_conn, agent: dict) -> dict:
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        return AgentsRepository(pg_conn).get_by_id(str(agent["id"]))

    @pytest.mark.parametrize("limit", [3, 0])
    def test_a_rename_saves_an_agent_past_a_lowered_limit(self, app, pg_conn, monkeypatch, limit):
        stored = normalize_agent_config(_config(topics=[_overlap(i) for i in range(5)]))
        agent = self._agent(pg_conn, stored)
        monkeypatch.setattr(settings, "ANALYTICS_MAX_OVERLAPPING_TOPICS", limit)
        response = _put(app, pg_conn, "owner", str(agent["id"]), {"name": "Renamed", "config": stored})
        assert response.status_code == 200, response.json
        assert self._saved(pg_conn, agent)["name"] == "Renamed"

    def test_an_insights_save_keeps_a_control_that_no_longer_validates(self, app, pg_conn, narrowed_checks):
        # The insights sheet sends the stored config back with its own changes: guardrails it does not change
        # are not validated again, so a control the operator turned off neither blocks the save nor is lost.
        stored = {"guardrails": TWO_CONTROLS, "api_write_allowlist": [], "analytics": {"enabled": True}}
        agent = self._agent(pg_conn, stored)
        response = _put(app, pg_conn, "owner", str(agent["id"]),
                        {"config": {**stored, "analytics": {"enabled": False}}})
        assert response.status_code == 200, response.json
        saved = self._saved(pg_conn, agent)["config"]
        assert saved["guardrails"] == TWO_CONTROLS and saved["analytics"]["enabled"] is False

    def test_a_guardrails_change_is_validated_whole(self, app, pg_conn, narrowed_checks):
        from docsgpt.api.user.agents.routes import INVALID_CONFIG_MESSAGE

        stored = {"guardrails": TWO_CONTROLS, "api_write_allowlist": []}
        agent = self._agent(pg_conn, stored)
        changed = {**stored, "guardrails": {**TWO_CONTROLS, "mode": "monitor_only"}}
        response = _put(app, pg_conn, "owner", str(agent["id"]), {"config": changed})
        assert response.status_code == 400 and response.json["message"] == INVALID_CONFIG_MESSAGE

    def test_adding_past_the_limit_is_400_with_the_analytics_message(self, app, pg_conn, monkeypatch):
        from docsgpt.api.user.agents.routes import ANALYTICS_INVALID_CONFIG_MESSAGES, INVALID_CONFIG_MESSAGE

        stored = normalize_agent_config(_config(topics=[_overlap(i) for i in range(5)]))
        agent = self._agent(pg_conn, stored)
        monkeypatch.setattr(settings, "ANALYTICS_MAX_OVERLAPPING_TOPICS", 3)
        grown = {**stored, "analytics": {**stored["analytics"],
                                         "topics": stored["analytics"]["topics"] + [_overlap(6)]}}
        response = _put(app, pg_conn, "owner", str(agent["id"]), {"config": grown})
        assert response.status_code == 400
        assert response.json["message"] == ANALYTICS_INVALID_CONFIG_MESSAGES["topics"] != INVALID_CONFIG_MESSAGE
        assert len(self._saved(pg_conn, agent)["config"]["analytics"]["topics"]) == 5

    def test_a_long_named_flat_source_can_be_hidden_and_edited(self, app, pg_conn):
        from docsgpt.analytics import topics
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        long_name = "Q3-2025 Vendor Due Diligence Questionnaire - Halvorsen Logistics (final, signed).pdf"
        repo = SourcesRepository(pg_conn)
        flat = repo.create(long_name, user_id="owner",
                           directory_structure={"questionnaire.pdf": {"token_count": 900}})
        docs = repo.create("Docs", user_id="owner", directory_structure={"guides": {"setup.md": {"token_count": 9}}})
        agent = self._agent(pg_conn, normalize_agent_config({}), source_id=str(docs["id"]),
                            extra_source_ids=[str(flat["id"])])
        folder = topics.folders_of(pg_conn, self._saved(pg_conn, agent))[0]["name"]
        assert len(folder) <= 60

        hidden = normalize_agent_config(_config(hidden_folders=[folder]))
        response = _put(app, pg_conn, "owner", str(agent["id"]), {"config": hidden})
        assert response.status_code == 200, response.json
        response = _put(app, pg_conn, "owner", str(agent["id"]), {"name": "Renamed"})
        assert response.status_code == 200, response.json

        edited = normalize_agent_config(_config(hidden_folders=[folder], topics=[_topic(1, name=folder)]))
        response = _put(app, pg_conn, "owner", str(agent["id"]), {"config": edited})
        assert response.status_code == 200, response.json
        saved = self._saved(pg_conn, agent)["config"]["analytics"]
        assert topics.options(pg_conn, self._saved(pg_conn, agent), AnalyticsConfig.parse(saved)) == {
            "guides": "Pages such as: Setup", folder: None}
