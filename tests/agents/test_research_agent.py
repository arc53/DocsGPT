"""Tests for ResearchAgent — multi-step research with budget controls."""

import json
import time
from unittest.mock import Mock

import pytest
from application.agents.research_agent import (
    CitationManager,
    ResearchAgent,
    DEFAULT_MAX_STEPS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TOKEN_BUDGET,
)


# ---------------------------------------------------------------------------
# CitationManager
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCitationManager:

    def test_add_returns_citation_number(self):
        cm = CitationManager()
        num = cm.add({"source": "s1", "title": "T1"})
        assert num == 1

    def test_add_deduplicates(self):
        cm = CitationManager()
        n1 = cm.add({"source": "s1", "title": "T1"})
        n2 = cm.add({"source": "s1", "title": "T1"})
        assert n1 == n2
        assert len(cm.citations) == 1

    def test_add_different_sources(self):
        cm = CitationManager()
        n1 = cm.add({"source": "s1", "title": "T1"})
        n2 = cm.add({"source": "s2", "title": "T2"})
        assert n1 != n2
        assert len(cm.citations) == 2

    def test_add_docs_returns_mapping(self):
        cm = CitationManager()
        docs = [
            {"source": "s1", "title": "Doc A"},
            {"source": "s2", "title": "Doc B"},
        ]
        text = cm.add_docs(docs)
        assert "[1] Doc A" in text
        assert "[2] Doc B" in text

    def test_format_references(self):
        cm = CitationManager()
        cm.add({"source": "http://example.com", "title": "Example", "filename": "ex.md"})
        refs = cm.format_references()
        assert "[1]" in refs
        assert "ex.md" in refs

    def test_format_references_empty(self):
        cm = CitationManager()
        assert "No sources" in cm.format_references()

    def test_get_all_docs(self):
        cm = CitationManager()
        cm.add({"source": "s1", "title": "T1"})
        cm.add({"source": "s2", "title": "T2"})
        docs = cm.get_all_docs()
        assert len(docs) == 2


