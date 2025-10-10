from unittest.mock import Mock, mock_open, patch

import pytest
from application.agents.react_agent import ReActAgent


@pytest.mark.unit
class TestReActAgent:

    def test_react_agent_initialization(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ReActAgent(**agent_base_params)

        assert isinstance(agent, ReActAgent)
        assert agent.plan == ""
        assert agent.observations == []

    def test_react_agent_inherits_base_properties(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ReActAgent(**agent_base_params)

        assert agent.endpoint == agent_base_params["endpoint"]
        assert agent.llm_name == agent_base_params["llm_name"]
        assert agent.gpt_model == agent_base_params["gpt_model"]


@pytest.mark.unit
class TestReActAgentContentExtraction:

    def test_extract_content_from_string(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ReActAgent(**agent_base_params)

        response = "Simple string response"
        content = agent._extract_content_from_llm_response(response)

        assert content == "Simple string response"

    def test_extract_content_from_message_object(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ReActAgent(**agent_base_params)

        response = Mock()
        response.message = Mock()
        response.message.content = "Message content"

        content = agent._extract_content_from_llm_response(response)

        assert content == "Message content"

    def test_extract_content_from_openai_response(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ReActAgent(**agent_base_params)

        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message = Mock()
        response.choices[0].message.content = "OpenAI content"
        response.message = None
        response.content = None

        content = agent._extract_content_from_llm_response(response)

        assert content == "OpenAI content"

    def test_extract_content_from_anthropic_response(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ReActAgent(**agent_base_params)

        text_block = Mock()
        text_block.text = "Anthropic content"

        response = Mock()
        response.content = [text_block]
        response.message = None
        response.choices = None

        content = agent._extract_content_from_llm_response(response)

        assert content == "Anthropic content"

    def test_extract_content_from_openai_stream(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ReActAgent(**agent_base_params)

        chunk1 = Mock()
        chunk1.choices = [Mock()]
        chunk1.choices[0].delta = Mock()
        chunk1.choices[0].delta.content = "Part 1 "

        chunk2 = Mock()
        chunk2.choices = [Mock()]
        chunk2.choices[0].delta = Mock()
        chunk2.choices[0].delta.content = "Part 2"

        response = iter([chunk1, chunk2])
        content = agent._extract_content_from_llm_response(response)

        assert content == "Part 1 Part 2"

    def test_extract_content_from_anthropic_stream(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ReActAgent(**agent_base_params)

        chunk1 = Mock()
        chunk1.type = "content_block_delta"
        chunk1.delta = Mock()
        chunk1.delta.text = "Stream 1 "
        chunk1.choices = []

        chunk2 = Mock()
        chunk2.type = "content_block_delta"
        chunk2.delta = Mock()
        chunk2.delta.text = "Stream 2"
        chunk2.choices = []

        response = iter([chunk1, chunk2])
        content = agent._extract_content_from_llm_response(response)

        assert content == "Stream 1 Stream 2"

    def test_extract_content_from_string_stream(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ReActAgent(**agent_base_params)

        response = iter(["chunk1", "chunk2", "chunk3"])
        content = agent._extract_content_from_llm_response(response)

        assert content == "chunk1chunk2chunk3"

    def test_extract_content_handles_none_content(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ReActAgent(**agent_base_params)

        response = Mock()
        response.message = Mock()
        response.message.content = None
        response.choices = None
        response.content = None

        content = agent._extract_content_from_llm_response(response)

        assert content == ""


@pytest.mark.unit
class TestReActAgentPlanning:

    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data="Test planning prompt: {query} {summaries} {prompt} {observations}",
    )
    def test_create_plan(
        self,
        mock_file,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        def mock_gen_stream(*args, **kwargs):
            yield "Plan step 1"
            yield "Plan step 2"

        mock_llm.gen_stream = Mock(return_value=mock_gen_stream())

        agent = ReActAgent(**agent_base_params)
        agent.observations = ["Observation 1"]

        plan_chunks = list(agent._create_plan("Test query", "Test docs", log_context))

        assert len(plan_chunks) == 2
        assert plan_chunks[0] == "Plan step 1"
        assert plan_chunks[1] == "Plan step 2"

        mock_llm.gen_stream.assert_called_once()

    @patch("builtins.open", new_callable=mock_open, read_data="Test: {query}")
    def test_create_plan_fills_template(
        self,
        mock_file,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["Plan"]))

        agent = ReActAgent(**agent_base_params)
        list(agent._create_plan("My query", "Docs", log_context))

        call_args = mock_llm.gen_stream.call_args[1]
        messages = call_args["messages"]

        assert "My query" in messages[0]["content"]


@pytest.mark.unit
class TestReActAgentFinalAnswer:

    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data="Final answer for: {query} with {observations}",
    )
    def test_create_final_answer(
        self,
        mock_file,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        def mock_gen_stream(*args, **kwargs):
            yield "Final "
            yield "answer"

        mock_llm.gen_stream = Mock(return_value=mock_gen_stream())

        agent = ReActAgent(**agent_base_params)
        observations = ["Obs 1", "Obs 2"]

        answer_chunks = list(
            agent._create_final_answer("Test query", observations, log_context)
        )

        assert len(answer_chunks) == 2
        assert answer_chunks[0] == "Final "
        assert answer_chunks[1] == "answer"

    @patch("builtins.open", new_callable=mock_open, read_data="Answer: {observations}")
    def test_create_final_answer_truncates_long_observations(
        self,
        mock_file,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))

        agent = ReActAgent(**agent_base_params)
        long_obs = ["A" * 15000]

        list(agent._create_final_answer("Query", long_obs, log_context))

        call_args = mock_llm.gen_stream.call_args[1]
        messages = call_args["messages"]

        assert "observations truncated" in messages[0]["content"]

    @patch("builtins.open", new_callable=mock_open, read_data="Test: {query}")
    def test_create_final_answer_no_tools(
        self,
        mock_file,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))

        agent = ReActAgent(**agent_base_params)
        list(agent._create_final_answer("Query", ["Obs"], log_context))

        call_args = mock_llm.gen_stream.call_args[1]

        assert call_args["tools"] is None


@pytest.mark.unit
class TestReActAgentGenInner:

    @patch(
        "builtins.open", new_callable=mock_open, read_data="Prompt template: {query}"
    )
    def test_gen_inner_resets_state(
        self,
        mock_file,
        agent_base_params,
        mock_retriever,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        mock_mongo_db,
        log_context,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["SATISFIED"]))

        def mock_handler(*args, **kwargs):
            yield "SATISFIED"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ReActAgent(**agent_base_params)
        agent.plan = "Old plan"
        agent.observations = ["Old obs"]

        list(agent._gen_inner("New query", mock_retriever, log_context))

        assert agent.plan != "Old plan"
        assert len(agent.observations) > 0

    @patch("builtins.open", new_callable=mock_open, read_data="Prompt: {query}")
    def test_gen_inner_stops_on_satisfied(
        self,
        mock_file,
        agent_base_params,
        mock_retriever,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        mock_mongo_db,
        log_context,
    ):
        iteration_count = 0

        def mock_gen_stream(*args, **kwargs):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count == 1:
                yield "Plan"
            else:
                yield "SATISFIED - done"

        mock_llm.gen_stream = Mock(
            side_effect=lambda *args, **kwargs: mock_gen_stream(*args, **kwargs)
        )

        def mock_handler(*args, **kwargs):
            yield "SATISFIED - done"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ReActAgent(**agent_base_params)
        results = list(agent._gen_inner("Test query", mock_retriever, log_context))

        assert any("answer" in r for r in results)

    @patch("builtins.open", new_callable=mock_open, read_data="Prompt: {query}")
    def test_gen_inner_max_iterations(
        self,
        mock_file,
        agent_base_params,
        mock_retriever,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        mock_mongo_db,
        log_context,
    ):
        call_count = 0

        def mock_gen_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield f"Iteration {call_count}"

        mock_llm.gen_stream = Mock(
            side_effect=lambda *args, **kwargs: mock_gen_stream(*args, **kwargs)
        )

        def mock_handler(*args, **kwargs):
            yield "Continue..."

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ReActAgent(**agent_base_params)

        results = list(agent._gen_inner("Test query", mock_retriever, log_context))

        thought_results = [r for r in results if "thought" in r]
        assert len(thought_results) > 0

    @patch("builtins.open", new_callable=mock_open, read_data="Prompt: {query}")
    def test_gen_inner_yields_sources(
        self,
        mock_file,
        agent_base_params,
        mock_retriever,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        mock_mongo_db,
        log_context,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["SATISFIED"]))

        def mock_handler(*args, **kwargs):
            yield "SATISFIED"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ReActAgent(**agent_base_params)
        results = list(agent._gen_inner("Test query", mock_retriever, log_context))

        sources = [r for r in results if "sources" in r]
        assert len(sources) >= 1

    @patch("builtins.open", new_callable=mock_open, read_data="Prompt: {query}")
    def test_gen_inner_yields_tool_calls(
        self,
        mock_file,
        agent_base_params,
        mock_retriever,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        mock_mongo_db,
        log_context,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["SATISFIED"]))

        def mock_handler(*args, **kwargs):
            yield "SATISFIED"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ReActAgent(**agent_base_params)
        agent.tool_calls = [{"tool": "test", "result": "A" * 100}]

        results = list(agent._gen_inner("Test query", mock_retriever, log_context))

        tool_call_results = [r for r in results if "tool_calls" in r]
        if tool_call_results:
            assert len(tool_call_results[0]["tool_calls"][0]["result"]) <= 53

    @patch("builtins.open", new_callable=mock_open, read_data="Prompt: {query}")
    def test_gen_inner_logs_observations(
        self,
        mock_file,
        agent_base_params,
        mock_retriever,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        mock_mongo_db,
        log_context,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["SATISFIED"]))

        def mock_handler(*args, **kwargs):
            yield "SATISFIED"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ReActAgent(**agent_base_params)
        list(agent._gen_inner("Test query", mock_retriever, log_context))

        assert len(agent.observations) > 0


@pytest.mark.integration
class TestReActAgentIntegration:

    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data="Prompt: {query} {summaries} {prompt} {observations}",
    )
    def test_full_react_workflow(
        self,
        mock_file,
        agent_base_params,
        mock_retriever,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        mock_mongo_db,
        log_context,
    ):
        call_sequence = []

        def mock_gen_stream(*args, **kwargs):
            call_sequence.append("gen_stream")
            if len(call_sequence) <= 2:
                yield "Planning..."
            else:
                yield "SATISFIED final answer"

        mock_llm.gen_stream = Mock(
            side_effect=lambda *args, **kwargs: mock_gen_stream(*args, **kwargs)
        )

        def mock_handler(*args, **kwargs):
            call_sequence.append("handler")
            yield "SATISFIED final answer"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ReActAgent(**agent_base_params)
        results = list(agent._gen_inner("Complex query", mock_retriever, log_context))

        assert len(results) > 0
        assert any("thought" in r for r in results)
        assert any("answer" in r for r in results)
