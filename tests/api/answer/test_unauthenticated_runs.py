"""A request with no token and no API key never sets up an agent run.

The routes answer it with 401, but they used to build the agent first, so a
public agent's prompt tools were pre-fetched (run) for nobody.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestNoTokenNoRun:
    def test_build_agent_sets_nothing_up_without_a_caller(self):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({"question": "q", "agent_id": "a-1"}, None)
        with patch.object(processor, "initialize") as initialize, \
                patch.object(processor, "pre_fetch_tools") as pre_fetch_tools, \
                patch.object(processor, "create_agent") as create_agent:
            assert processor.build_agent("q") is None
        initialize.assert_not_called()
        pre_fetch_tools.assert_not_called()
        create_agent.assert_not_called()
        assert processor.decoded_token is None

    def test_api_key_request_still_runs(self):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({"question": "q", "api_key": "k"}, None)
        agent = MagicMock()

        def _initialize():
            processor.decoded_token = {"sub": "owner"}

        with patch.object(processor, "initialize", side_effect=_initialize), \
                patch.object(processor, "_exposure_partition", return_value=([], [])), \
                patch.object(processor, "pre_fetch_docs", return_value=(None, None)), \
                patch.object(processor, "pre_fetch_tools", return_value=None), \
                patch.object(processor, "create_agent", return_value=agent):
            assert processor.build_agent("q") is agent

    def test_stream_route_answers_401_without_pre_fetching(self):
        from flask import Flask

        from docsgpt.api.answer.routes.stream import StreamResource

        app = Flask(__name__)
        with app.test_request_context("/stream", method="POST", json={"question": "q", "agent_id": "a-1"}), \
                patch("docsgpt.api.answer.services.stream_processor.StreamProcessor.pre_fetch_tools") as pre, \
                patch("docsgpt.api.answer.services.stream_processor.StreamProcessor.initialize"):
            from flask import request

            request.decoded_token = None
            response = StreamResource().post()
        assert response.status_code == 401
        pre.assert_not_called()
