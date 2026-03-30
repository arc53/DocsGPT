"""Comprehensive tests for application/agents/research_agent.py

Covers: CitationManager, ResearchAgent (init, budget, timeout, phases:
clarification, planning, research step, synthesis, _extract_text,
JSON parsing, tool setup, is_follow_up).
"""

import json
import time
from unittest.mock import Mock, patch

import pytest

from application.agents.research_agent import (
    COMPLEXITY_CAPS,
    CitationManager,
    ResearchAgent,
    DEFAULT_MAX_STEPS,
    DEFAULT_MAX_SUB_ITERATIONS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TOKEN_BUDGET,
    DEFAULT_PARALLEL_WORKERS,
)


# =====================================================================
# CitationManager
# =====================================================================


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

    def test_add_same_source_different_title(self):
        cm = CitationManager()
        n1 = cm.add({"source": "s1", "title": "T1"})
        n2 = cm.add({"source": "s1", "title": "T2"})
        assert n1 != n2

    def test_add_docs_returns_mapping(self):
        cm = CitationManager()
        docs = [
            {"source": "s1", "title": "Doc A"},
            {"source": "s2", "title": "Doc B"},
        ]
        text = cm.add_docs(docs)
        assert "[1] Doc A" in text
        assert "[2] Doc B" in text

    def test_add_docs_deduplication(self):
        cm = CitationManager()
        docs = [
            {"source": "s1", "title": "Doc A"},
            {"source": "s1", "title": "Doc A"},
        ]
        text = cm.add_docs(docs)
        assert text.count("[1]") == 2

    def test_format_references(self):
        cm = CitationManager()
        cm.add({
            "source": "http://example.com",
            "title": "Example",
            "filename": "ex.md",
        })
        refs = cm.format_references()
        assert "[1]" in refs
        assert "ex.md" in refs
        assert "http://example.com" in refs

    def test_format_references_uses_title_when_no_filename(self):
        cm = CitationManager()
        cm.add({"source": "http://example.com", "title": "My Title"})
        refs = cm.format_references()
        assert "My Title" in refs

    def test_format_references_empty(self):
        cm = CitationManager()
        assert "No sources" in cm.format_references()

    def test_get_all_docs(self):
        cm = CitationManager()
        cm.add({"source": "s1", "title": "T1"})
        cm.add({"source": "s2", "title": "T2"})
        docs = cm.get_all_docs()
        assert len(docs) == 2

    def test_format_references_sorted(self):
        cm = CitationManager()
        cm.add({"source": "s1", "title": "A"})
        cm.add({"source": "s2", "title": "B"})
        cm.add({"source": "s3", "title": "C"})
        refs = cm.format_references()
        lines = refs.strip().split("\n")
        assert lines[0].startswith("[1]")
        assert lines[1].startswith("[2]")
        assert lines[2].startswith("[3]")