# ---------------------------------------------------------------------------
# ResearchAgent Init & Budget
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResearchAgentInit:

    def test_initialization(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ResearchAgent(**agent_base_params)
        assert isinstance(agent, ResearchAgent)
        assert agent.max_steps == DEFAULT_MAX_STEPS
        assert agent.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert agent.token_budget == DEFAULT_TOKEN_BUDGET
        assert agent.retriever_config == {}

    def test_custom_budget(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ResearchAgent(
            max_steps=3,
            timeout_seconds=60,
            token_budget=50_000,
            **agent_base_params,
        )
        assert agent.max_steps == 3
        assert agent.timeout_seconds == 60
        assert agent.token_budget == 50_000

    def test_with_retriever_config(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        rc = {"source": {"active_docs": ["abc"]}}
        agent = ResearchAgent(retriever_config=rc, **agent_base_params)
        assert agent.retriever_config == rc


@pytest.mark.unit
class TestResearchAgentBudget:

    def _make_agent(self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, **kwargs):
        return ResearchAgent(**kwargs, **agent_base_params)

    def test_timeout_detection(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator,
            timeout_seconds=0,
        )
        agent._start_time = time.monotonic() - 1
        assert agent._is_timed_out() is True

    def test_not_timed_out(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator,
            timeout_seconds=300,
        )
        agent._start_time = time.monotonic()
        assert agent._is_timed_out() is False

    def test_token_budget_tracking(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator,
            token_budget=1000,
        )
        agent._track_tokens(500)
        assert agent._budget_remaining() == 500
        assert agent._is_over_budget() is False

        agent._track_tokens(500)
        assert agent._budget_remaining() == 0
        assert agent._is_over_budget() is True

    def test_snapshot_llm_tokens_returns_delta(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator,
        )
        mock_llm.token_usage = {"prompt_tokens": 100, "generated_tokens": 50}

        delta1 = agent._snapshot_llm_tokens()
        assert delta1 == 150

        # Simulate more tokens used
        mock_llm.token_usage = {"prompt_tokens": 200, "generated_tokens": 100}
        delta2 = agent._snapshot_llm_tokens()
        assert delta2 == 150  # 300 - 150

    def test_elapsed(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator,
        )
        agent._start_time = time.monotonic() - 1.5
        elapsed = agent._elapsed()
        assert elapsed >= 1.0


# ---------------------------------------------------------------------------
# ResearchAgent Phases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResearchAgentClarification:

    def test_is_follow_up_no_history(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ResearchAgent(**agent_base_params)
        assert agent._is_follow_up() is False

    def test_is_follow_up_with_clarification_metadata(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent_base_params["chat_history"] = [
            {"prompt": "What?", "response": "Clarify", "metadata": {"is_clarification": True}},
        ]
        agent = ResearchAgent(**agent_base_params)
        assert agent._is_follow_up() is True

    def test_is_follow_up_without_metadata(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent_base_params["chat_history"] = [
            {"prompt": "What?", "response": "Normal answer"},
        ]
        agent = ResearchAgent(**agent_base_params)
        assert agent._is_follow_up() is False

    def test_clarification_returns_none_on_no_clarification_needed(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator
    ):
        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message = Mock()
        response.choices[0].message.content = json.dumps(
            {"needs_clarification": False, "reason": "Clear enough"}
        )
        mock_llm.gen = Mock(return_value=response)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        result = agent._clarification_phase("What is Python?")
        assert result is None

    def test_clarification_returns_questions(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator
    ):
        clarification_json = json.dumps({
            "needs_clarification": True,
            "questions": ["Which version?", "What context?"],
        })
        # Return a plain string so _extract_text handles it directly
        mock_llm.gen = Mock(return_value=clarification_json)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        result = agent._clarification_phase("Tell me about it")
        assert result is not None
        assert "Which version?" in result
        assert "What context?" in result


@pytest.mark.unit
class TestResearchAgentPlanning:

    def test_planning_returns_steps_and_complexity(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator
    ):
        plan_json = json.dumps({
            "complexity": "moderate",
            "steps": [
                {"query": "sub-question 1", "rationale": "reason 1"},
                {"query": "sub-question 2", "rationale": "reason 2"},
            ],
        })
        # Return plain string so _extract_text handles it directly
        mock_llm.gen = Mock(return_value=plan_json)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        steps, complexity = agent._planning_phase("Compare A and B")

        assert complexity == "moderate"
        assert len(steps) == 2
        assert steps[0]["query"] == "sub-question 1"

    def test_planning_caps_steps_by_complexity(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator
    ):
        plan_json = json.dumps({
            "complexity": "simple",
            "steps": [
                {"query": f"q{i}", "rationale": f"r{i}"} for i in range(10)
            ],
        })
        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message = Mock()
        response.choices[0].message.content = plan_json
        mock_llm.gen = Mock(return_value=response)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        steps, complexity = agent._planning_phase("Simple question")

        assert complexity == "simple"
        assert len(steps) <= 2  # COMPLEXITY_CAPS["simple"] == 2

    def test_planning_fallback_on_error(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator
    ):
        mock_llm.gen = Mock(side_effect=Exception("LLM down"))
        mock_llm.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

        agent = ResearchAgent(**agent_base_params)
        steps, complexity = agent._planning_phase("Anything")

        assert complexity == "simple"
        assert len(steps) == 1
        assert steps[0]["query"] == "Anything"


@pytest.mark.unit
class TestResearchAgentExtractText:

    def _make_agent(self, agent_base_params, mock_llm_creator, mock_llm_handler_creator):
        return ResearchAgent(**agent_base_params)

    def test_extract_from_string(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(agent_base_params, mock_llm_creator, mock_llm_handler_creator)
        assert agent._extract_text("hello") == "hello"

    def test_extract_from_openai_response(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(agent_base_params, mock_llm_creator, mock_llm_handler_creator)
        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message = Mock()
        response.choices[0].message.content = "OpenAI content"
        response.message = None
        response.content = None
        assert agent._extract_text(response) == "OpenAI content"

    def test_extract_from_anthropic_response(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(agent_base_params, mock_llm_creator, mock_llm_handler_creator)
        text_block = Mock()
        text_block.text = "Anthropic content"
        response = Mock()
        response.content = [text_block]
        response.message = None
        response.choices = None
        assert agent._extract_text(response) == "Anthropic content"

    def test_extract_from_none(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(agent_base_params, mock_llm_creator, mock_llm_handler_creator)
        assert agent._extract_text(None) == ""


@pytest.mark.unit
class TestResearchAgentParseJson:

    def _make_agent(self, agent_base_params, mock_llm_creator, mock_llm_handler_creator):
        return ResearchAgent(**agent_base_params)

    def test_parse_plan_direct_json(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(agent_base_params, mock_llm_creator, mock_llm_handler_creator)
        text = '{"steps": [{"query": "q1"}], "complexity": "simple"}'
        result = agent._parse_plan_json(text)
        assert isinstance(result, dict)
        assert len(result["steps"]) == 1

    def test_parse_plan_from_code_fence(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(agent_base_params, mock_llm_creator, mock_llm_handler_creator)
        text = 'Here is the plan:\n```json\n{"steps": [{"query": "q1"}]}\n```'
        result = agent._parse_plan_json(text)
        assert isinstance(result, dict)

    def test_parse_plan_invalid_returns_empty(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(agent_base_params, mock_llm_creator, mock_llm_handler_creator)
        result = agent._parse_plan_json("not json at all")
        assert result == []

    def test_parse_clarification_json(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(agent_base_params, mock_llm_creator, mock_llm_handler_creator)
        text = '{"needs_clarification": false, "reason": "clear"}'
        result = agent._parse_clarification_json(text)
        assert result["needs_clarification"] is False

    def test_parse_clarification_json_from_code_fence(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(agent_base_params, mock_llm_creator, mock_llm_handler_creator)
        text = '```json\n{"needs_clarification": true, "questions": ["q1"]}\n```'
        result = agent._parse_clarification_json(text)
        assert result["needs_clarification"] is True

    def test_parse_clarification_json_invalid(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(agent_base_params, mock_llm_creator, mock_llm_handler_creator)
        result = agent._parse_clarification_json("not json")
        assert result is None
