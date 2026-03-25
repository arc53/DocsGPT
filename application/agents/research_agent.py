import json
import logging
import os
import time
from typing import Dict, Generator, List, Optional

from application.agents.base import BaseAgent
from application.agents.tool_executor import ToolExecutor
from application.agents.tools.internal_search import (
    INTERNAL_TOOL_ENTRY,
    INTERNAL_TOOL_ID,
    build_internal_tool_config,
)
from application.agents.tools.think import THINK_TOOL_ENTRY, THINK_TOOL_ID
from application.logging import LogContext

logger = logging.getLogger(__name__)

# Defaults (can be overridden via constructor)
DEFAULT_MAX_STEPS = 6
DEFAULT_MAX_SUB_ITERATIONS = 5
DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes
DEFAULT_TOKEN_BUDGET = 100_000
DEFAULT_PARALLEL_WORKERS = 3

# Adaptive depth caps per complexity level
COMPLEXITY_CAPS = {
    "simple": 2,
    "moderate": 4,
    "complex": 6,
}

_PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts",
    "research",
)


def _load_prompt(name: str) -> str:
    with open(os.path.join(_PROMPTS_DIR, name), "r") as f:
        return f.read()


CLARIFICATION_PROMPT = _load_prompt("clarification.txt")
PLANNING_PROMPT = _load_prompt("planning.txt")
STEP_PROMPT = _load_prompt("step.txt")
SYNTHESIS_PROMPT = _load_prompt("synthesis.txt")


# ---------------------------------------------------------------------------
# CitationManager
# ---------------------------------------------------------------------------


class CitationManager:
    """Tracks and deduplicates citations across research steps."""

    def __init__(self):
        self.citations: Dict[int, Dict] = {}
        self._counter = 0

    def add(self, doc: Dict) -> int:
        """Register a source, return its citation number. Deduplicates by source."""
        source = doc.get("source", "")
        title = doc.get("title", "")
        for num, existing in self.citations.items():
            if existing.get("source") == source and existing.get("title") == title:
                return num
        self._counter += 1
        self.citations[self._counter] = doc
        return self._counter

    def add_docs(self, docs: List[Dict]) -> str:
        """Register multiple docs, return formatted citation mapping text."""
        mapping_lines = []
        for doc in docs:
            num = self.add(doc)
            title = doc.get("title", "Untitled")
            mapping_lines.append(f"[{num}] {title}")
        return "\n".join(mapping_lines)

    def format_references(self) -> str:
        """Generate [N] -> source mapping for report footer."""
        if not self.citations:
            return "No sources found."
        lines = []
        for num, doc in sorted(self.citations.items()):
            title = doc.get("title", "Untitled")
            source = doc.get("source", "Unknown")
            filename = doc.get("filename", "")
            display = filename or title
            lines.append(f"[{num}] {display} — {source}")
        return "\n".join(lines)

    def get_all_docs(self) -> List[Dict]:
        return list(self.citations.values())


# ---------------------------------------------------------------------------
# ResearchAgent
# ---------------------------------------------------------------------------


