"""An agent row's unset columns read as their defaults on a run.

Postgres rows carry every column, so a column the agent never set is an
explicit ``None`` (or a legacy ``""``) rather than a missing key, and
``dict.get(key, default)`` returns it instead of the default. A promptable
share's backing agent had no ``agent_type`` and failed every turn.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docsgpt.api.answer.services.stream_processor import StreamProcessor

SP = "docsgpt.api.answer.services.stream_processor"


def _row(**overrides) -> dict:
    row = {
        "id": "a1",
        "user_id": "owner",
        "key": "share_key",
        "agent_type": None,
        "prompt_id": None,
        "default_model_id": None,
        "models": None,
        "json_schema": None,
        "source_id": None,
        "extra_source_ids": [],
    }
    row.update(overrides)
    return row


@pytest.mark.unit
class TestAgentRunData:
    @pytest.mark.parametrize("agent_type", [None, "", "  "])
    def test_blank_type_is_the_default(self, agent_type):
        sp = StreamProcessor(request_data={}, decoded_token={"sub": "owner"})
        with patch(f"{SP}.settings") as mock_settings:
            mock_settings.AGENT_NAME = "classic"
            data = sp._agent_run_data(MagicMock(), _row(agent_type=agent_type))
        assert data["agent_type"] == "classic"
        assert data["prompt_id"] == "default"
        assert data["default_model_id"] == ""
        assert data["models"] == []

    def test_set_values_are_kept(self):
        sp = StreamProcessor(request_data={}, decoded_token={"sub": "owner"})
        data = sp._agent_run_data(
            MagicMock(), _row(agent_type="agentic", default_model_id="m", models=["m"], prompt_id="creative"),
        )
        assert data["agent_type"] == "agentic"
        assert data["default_model_id"] == "m"
        assert data["models"] == ["m"]
        assert data["prompt_id"] == "creative"


@pytest.mark.unit
class TestConfigureAgent:
    def test_null_columns_from_the_key_path_use_defaults(self):
        sp = StreamProcessor(request_data={"api_key": "share_key"}, decoded_token=None)
        sp._resolve_agent_id = MagicMock(return_value=None)
        sp._get_agent_key = MagicMock(return_value=(None, False, None))
        # Bypass _agent_run_data: _configure_agent guards on its own.
        sp._get_data_from_api_key = MagicMock(return_value={**_row(), "_id": "a1", "user": "owner"})
        with patch(f"{SP}.settings") as mock_settings:
            mock_settings.AGENT_NAME = "classic"
            sp._configure_agent()
        assert sp.agent_config["agent_type"] == "classic"
        assert sp.agent_config["prompt_id"] == "default"
        assert sp.agent_config["default_model_id"] == ""
        assert sp.agent_config["models"] == []