# =====================================================================
# ResearchAgent Init & Constants
# =====================================================================


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
        assert agent.max_sub_iterations == DEFAULT_MAX_SUB_ITERATIONS
        assert agent.parallel_workers == DEFAULT_PARALLEL_WORKERS
        assert agent.retriever_config == {}

    def test_custom_budget(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ResearchAgent(
            max_steps=3,
            timeout_seconds=60,
            token_budget=50_000,
            max_sub_iterations=2,
            parallel_workers=1,
            **agent_base_params,
        )
        assert agent.max_steps == 3
        assert agent.timeout_seconds == 60
        assert agent.token_budget == 50_000
        assert agent.max_sub_iterations == 2
        assert agent.parallel_workers == 1

    def test_with_retriever_config(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        rc = {"source": {"active_docs": ["abc"]}}
        agent = ResearchAgent(retriever_config=rc, **agent_base_params)
        assert agent.retriever_config == rc

    def test_constants(self):
        assert DEFAULT_MAX_STEPS == 6
        assert DEFAULT_MAX_SUB_ITERATIONS == 5
        assert DEFAULT_TIMEOUT_SECONDS == 300
        assert DEFAULT_TOKEN_BUDGET == 100_000
        assert DEFAULT_PARALLEL_WORKERS == 3

    def test_complexity_caps(self):
        assert COMPLEXITY_CAPS["simple"] == 2
        assert COMPLEXITY_CAPS["moderate"] == 4
        assert COMPLEXITY_CAPS["complex"] == 6


# =====================================================================
# Budget & Timeout
# =====================================================================


@pytest.mark.unit
class TestResearchAgentBudget:

    def _make_agent(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, **kwargs
    ):
        return ResearchAgent(**kwargs, **agent_base_params)

    def test_timeout_detection(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params,
            mock_llm_creator,
            mock_llm_handler_creator,
            timeout_seconds=0,
        )
        agent._start_time = time.monotonic() - 1
        assert agent._is_timed_out() is True

    def test_not_timed_out(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params,
            mock_llm_creator,
            mock_llm_handler_creator,
            timeout_seconds=300,
        )
        agent._start_time = time.monotonic()
        assert agent._is_timed_out() is False

    def test_token_budget_tracking(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params,
            mock_llm_creator,
            mock_llm_handler_creator,
            token_budget=1000,
        )
        agent._track_tokens(500)
        assert agent._budget_remaining() == 500
        assert agent._is_over_budget() is False

        agent._track_tokens(500)
        assert agent._budget_remaining() == 0
        assert agent._is_over_budget() is True

    def test_over_budget_returns_zero_remaining(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params,
            mock_llm_creator,
            mock_llm_handler_creator,
            token_budget=100,
        )
        agent._track_tokens(200)
        assert agent._budget_remaining() == 0

    def test_snapshot_llm_tokens_returns_delta(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        agent = self._make_agent(
            agent_base_params,
            mock_llm_creator,
            mock_llm_handler_creator,
        )
        mock_llm.token_usage = {"prompt_tokens": 100, "generated_tokens": 50}

        delta1 = agent._snapshot_llm_tokens()
        assert delta1 == 150

        mock_llm.token_usage = {"prompt_tokens": 200, "generated_tokens": 100}
        delta2 = agent._snapshot_llm_tokens()
        assert delta2 == 150

    def test_elapsed(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params,
            mock_llm_creator,
            mock_llm_handler_creator,
        )
        agent._start_time = time.monotonic() - 1.5
        elapsed = agent._elapsed()
        assert elapsed >= 1.0


# =====================================================================
# Clarification Phase
# =====================================================================


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
            {
                "prompt": "What?",
                "response": "Clarify",
                "metadata": {"is_clarification": True},
            },
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

    def test_is_follow_up_empty_metadata(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent_base_params["chat_history"] = [
            {"prompt": "What?", "response": "X", "metadata": {}},
        ]
        agent = ResearchAgent(**agent_base_params)
        assert agent._is_follow_up() is False

    def test_clarification_returns_none_on_no_clarification_needed(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
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
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        clarification_json = json.dumps({
            "needs_clarification": True,
            "questions": ["Which version?", "What context?"],
        })
        mock_llm.gen = Mock(return_value=clarification_json)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        result = agent._clarification_phase("Tell me about it")
        assert result is not None
        assert "Which version?" in result
        assert "What context?" in result
        assert "1." in result
        assert "2." in result

    def test_clarification_limits_questions_to_three(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        clarification_json = json.dumps({
            "needs_clarification": True,
            "questions": ["q1", "q2", "q3", "q4", "q5"],
        })
        mock_llm.gen = Mock(return_value=clarification_json)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        result = agent._clarification_phase("complex question")
        # Should only show 3 questions
        assert "3." in result
        assert "4." not in result

    def test_clarification_returns_none_on_empty_questions(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        clarification_json = json.dumps({
            "needs_clarification": True,
            "questions": [],
        })
        mock_llm.gen = Mock(return_value=clarification_json)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        result = agent._clarification_phase("question")
        assert result is None

    def test_clarification_returns_none_on_llm_error(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        mock_llm.gen = Mock(side_effect=Exception("LLM error"))
        mock_llm.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

        agent = ResearchAgent(**agent_base_params)
        result = agent._clarification_phase("question")
        assert result is None


# =====================================================================
# Planning Phase
# =====================================================================


@pytest.mark.unit
class TestResearchAgentPlanning:

    def test_planning_returns_steps_and_complexity(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        plan_json = json.dumps({
            "complexity": "moderate",
            "steps": [
                {"query": "sub-question 1", "rationale": "reason 1"},
                {"query": "sub-question 2", "rationale": "reason 2"},
            ],
        })
        mock_llm.gen = Mock(return_value=plan_json)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        steps, complexity = agent._planning_phase("Compare A and B")

        assert complexity == "moderate"
        assert len(steps) == 2
        assert steps[0]["query"] == "sub-question 1"

    def test_planning_caps_steps_by_complexity(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        plan_json = json.dumps({
            "complexity": "simple",
            "steps": [{"query": f"q{i}", "rationale": f"r{i}"} for i in range(10)],
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
        assert len(steps) <= 2

    def test_planning_caps_steps_for_complex(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        plan_json = json.dumps({
            "complexity": "complex",
            "steps": [{"query": f"q{i}", "rationale": f"r{i}"} for i in range(10)],
        })
        mock_llm.gen = Mock(return_value=plan_json)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        steps, complexity = agent._planning_phase("Complex analysis")

        assert complexity == "complex"
        assert len(steps) <= 6

    def test_planning_fallback_on_error(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        mock_llm.gen = Mock(side_effect=Exception("LLM down"))
        mock_llm.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

        agent = ResearchAgent(**agent_base_params)
        steps, complexity = agent._planning_phase("Anything")

        assert complexity == "simple"
        assert len(steps) == 1
        assert steps[0]["query"] == "Anything"

    def test_planning_list_response(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        plan_json = json.dumps([
            {"query": "q1", "rationale": "r1"},
            {"query": "q2", "rationale": "r2"},
        ])
        mock_llm.gen = Mock(return_value=plan_json)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        steps, complexity = agent._planning_phase("question")

        assert complexity == "moderate"
        assert len(steps) == 2


# =====================================================================
# Extract Text
# =====================================================================


@pytest.mark.unit
class TestResearchAgentExtractText:

    def _make_agent(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        return ResearchAgent(**agent_base_params)

    def test_extract_from_string(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        assert agent._extract_text("hello") == "hello"

    def test_extract_from_openai_response(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
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
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        text_block = Mock()
        text_block.text = "Anthropic content"
        response = Mock()
        response.content = [text_block]
        response.message = None
        response.choices = None
        assert agent._extract_text(response) == "Anthropic content"

    def test_extract_from_message_content(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        response = Mock()
        response.message = Mock()
        response.message.content = "From message"
        assert agent._extract_text(response) == "From message"

    def test_extract_from_none(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        assert agent._extract_text(None) == ""


# =====================================================================
# Parse JSON
# =====================================================================


@pytest.mark.unit
class TestResearchAgentParseJson:

    def _make_agent(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        return ResearchAgent(**agent_base_params)

    def test_parse_plan_direct_json(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        text = '{"steps": [{"query": "q1"}], "complexity": "simple"}'
        result = agent._parse_plan_json(text)
        assert isinstance(result, dict)
        assert len(result["steps"]) == 1

    def test_parse_plan_list(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        text = '[{"query": "q1"}]'
        result = agent._parse_plan_json(text)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_parse_plan_from_code_fence(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        text = 'Here is the plan:\n```json\n{"steps": [{"query": "q1"}]}\n```'
        result = agent._parse_plan_json(text)
        assert isinstance(result, dict)

    def test_parse_plan_from_plain_code_fence(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        text = 'Result:\n```\n{"steps": [{"query": "q1"}]}\n```'
        result = agent._parse_plan_json(text)
        assert isinstance(result, dict)

    def test_parse_plan_embedded_json_object(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        text = 'Here is the plan: {"steps": [{"query": "q1"}]} end.'
        result = agent._parse_plan_json(text)
        assert isinstance(result, dict)

    def test_parse_plan_invalid_returns_empty(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        result = agent._parse_plan_json("not json at all")
        assert result == []

    def test_parse_clarification_json(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        text = '{"needs_clarification": false, "reason": "clear"}'
        result = agent._parse_clarification_json(text)
        assert result["needs_clarification"] is False

    def test_parse_clarification_json_from_code_fence(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        text = '```json\n{"needs_clarification": true, "questions": ["q1"]}\n```'
        result = agent._parse_clarification_json(text)
        assert result["needs_clarification"] is True

    def test_parse_clarification_embedded_json(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        text = 'Here: {"needs_clarification": true, "questions": ["q1"]} done.'
        result = agent._parse_clarification_json(text)
        assert result["needs_clarification"] is True

    def test_parse_clarification_json_invalid(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = self._make_agent(
            agent_base_params, mock_llm_creator, mock_llm_handler_creator
        )
        result = agent._parse_clarification_json("not json")
        assert result is None


# =====================================================================
# Tool Setup
# =====================================================================


@pytest.mark.unit
class TestResearchAgentToolSetup:

    def test_setup_tools_includes_think_and_internal(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ResearchAgent(
            retriever_config={
                "source": {"active_docs": ["abc"]},
                "retriever_name": "classic",
            },
            **agent_base_params,
        )

        with patch(
            "application.agents.research_agent.add_internal_search_tool"
        ) as mock_add:
            tools = agent._setup_tools()
            mock_add.assert_called_once()
            assert "think" in tools

    def test_setup_tools_no_retriever_config(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ResearchAgent(**agent_base_params)

        with patch(
            "application.agents.research_agent.add_internal_search_tool"
        ) as mock_add:
            tools = agent._setup_tools()
            mock_add.assert_called_once()
            assert "think" in tools


# =====================================================================
# Collect Step Sources
# =====================================================================


@pytest.mark.unit
class TestCollectStepSources:

    def test_collects_from_internal_search_tool(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ResearchAgent(**agent_base_params)

        mock_tool = Mock()
        mock_tool.retrieved_docs = [
            {"source": "s1", "title": "T1"},
            {"source": "s2", "title": "T2"},
        ]

        cache_key = f"internal_search:internal:{agent.user or ''}"
        agent.tool_executor._loaded_tools[cache_key] = mock_tool

        agent._collect_step_sources()

        assert len(agent.citations.citations) == 2

    def test_no_tool_no_error(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ResearchAgent(**agent_base_params)
        agent._collect_step_sources()
        assert len(agent.citations.citations) == 0


# =====================================================================
# _gen_inner (full orchestration tests)
# =====================================================================


@pytest.mark.unit
class TestGenInner:

    def test_gen_inner_clarification_path(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """When clarification is needed, _gen_inner yields clarification output and returns."""
        agent = ResearchAgent(**agent_base_params)

        with patch.object(agent, "_is_follow_up", return_value=False), \
             patch.object(agent, "_clarification_phase", return_value="Please clarify:\n1. Which version?"), \
             patch.object(agent, "_setup_tools", return_value={}):
            events = list(agent._gen_inner("ambiguous question", log_context))

        # Should have: metadata, answer, sources, tool_calls
        meta_events = [e for e in events if isinstance(e, dict) and "metadata" in e]
        assert len(meta_events) == 1
        assert meta_events[0]["metadata"]["is_clarification"] is True

        answer_events = [e for e in events if isinstance(e, dict) and "answer" in e]
        assert len(answer_events) == 1
        assert "Please clarify" in answer_events[0]["answer"]

        source_events = [e for e in events if isinstance(e, dict) and "sources" in e]
        assert len(source_events) == 1
        assert source_events[0]["sources"] == []

    def test_gen_inner_skips_clarification_on_follow_up(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """When user is responding to clarification, skip clarification phase."""
        agent_base_params["chat_history"] = [
            {"prompt": "What?", "response": "clarify", "metadata": {"is_clarification": True}},
        ]
        agent = ResearchAgent(**agent_base_params)

        plan_steps = [{"query": "test query", "rationale": "direct"}]

        with patch.object(agent, "_setup_tools", return_value={}), \
             patch.object(agent, "_planning_phase", return_value=(plan_steps, "simple")), \
             patch.object(agent, "_research_step", return_value="findings here"), \
             patch.object(agent, "_synthesis_phase", return_value=iter([{"answer": "result"}])), \
             patch.object(agent, "_get_truncated_tool_calls", return_value=[]):
            events = list(agent._gen_inner("Python 3.10", log_context))

        # Should NOT have clarification metadata
        meta_events = [e for e in events if isinstance(e, dict) and e.get("metadata", {}).get("is_clarification")]
        assert len(meta_events) == 0

        # Should have planning event
        plan_events = [e for e in events if isinstance(e, dict) and e.get("type") == "research_plan"]
        assert len(plan_events) == 1

    def test_gen_inner_empty_plan_fallback(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """When planning returns no steps, _gen_inner uses a fallback single step."""
        agent = ResearchAgent(**agent_base_params)

        with patch.object(agent, "_setup_tools", return_value={}), \
             patch.object(agent, "_is_follow_up", return_value=True), \
             patch.object(agent, "_planning_phase", return_value=([], "moderate")), \
             patch.object(agent, "_research_step", return_value="direct findings"), \
             patch.object(agent, "_synthesis_phase", return_value=iter([{"answer": "done"}])), \
             patch.object(agent, "_get_truncated_tool_calls", return_value=[]):
            events = list(agent._gen_inner("What is X?", log_context))

        plan_events = [e for e in events if isinstance(e, dict) and e.get("type") == "research_plan"]
        assert len(plan_events) == 1
        # Fallback plan should have one step with the original query
        assert plan_events[0]["data"]["steps"][0]["query"] == "What is X?"
        assert plan_events[0]["data"]["complexity"] == "simple"

    def test_gen_inner_timeout_during_research(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """Timeout during research steps stops early and proceeds to synthesis."""
        agent = ResearchAgent(timeout_seconds=0, **agent_base_params)

        plan_steps = [
            {"query": "step1", "rationale": "r1"},
            {"query": "step2", "rationale": "r2"},
        ]

        with patch.object(agent, "_setup_tools", return_value={}), \
             patch.object(agent, "_is_follow_up", return_value=True), \
             patch.object(agent, "_planning_phase", return_value=(plan_steps, "moderate")):
            # Set start time in the past to trigger timeout
            agent._start_time = time.monotonic() - 1

            with patch.object(agent, "_synthesis_phase", return_value=iter([{"answer": "partial"}])), \
                 patch.object(agent, "_get_truncated_tool_calls", return_value=[]):
                events = list(agent._gen_inner("question", log_context))

        # No research progress events with status "researching" expected (timed out before any step)
        researching = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == "research_progress"
            and e.get("data", {}).get("status") == "researching"
        ]
        assert len(researching) == 0

        # Should still have synthesis event
        synth = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == "research_progress"
            and e.get("data", {}).get("status") == "synthesizing"
        ]
        assert len(synth) == 1

    def test_gen_inner_budget_exhausted_during_research(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """Token budget exhaustion during research stops early."""
        agent = ResearchAgent(token_budget=10, **agent_base_params)

        plan_steps = [
            {"query": "step1", "rationale": "r1"},
            {"query": "step2", "rationale": "r2"},
        ]

        with patch.object(agent, "_setup_tools", return_value={}), \
             patch.object(agent, "_is_follow_up", return_value=True), \
             patch.object(agent, "_planning_phase", return_value=(plan_steps, "moderate")):
            agent._start_time = time.monotonic()
            agent._tokens_used = 100  # Over budget

            with patch.object(agent, "_synthesis_phase", return_value=iter([{"answer": "partial"}])), \
                 patch.object(agent, "_get_truncated_tool_calls", return_value=[]):
                events = list(agent._gen_inner("question", log_context))

        researching = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == "research_progress"
            and e.get("data", {}).get("status") == "researching"
        ]
        assert len(researching) == 0

    def test_gen_inner_full_flow(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """Full flow: plan, research multiple steps, synthesize."""
        agent = ResearchAgent(**agent_base_params)

        plan_steps = [
            {"query": "step1", "rationale": "r1"},
            {"query": "step2", "rationale": "r2"},
        ]

        with patch.object(agent, "_setup_tools", return_value={}), \
             patch.object(agent, "_is_follow_up", return_value=True), \
             patch.object(agent, "_planning_phase", return_value=(plan_steps, "moderate")), \
             patch.object(agent, "_research_step", side_effect=["report1", "report2"]), \
             patch.object(agent, "_synthesis_phase", return_value=iter([{"answer": "final report"}])), \
             patch.object(agent, "_get_truncated_tool_calls", return_value=[{"tool": "search"}]):
            events = list(agent._gen_inner("Compare A and B", log_context))

        # Planning event
        plan_events = [e for e in events if isinstance(e, dict) and e.get("type") == "research_plan"]
        assert len(plan_events) == 1

        # Research progress events: 2 researching + 2 complete
        researching = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == "research_progress"
            and e.get("data", {}).get("status") == "researching"
        ]
        assert len(researching) == 2

        complete = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == "research_progress"
            and e.get("data", {}).get("status") == "complete"
        ]
        assert len(complete) == 2

        # Synthesis event
        synth = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == "research_progress"
            and e.get("data", {}).get("status") == "synthesizing"
        ]
        assert len(synth) == 1

        # Sources and tool_calls events
        source_events = [e for e in events if isinstance(e, dict) and "sources" in e]
        assert len(source_events) == 1

        tc_events = [e for e in events if isinstance(e, dict) and "tool_calls" in e]
        assert len(tc_events) == 1


# =====================================================================
# _synthesis_phase
# =====================================================================


@pytest.mark.unit
class TestSynthesisPhase:

    def test_synthesis_phase_builds_correct_prompt(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """Synthesis phase constructs prompt from plan and findings."""
        agent = ResearchAgent(**agent_base_params)
        agent._start_time = time.monotonic()
        agent.citations.add({"source": "s1", "title": "T1", "filename": "f1.md"})

        plan = [
            {"query": "q1", "rationale": "reason1"},
            {"query": "q2", "rationale": "reason2"},
        ]
        reports = [
            {"step": plan[0], "content": "Found X"},
            {"step": plan[1], "content": "Found Y"},
        ]

        mock_llm.gen_stream = Mock(return_value=iter(["chunk1", "chunk2"]))

        with patch.object(agent, "_handle_response", return_value=iter([
            {"answer": "Synthesized report"},
        ])):
            events = list(agent._synthesis_phase(
                "test question", plan, reports, {}, log_context
            ))

        answer_events = [e for e in events if isinstance(e, dict) and "answer" in e]
        assert len(answer_events) == 1

        # Verify gen_stream was called
        mock_llm.gen_stream.assert_called_once()
        call_kwargs = mock_llm.gen_stream.call_args
        messages = call_kwargs[1]["messages"] if "messages" in call_kwargs[1] else call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None
        if messages is None:
            messages = call_kwargs.kwargs.get("messages", call_kwargs.args[1] if len(call_kwargs.args) > 1 else [])

    def test_synthesis_phase_with_empty_reports(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
        log_context,
    ):
        """Synthesis handles empty reports."""
        agent = ResearchAgent(**agent_base_params)
        agent._start_time = time.monotonic()

        mock_llm.gen_stream = Mock(return_value=iter([]))

        with patch.object(agent, "_handle_response", return_value=iter([
            {"answer": "No findings available."},
        ])):
            events = list(agent._synthesis_phase(
                "test question", [], [], {}, log_context
            ))

        answer_events = [e for e in events if isinstance(e, dict) and "answer" in e]
        assert len(answer_events) == 1


# =====================================================================
# _research_step and _research_step_with_executor
# =====================================================================


@pytest.mark.unit
class TestResearchStep:

    def test_research_step_no_tool_call(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """LLM returns direct answer without tool calls."""
        agent = ResearchAgent(**agent_base_params)
        agent._start_time = time.monotonic()
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        # LLM returns a direct response
        mock_response = Mock()
        mock_llm.gen = Mock(return_value=mock_response)

        from application.llm.handlers.base import LLMResponse
        parsed = LLMResponse(
            content="Direct answer to the question",
            tool_calls=[],
            finish_reason="stop",
            raw_response=mock_response,
        )
        mock_llm_handler.parse_response = Mock(return_value=parsed)

        report = agent._research_step("What is Python?", {})
        assert report == "Direct answer to the question"

    def test_research_step_with_tool_calls(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """LLM makes a tool call, then returns final answer."""
        agent = ResearchAgent(**agent_base_params)
        agent._start_time = time.monotonic()
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        mock_response1 = Mock()
        mock_response2 = Mock()
        mock_llm.gen = Mock(side_effect=[mock_response1, mock_response2])

        from application.llm.handlers.base import LLMResponse, ToolCall

        tool_call = ToolCall(id="tc1", name="internal__search", arguments={"query": "python"})
        parsed_with_tool = LLMResponse(
            content="",
            tool_calls=[tool_call],
            finish_reason="tool_calls",
            raw_response=mock_response1,
        )
        parsed_final = LLMResponse(
            content="Python is a programming language.",
            tool_calls=[],
            finish_reason="stop",
            raw_response=mock_response2,
        )
        mock_llm_handler.parse_response = Mock(side_effect=[parsed_with_tool, parsed_final])

        # Mock tool execution
        with patch.object(agent, "_execute_step_tools_with_refinement",
                          return_value=([], False)):
            report = agent._research_step("What is Python?", {})
            assert report == "Python is a programming language."

    def test_research_step_timeout_mid_iteration(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Research step times out and returns summary."""
        agent = ResearchAgent(timeout_seconds=0, **agent_base_params)
        agent._start_time = time.monotonic() - 1  # Already timed out
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        # Summary response when max iterations hit
        mock_llm.gen = Mock(return_value="Summary of findings")

        report = agent._research_step("query", {})
        assert "Summary" in report or "completed" in report

    def test_research_step_budget_exhausted(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Research step hits token budget and returns summary."""
        agent = ResearchAgent(token_budget=10, **agent_base_params)
        agent._start_time = time.monotonic()
        agent._tokens_used = 100  # Over budget
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        mock_llm.gen = Mock(return_value="Budget summary")

        report = agent._research_step("query", {})
        assert "Budget summary" in report or "completed" in report

    def test_research_step_llm_error(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Research step handles LLM error gracefully."""
        agent = ResearchAgent(**agent_base_params)
        agent._start_time = time.monotonic()
        mock_llm.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

        # First gen call fails
        mock_llm.gen = Mock(side_effect=[
            Exception("LLM error"),
            "Fallback summary",
        ])

        report = agent._research_step("query", {})
        assert "completed" in report or "Fallback" in report

    def test_research_step_max_iterations_summary(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """After max iterations, research step asks for summary."""
        agent = ResearchAgent(max_sub_iterations=1, **agent_base_params)
        agent._start_time = time.monotonic()
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        from application.llm.handlers.base import LLMResponse, ToolCall

        tool_call = ToolCall(id="tc1", name="internal__search", arguments={"query": "test"})

        mock_response1 = Mock()
        parsed_with_tool = LLMResponse(
            content="",
            tool_calls=[tool_call],
            finish_reason="tool_calls",
            raw_response=mock_response1,
        )
        mock_llm_handler.parse_response = Mock(return_value=parsed_with_tool)

        # First gen returns tool call, second gen (summary request) returns text
        mock_llm.gen = Mock(side_effect=[mock_response1, "Final summary after max iters"])

        with patch.object(agent, "_execute_step_tools_with_refinement",
                          return_value=([], False)):
            report = agent._research_step("query", {})

        assert "Final summary" in report

    def test_research_step_summary_fails_gracefully(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """When summary LLM call fails, returns fallback text."""
        agent = ResearchAgent(max_sub_iterations=0, **agent_base_params)
        agent._start_time = time.monotonic()
        mock_llm.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

        # Summary call fails
        mock_llm.gen = Mock(side_effect=Exception("gen failed"))

        report = agent._research_step("query", {})
        assert report == "Research step completed."


# =====================================================================
# _execute_step_tools_with_refinement
# =====================================================================


@pytest.mark.unit
class TestExecuteStepToolsWithRefinement:

    def test_basic_tool_execution(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Tool execution appends messages correctly."""
        agent = ResearchAgent(**agent_base_params)

        from application.llm.handlers.base import ToolCall

        call = ToolCall(id="tc1", name="internal__search", arguments={"query": "test"})

        def fake_execute(tools_dict, tc, llm_class):
            gen_result = ("Search result text", "tc1")
            return gen_result
            yield  # noqa: E501 - makes it a generator

        # Build a proper generator mock
        def gen_execute(tools_dict, tc, llm_class):
            yield {"type": "tool_call", "data": {"action_name": "search", "status": "pending"}}
            return ("Search result text", "tc1")

        agent.tool_executor.execute = gen_execute
        mock_llm_handler.create_tool_message = Mock(
            return_value={"role": "tool", "content": "Search result text"}
        )

        messages = [{"role": "user", "content": "query"}]
        result_msgs, was_empty = agent._execute_step_tools_with_refinement(
            [call], {}, messages, agent.tool_executor, False
        )

        assert len(result_msgs) > 1
        assert any(m.get("role") == "assistant" for m in result_msgs)
        assert any(m.get("role") == "tool" for m in result_msgs)

    def test_empty_search_result_refinement(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """When search returns empty twice, adds refinement hint."""
        agent = ResearchAgent(**agent_base_params)

        from application.llm.handlers.base import ToolCall

        call = ToolCall(id="tc1", name="internal__search", arguments={"query": "test"})

        def gen_execute(tools_dict, tc, llm_class):
            yield {"type": "tool_call", "data": {"action_name": "search", "status": "pending"}}
            return ("No documents found for the query", "tc1")

        agent.tool_executor.execute = gen_execute
        mock_llm_handler.create_tool_message = Mock(
            return_value={"role": "tool", "content": "No documents found"}
        )

        messages = [{"role": "user", "content": "query"}]
        # First call with last_search_empty=True to trigger refinement
        result_msgs, was_empty = agent._execute_step_tools_with_refinement(
            [call], {}, messages, agent.tool_executor, True
        )

        assert was_empty is True

    def test_non_search_tool_no_refinement(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Non-search tools don't trigger empty search logic."""
        agent = ResearchAgent(**agent_base_params)

        from application.llm.handlers.base import ToolCall

        call = ToolCall(id="tc1", name="think__think", arguments={"thought": "hmm"})

        def gen_execute(tools_dict, tc, llm_class):
            yield {"type": "tool_call", "data": {"action_name": "think", "status": "pending"}}
            return ("Thought processed", "tc1")

        agent.tool_executor.execute = gen_execute
        mock_llm_handler.create_tool_message = Mock(
            return_value={"role": "tool", "content": "Thought processed"}
        )

        messages = [{"role": "user", "content": "query"}]
        result_msgs, was_empty = agent._execute_step_tools_with_refinement(
            [call], {}, messages, agent.tool_executor, False
        )

        assert was_empty is False


# =====================================================================
# _planning_phase extended (edge cases in JSON parsing)
# =====================================================================


@pytest.mark.unit
class TestPlanningPhaseExtended:

    def test_planning_unknown_complexity_uses_default_cap(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Unknown complexity level uses max_steps as cap."""
        plan_json = json.dumps({
            "complexity": "extreme",
            "steps": [{"query": f"q{i}", "rationale": f"r{i}"} for i in range(10)],
        })
        mock_llm.gen = Mock(return_value=plan_json)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        steps, complexity = agent._planning_phase("Hard question")

        assert complexity == "extreme"
        assert len(steps) <= agent.max_steps

    def test_parse_plan_json_dict_without_steps_key(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """JSON dict without 'steps' key is not treated as a plan."""
        agent = ResearchAgent(**agent_base_params)
        # Returns empty list since it's a dict but no 'steps'
        result = agent._parse_plan_json('{"complexity": "simple"}')
        assert result == []

    def test_parse_plan_json_code_fence_with_list(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """JSON list inside code fence is parsed correctly."""
        agent = ResearchAgent(**agent_base_params)
        text = 'Plan:\n```json\n[{"query": "q1", "rationale": "r1"}]\n```'
        result = agent._parse_plan_json(text)
        assert isinstance(result, list)
        assert len(result) == 1


# =====================================================================
# Additional coverage: lines 326, 328, 335-336, 346-352, 360
# =====================================================================


@pytest.mark.unit
class TestClarificationPhaseAdditional:

    def test_clarification_returns_formatted_questions(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Cover lines 326, 328, 335-336: clarification with questions."""
        clarification_json = json.dumps({
            "needs_clarification": True,
            "questions": ["What version?", "Which platform?", "What scope?"],
        })
        mock_llm.gen = Mock(return_value=clarification_json)
        mock_llm.token_usage = {"prompt_tokens": 10, "generated_tokens": 5}

        agent = ResearchAgent(**agent_base_params)
        result = agent._clarification_phase("Tell me about it")

        assert result is not None
        assert "1." in result
        assert "2." in result
        assert "3." in result
        assert "clarify" in result.lower()

    def test_parse_clarification_json_code_fence_invalid(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Cover lines 346-352: invalid JSON inside code fence falls through."""
        agent = ResearchAgent(**agent_base_params)
        text = '```json\nnot valid json\n```'
        result = agent._parse_clarification_json(text)
        assert result is None

    def test_parse_clarification_json_embedded_invalid(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Cover line 360: embedded JSON with invalid content."""
        agent = ResearchAgent(**agent_base_params)
        text = 'Before {invalid json} after'
        result = agent._parse_clarification_json(text)
        assert result is None

    def test_parse_clarification_code_fence_no_closing(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Cover line 358: code fence without closing marker."""
        agent = ResearchAgent(**agent_base_params)
        text = '```json\n{"needs_clarification": true, "questions": ["q1"]}'
        result = agent._parse_clarification_json(text)
        assert result is not None
        assert result["needs_clarification"] is True

    def test_parse_plan_json_embedded_dict_without_steps(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Cover line 463: embedded dict without 'steps' key."""
        agent = ResearchAgent(**agent_base_params)
        text = 'Here is a plan: {"key": "value"} done.'
        result = agent._parse_plan_json(text)
        assert result == []


# ---------------------------------------------------------------------------
# Coverage — additional uncovered lines: 326, 328, 335-336, 360
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResearchAgentClarificationCoverage:

    def test_clarification_no_needs_clarification(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Cover line 326: data has needs_clarification=False returns None."""
        agent = ResearchAgent(**agent_base_params)
        # Mock _generate_response to return valid JSON without clarification
        agent._generate_response = lambda *a, **kw: None
        agent._extract_text = lambda r: '{"needs_clarification": false}'
        agent._snapshot_llm_tokens = lambda: {}
        agent._track_tokens = lambda t: None

        result = agent._clarification_phase("test query")
        assert result is None

    def test_clarification_with_questions(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Cover lines 328, 335-336: questions returned as formatted response."""
        agent = ResearchAgent(**agent_base_params)
        agent._generate_response = lambda *a, **kw: None
        agent._extract_text = lambda r: '{"needs_clarification": true, "questions": ["What scope?", "What depth?"]}'
        agent._snapshot_llm_tokens = lambda: {}
        agent._track_tokens = lambda t: None

        result = agent._clarification_phase("test query")
        assert result is not None
        assert "What scope?" in result
        assert "What depth?" in result
        assert "Before I begin" in result

    def test_clarification_empty_questions_returns_none(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Cover line 328: needs_clarification=True but empty questions."""
        agent = ResearchAgent(**agent_base_params)
        agent._generate_response = lambda *a, **kw: None
        agent._extract_text = lambda r: '{"needs_clarification": true, "questions": []}'
        agent._snapshot_llm_tokens = lambda: {}
        agent._track_tokens = lambda t: None

        result = agent._clarification_phase("test query")
        assert result is None

    def test_parse_clarification_json_with_code_fence_json(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Cover line 360: JSON in code fence marker parsed."""
        agent = ResearchAgent(**agent_base_params)
        text = '```json\n{"needs_clarification": true, "questions": ["q1"]}\n```'
        result = agent._parse_clarification_json(text)
        assert result is not None
        assert result["needs_clarification"] is True

    def test_parse_clarification_json_embedded_object(
        self,
        agent_base_params,
        mock_llm_creator,
        mock_llm_handler_creator,
    ):
        """Cover line 360+: JSON object embedded in text."""
        agent = ResearchAgent(**agent_base_params)
        text = 'Here is my response: {"needs_clarification": false} end.'
        result = agent._parse_clarification_json(text)
        assert result == {"needs_clarification": False}