class ResearchAgent(BaseAgent):
    """Multi-step research agent with parallel execution and budget controls.

    Orchestrates: Plan -> Research (per step, optionally parallel) -> Synthesize.
    """

    def __init__(
        self,
        retriever_config: Optional[Dict] = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_sub_iterations: int = DEFAULT_MAX_SUB_ITERATIONS,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        parallel_workers: int = DEFAULT_PARALLEL_WORKERS,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.retriever_config = retriever_config or {}
        self.max_steps = max_steps
        self.max_sub_iterations = max_sub_iterations
        self.timeout_seconds = timeout_seconds
        self.token_budget = token_budget
        self.parallel_workers = parallel_workers
        self.citations = CitationManager()
        self._start_time: float = 0
        self._tokens_used: int = 0

    # ------------------------------------------------------------------
    # Budget & timeout helpers
    # ------------------------------------------------------------------

    def _is_timed_out(self) -> bool:
        return (time.monotonic() - self._start_time) >= self.timeout_seconds

    def _elapsed(self) -> float:
        return round(time.monotonic() - self._start_time, 1)

    def _track_tokens(self, count: int):
        self._tokens_used += count

    def _budget_remaining(self) -> int:
        return max(self.token_budget - self._tokens_used, 0)

    def _is_over_budget(self) -> bool:
        return self._tokens_used >= self.token_budget

    def _snapshot_llm_tokens(self) -> int:
        """Read current token usage from LLM and return delta since last snapshot."""
        current = self.llm.token_usage.get("prompt_tokens", 0) + self.llm.token_usage.get("generated_tokens", 0)
        return current

    # ------------------------------------------------------------------
    # Main orchestration
    # ------------------------------------------------------------------

    def _gen_inner(
        self, query: str, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        self._start_time = time.monotonic()
        tools_dict = self._setup_tools()

        # Phase 0: Clarification (skip if user is responding to a prior clarification)
        if not self._is_follow_up():
            clarification = self._clarification_phase(query)
            if clarification:
                yield {"metadata": {"is_clarification": True}}
                yield {"answer": clarification}
                yield {"sources": []}
                yield {"tool_calls": []}
                log_context.stacks.append(
                    {"component": "agent", "data": {"clarification": True}}
                )
                return

        # Phase 1: Planning (with adaptive depth)
        yield {"type": "research_progress", "data": {"status": "planning"}}
        plan, complexity = self._planning_phase(query)

        if not plan:
            logger.warning("ResearchAgent: Planning produced no steps, falling back")
            plan = [{"query": query, "rationale": "Direct investigation"}]
            complexity = "simple"

        yield {
            "type": "research_plan",
            "data": {"steps": plan, "complexity": complexity},
        }

        # Phase 2: Research each step (yields progress events in real-time)
        intermediate_reports = []
        for i, step in enumerate(plan):
            step_num = i + 1
            step_query = step.get("query", query)

            if self._is_timed_out():
                logger.warning(
                    f"ResearchAgent: Timeout at step {step_num}/{len(plan)} "
                    f"({self._elapsed()}s)"
                )
                break
            if self._is_over_budget():
                logger.warning(
                    f"ResearchAgent: Token budget exhausted at step {step_num}/{len(plan)}"
                )
                break

            yield {
                "type": "research_progress",
                "data": {
                    "step": step_num,
                    "total": len(plan),
                    "query": step_query,
                    "status": "researching",
                },
            }

            report = self._research_step(step_query, tools_dict)
            intermediate_reports.append({"step": step, "content": report})

            yield {
                "type": "research_progress",
                "data": {
                    "step": step_num,
                    "total": len(plan),
                    "query": step_query,
                    "status": "complete",
                },
            }

        # Phase 3: Synthesis (streaming)
        if self._is_timed_out():
            logger.warning(
                f"ResearchAgent: Timeout ({self._elapsed()}s) before synthesis, "
                f"synthesizing with {len(intermediate_reports)} reports"
            )
        yield {
            "type": "research_progress",
            "data": {
                "status": "synthesizing",
                "elapsed_seconds": self._elapsed(),
                "tokens_used": self._tokens_used,
            },
        }
        yield from self._synthesis_phase(
            query, plan, intermediate_reports, tools_dict, log_context
        )

        # Sources and tool calls
        self.retrieved_docs = self.citations.get_all_docs()
        yield {"sources": self.retrieved_docs}
        yield {"tool_calls": self._get_truncated_tool_calls()}

        logger.info(
            f"ResearchAgent completed: {len(intermediate_reports)}/{len(plan)} steps, "
            f"{self._elapsed()}s, ~{self._tokens_used} tokens"
        )
        log_context.stacks.append(
            {"component": "agent", "data": {"tool_calls": self.tool_calls.copy()}}
        )

    # ------------------------------------------------------------------
    # Tool setup
    # ------------------------------------------------------------------

    def _setup_tools(self) -> Dict:
        """Build tools_dict with user tools + internal search + think."""
        tools_dict = self.tool_executor.get_tools()

        # Only add internal search if sources are configured
        source = self.retriever_config.get("source", {})
        has_sources = bool(source.get("active_docs"))
        if self.retriever_config and has_sources:
            internal_entry = dict(INTERNAL_TOOL_ENTRY)
            internal_entry["config"] = build_internal_tool_config(
                **self.retriever_config
            )
            tools_dict[INTERNAL_TOOL_ID] = internal_entry
        elif self.retriever_config and not has_sources:
            logger.info("ResearchAgent: No sources configured, skipping internal_search tool")

        think_entry = dict(THINK_TOOL_ENTRY)
        think_entry["config"] = {}
        tools_dict[THINK_TOOL_ID] = think_entry

        self._prepare_tools(tools_dict)
        return tools_dict

    # ------------------------------------------------------------------
    # Phase 0: Clarification
    # ------------------------------------------------------------------

    def _is_follow_up(self) -> bool:
        """Check if the user is responding to a prior clarification.

        Uses the metadata flag stored in the conversation DB — no string matching.
        Only skip clarification when the last query was explicitly flagged
        as a clarification by this agent.
        """
        if not self.chat_history:
            return False
        last = self.chat_history[-1]
        meta = last.get("metadata", {})
        return bool(meta.get("is_clarification"))

    def _clarification_phase(self, question: str) -> Optional[str]:
        """Ask the LLM whether the question needs clarification.

        Returns formatted clarification text if needed, or None to proceed.
        Uses response_format to force valid JSON output.
        """
        messages = [
            {"role": "system", "content": CLARIFICATION_PROMPT},
            {"role": "user", "content": question},
        ]

        try:
            response = self.llm.gen(
                model=self.model_id,
                messages=messages,
                tools=None,
                response_format={"type": "json_object"},
            )
            text = self._extract_text(response)
            self._track_tokens(self._snapshot_llm_tokens())
            logger.info(f"ResearchAgent clarification response: {text[:300]}")

            data = self._parse_clarification_json(text)
            if not data or not data.get("needs_clarification"):
                return None

            questions = data.get("questions", [])
            if not questions:
                return None

            # Format as a friendly response
            lines = [
                "Before I begin researching, I'd like to clarify a few things:\n"
            ]
            for i, q in enumerate(questions[:3], 1):
                lines.append(f"{i}. {q}")
            lines.append(
                "\nPlease provide these details and I'll start the research."
            )
            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Clarification phase failed: {e}", exc_info=True)
            return None  # proceed with research on failure

    def _parse_clarification_json(self, text: str) -> Optional[Dict]:
        """Parse clarification JSON from LLM response."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from code fences
        for marker in ["```json", "```"]:
            if marker in text:
                start = text.index(marker) + len(marker)
                end = text.index("```", start) if "```" in text[start:] else len(text)
                try:
                    return json.loads(text[start:end].strip())
                except (json.JSONDecodeError, ValueError):
                    pass

        # Try finding JSON object
        for i, ch in enumerate(text):
            if ch == "{":
                for j in range(len(text) - 1, i, -1):
                    if text[j] == "}":
                        try:
                            return json.loads(text[i : j + 1])
                        except json.JSONDecodeError:
                            continue
                break

        return None

    # ------------------------------------------------------------------
    # Phase 1: Planning (with adaptive depth)
    # ------------------------------------------------------------------

    def _planning_phase(self, question: str) -> tuple[List[Dict], str]:
        """Decompose the question into research steps via LLM.

        Returns (steps, complexity) where complexity is simple/moderate/complex.
        """
        messages = [
            {"role": "system", "content": PLANNING_PROMPT},
            {"role": "user", "content": question},
        ]

        try:
            response = self.llm.gen(
                model=self.model_id,
                messages=messages,
                tools=None,
                response_format={"type": "json_object"},
            )
            text = self._extract_text(response)
            self._track_tokens(self._snapshot_llm_tokens())
            logger.info(f"ResearchAgent planning LLM response: {text[:500]}")

            plan_data = self._parse_plan_json(text)
            if isinstance(plan_data, dict):
                complexity = plan_data.get("complexity", "moderate")
                steps = plan_data.get("steps", [])
            else:
                complexity = "moderate"
                steps = plan_data

            # Adaptive depth: cap steps based on assessed complexity
            cap = COMPLEXITY_CAPS.get(complexity, self.max_steps)
            cap = min(cap, self.max_steps)
            steps = steps[:cap]

            logger.info(
                f"ResearchAgent plan: complexity={complexity}, "
                f"steps={len(steps)} (cap={cap})"
            )
            return steps, complexity

        except Exception as e:
            logger.error(f"Planning phase failed: {e}", exc_info=True)
            return (
                [{"query": question, "rationale": "Direct investigation (planning failed)"}],
                "simple",
            )

    def _parse_plan_json(self, text: str):
        """Extract JSON plan from LLM response. Returns dict or list."""
        # Try direct parse
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "steps" in data:
                return data
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code fences
        for marker in ["```json", "```"]:
            if marker in text:
                start = text.index(marker) + len(marker)
                end = text.index("```", start) if "```" in text[start:] else len(text)
                try:
                    data = json.loads(text[start:end].strip())
                    if isinstance(data, dict) and "steps" in data:
                        return data
                    if isinstance(data, list):
                        return data
                except (json.JSONDecodeError, ValueError):
                    pass

        # Try finding JSON object in text
        for i, ch in enumerate(text):
            if ch == "{":
                for j in range(len(text) - 1, i, -1):
                    if text[j] == "}":
                        try:
                            data = json.loads(text[i : j + 1])
                            if isinstance(data, dict) and "steps" in data:
                                return data
                        except json.JSONDecodeError:
                            continue
                break

        logger.warning(f"Could not parse plan JSON from: {text[:200]}")
        return []

    # ------------------------------------------------------------------
    # Phase 2: Research step (core loop)
    # ------------------------------------------------------------------

    def _research_step(self, step_query: str, tools_dict: Dict) -> str:
        """Run a focused research loop for one sub-question (sequential path)."""
        report = self._research_step_with_executor(
            step_query, tools_dict, self.tool_executor
        )
        self._collect_step_sources()
        return report

    def _research_step_with_executor(
        self, step_query: str, tools_dict: Dict, executor: ToolExecutor
    ) -> str:
        """Core research loop. Works with any ToolExecutor instance."""
        system_prompt = STEP_PROMPT.replace("{step_query}", step_query)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": step_query},
        ]

        last_search_empty = False

        for iteration in range(self.max_sub_iterations):
            # Check timeout and budget
            if self._is_timed_out():
                logger.info(
                    f"Research step '{step_query[:50]}' timed out at iteration {iteration}"
                )
                break
            if self._is_over_budget():
                logger.info(
                    f"Research step '{step_query[:50]}' hit token budget at iteration {iteration}"
                )
                break

            try:
                response = self.llm.gen(
                    model=self.model_id,
                    messages=messages,
                    tools=self.tools if self.tools else None,
                )
                self._track_tokens(self._snapshot_llm_tokens())
            except Exception as e:
                logger.error(
                    f"Research step LLM call failed (iteration {iteration}): {e}",
                    exc_info=True,
                )
                break

            parsed = self.llm_handler.parse_response(response)

            if not parsed.requires_tool_call:
                return parsed.content or "No findings for this step."

            # Execute tool calls
            messages, last_search_empty = self._execute_step_tools_with_refinement(
                parsed.tool_calls, tools_dict, messages, executor, last_search_empty
            )

        # Max iterations / timeout / budget — ask for summary
        messages.append(
            {
                "role": "user",
                "content": "Please summarize your findings so far based on the information gathered.",
            }
        )
        try:
            response = self.llm.gen(
                model=self.model_id, messages=messages, tools=None
            )
            self._track_tokens(self._snapshot_llm_tokens())
            text = self._extract_text(response)
            return text or "Research step completed."
        except Exception:
            return "Research step completed."

    def _execute_step_tools_with_refinement(
        self,
        tool_calls,
        tools_dict: Dict,
        messages: List[Dict],
        executor: ToolExecutor,
        last_search_empty: bool,
    ) -> tuple[List[Dict], bool]:
        """Execute tool calls with query refinement on empty results.

        Returns (updated_messages, was_last_search_empty).
        """
        search_returned_empty = False

        for call in tool_calls:
            gen = executor.execute(
                tools_dict, call, self.llm.__class__.__name__
            )
            result = None
            call_id = None
            while True:
                try:
                    next(gen)
                except StopIteration as e:
                    result, call_id = e.value
                    break

            # Detect empty search results for refinement
            is_search = "search" in (call.name or "").lower()
            result_str = str(result) if result else ""
            if is_search and "No documents found" in result_str:
                search_returned_empty = True
                if last_search_empty:
                    # Two consecutive empty searches — inject refinement hint
                    result_str += (
                        "\n\nHint: Previous search also returned no results. "
                        "Try a very different query with different keywords, "
                        "or broaden your search terms."
                    )
                    result = result_str

            function_call_content = {
                "function_call": {
                    "name": call.name,
                    "args": call.arguments,
                    "call_id": call_id,
                }
            }
            messages.append(
                {"role": "assistant", "content": [function_call_content]}
            )
            tool_message = self.llm_handler.create_tool_message(call, result)
            messages.append(tool_message)

        return messages, search_returned_empty

    def _collect_step_sources(self):
        """Collect sources from InternalSearchTool and register with CitationManager."""
        cache_key = f"internal_search:{INTERNAL_TOOL_ID}:{self.user or ''}"
        tool = self.tool_executor._loaded_tools.get(cache_key)
        if tool and hasattr(tool, "retrieved_docs"):
            for doc in tool.retrieved_docs:
                self.citations.add(doc)

    # ------------------------------------------------------------------
    # Phase 3: Synthesis
    # ------------------------------------------------------------------

    def _synthesis_phase(
        self,
        question: str,
        plan: List[Dict],
        intermediate_reports: List[Dict],
        tools_dict: Dict,
        log_context: LogContext,
    ) -> Generator[Dict, None, None]:
        """Compile all findings into a final cited report (streaming)."""
        plan_lines = []
        for i, step in enumerate(plan, 1):
            plan_lines.append(
                f"{i}. {step.get('query', 'Unknown')} — {step.get('rationale', '')}"
            )
        plan_summary = "\n".join(plan_lines)

        findings_parts = []
        for i, report in enumerate(intermediate_reports, 1):
            step_query = report["step"].get("query", "Unknown")
            content = report["content"]
            findings_parts.append(
                f"--- Step {i}: {step_query} ---\n{content}"
            )
        findings = "\n\n".join(findings_parts)

        references = self.citations.format_references()

        synthesis_prompt = SYNTHESIS_PROMPT.replace("{question}", question)
        synthesis_prompt = synthesis_prompt.replace("{plan_summary}", plan_summary)
        synthesis_prompt = synthesis_prompt.replace("{findings}", findings)
        synthesis_prompt = synthesis_prompt.replace("{references}", references)

        messages = [
            {"role": "system", "content": synthesis_prompt},
            {"role": "user", "content": f"Please write the research report for: {question}"},
        ]

        llm_response = self.llm.gen_stream(
            model=self.model_id, messages=messages, tools=None
        )

        if log_context:
            from application.logging import build_stack_data

            log_context.stacks.append(
                {"component": "synthesis_llm", "data": build_stack_data(self.llm)}
            )

        yield from self._handle_response(
            llm_response, tools_dict, messages, log_context
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_text(self, response) -> str:
        """Extract text content from a non-streaming LLM response."""
        if isinstance(response, str):
            return response
        if hasattr(response, "message") and hasattr(response.message, "content"):
            return response.message.content or ""
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                return choice.message.content or ""
        if hasattr(response, "content") and isinstance(response.content, list):
            if response.content and hasattr(response.content[0], "text"):
                return response.content[0].text or ""
        return str(response) if response else ""
