import logging
import os
from typing import Any, Dict, Generator, List

from application.agents.base import BaseAgent
from application.logging import build_stack_data, LogContext

logger = logging.getLogger(__name__)

MAX_ITERATIONS_REASONING = 10

current_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
with open(
    os.path.join(current_dir, "application/prompts", "react_planning_prompt.txt"), "r"
) as f:
    PLANNING_PROMPT_TEMPLATE = f.read()
with open(
    os.path.join(current_dir, "application/prompts", "react_final_prompt.txt"), "r"
) as f:
    FINAL_PROMPT_TEMPLATE = f.read()


class ReActAgent(BaseAgent):
    """
    Research and Action (ReAct) Agent - Advanced reasoning agent with iterative planning.

    Implements a think-act-observe loop for complex problem-solving:
    1. Creates a strategic plan based on the query
    2. Executes tools and gathers observations
    3. Iteratively refines approach until satisfied
    4. Synthesizes final answer from all observations
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan: str = ""
        self.observations: List[str] = []

    def _gen_inner(
        self, query: str, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        """Execute ReAct reasoning loop with planning, action, and observation cycles"""

        self._reset_state()

        tools_dict = (
            self._get_tools(self.user_api_key)
            if self.user_api_key
            else self._get_user_tools(self.user)
        )
        self._prepare_tools(tools_dict)

        for iteration in range(1, MAX_ITERATIONS_REASONING + 1):
            yield {"thought": f"Reasoning... (iteration {iteration})\n\n"}

            yield from self._planning_phase(query, log_context)

            if not self.plan:
                logger.warning(
                    f"ReActAgent: No plan generated in iteration {iteration}"
                )
                break
            self.observations.append(f"Plan (iteration {iteration}): {self.plan}")

            satisfied = yield from self._execution_phase(query, tools_dict, log_context)

            if satisfied:
                logger.info("ReActAgent: Goal satisfied, stopping reasoning loop")
                break
        yield from self._synthesis_phase(query, log_context)

    def _reset_state(self):
        """Reset agent state for new query"""
        self.plan = ""
        self.observations = []

    def _planning_phase(
        self, query: str, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        """Generate strategic plan for query"""
        logger.info("ReActAgent: Creating plan...")

        plan_prompt = self._build_planning_prompt(query)
        messages = [{"role": "user", "content": plan_prompt}]

        plan_stream = self.llm.gen_stream(
            model=self.gpt_model,
            messages=messages,
            tools=self.tools if self.tools else None,
        )

        if log_context:
            log_context.stacks.append(
                {"component": "planning_llm", "data": build_stack_data(self.llm)}
            )
        plan_parts = []
        for chunk in plan_stream:
            content = self._extract_content(chunk)
            if content:
                plan_parts.append(content)
                yield {"thought": content}
        self.plan = "".join(plan_parts)

    def _execution_phase(
        self, query: str, tools_dict: Dict, log_context: LogContext
    ) -> Generator[bool, None, None]:
        """Execute plan with tool calls and observations"""
        execution_prompt = self._build_execution_prompt(query)
        messages = self._build_messages(execution_prompt, query)

        llm_response = self._llm_gen(messages, log_context)
        initial_content = self._extract_content(llm_response)

        if initial_content:
            self.observations.append(f"Initial response: {initial_content}")
        processed_response = self._llm_handler(
            llm_response, tools_dict, messages, log_context
        )

        for tool_call in self.tool_calls:
            observation = (
                f"Executed: {tool_call.get('tool_name', 'Unknown')} "
                f"with args {tool_call.get('arguments', {})}. "
                f"Result: {str(tool_call.get('result', ''))[:200]}"
            )
            self.observations.append(observation)
        final_content = self._extract_content(processed_response)
        if final_content:
            self.observations.append(f"Response after tools: {final_content}")
        if log_context:
            log_context.stacks.append(
                {
                    "component": "agent_tool_calls",
                    "data": {"tool_calls": self.tool_calls.copy()},
                }
            )
        yield {"sources": self.retrieved_docs}
        yield {"tool_calls": self._get_truncated_tool_calls()}

        return "SATISFIED" in (final_content or "")

    def _synthesis_phase(
        self, query: str, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        """Synthesize final answer from all observations"""
        logger.info("ReActAgent: Generating final answer...")

        final_prompt = self._build_final_answer_prompt(query)
        messages = [{"role": "user", "content": final_prompt}]

        final_stream = self.llm.gen_stream(
            model=self.gpt_model, messages=messages, tools=None
        )

        if log_context:
            log_context.stacks.append(
                {"component": "final_answer_llm", "data": build_stack_data(self.llm)}
            )
        for chunk in final_stream:
            content = self._extract_content(chunk)
            if content:
                yield {"answer": content}

    def _build_planning_prompt(self, query: str) -> str:
        """Build planning phase prompt"""
        prompt = PLANNING_PROMPT_TEMPLATE.replace("{query}", query)
        prompt = prompt.replace("{prompt}", self.prompt or "")
        prompt = prompt.replace("{summaries}", "")
        prompt = prompt.replace("{observations}", "\n".join(self.observations))
        return prompt

    def _build_execution_prompt(self, query: str) -> str:
        """Build execution phase prompt with plan and observations"""
        observations_str = "\n".join(self.observations)

        if len(observations_str) > 20000:
            observations_str = observations_str[:20000] + "\n...[truncated]"
        return (
            f"{self.prompt or ''}\n\n"
            f"Follow this plan:\n{self.plan}\n\n"
            f"Observations:\n{observations_str}\n\n"
            f"If sufficient data exists to answer '{query}', respond with 'SATISFIED'. "
            f"Otherwise, continue executing the plan."
        )

    def _build_final_answer_prompt(self, query: str) -> str:
        """Build final synthesis prompt"""
        observations_str = "\n".join(self.observations)

        if len(observations_str) > 10000:
            observations_str = observations_str[:10000] + "\n...[truncated]"
            logger.warning("ReActAgent: Observations truncated for final answer")
        return FINAL_PROMPT_TEMPLATE.format(query=query, observations=observations_str)

    def _extract_content(self, response: Any) -> str:
        """Extract text content from various LLM response formats"""
        if not response:
            return ""
        collected = []

        if isinstance(response, str):
            return response
        if hasattr(response, "message") and hasattr(response.message, "content"):
            if response.message.content:
                return response.message.content
        if hasattr(response, "choices") and response.choices:
            if hasattr(response.choices[0], "message"):
                content = response.choices[0].message.content
                if content:
                    return content
        if hasattr(response, "content") and isinstance(response.content, list):
            if response.content and hasattr(response.content[0], "text"):
                return response.content[0].text
        try:
            for chunk in response:
                content_piece = ""

                if hasattr(chunk, "choices") and chunk.choices:
                    if hasattr(chunk.choices[0], "delta"):
                        delta_content = chunk.choices[0].delta.content
                        if delta_content:
                            content_piece = delta_content
                elif hasattr(chunk, "type") and chunk.type == "content_block_delta":
                    if hasattr(chunk, "delta") and hasattr(chunk.delta, "text"):
                        content_piece = chunk.delta.text
                elif isinstance(chunk, str):
                    content_piece = chunk
                if content_piece:
                    collected.append(content_piece)
        except (TypeError, AttributeError):
            logger.debug(
                f"Response not iterable or unexpected format: {type(response)}"
            )
        except Exception as e:
            logger.error(f"Error extracting content: {e}")
        return "".join(collected)
