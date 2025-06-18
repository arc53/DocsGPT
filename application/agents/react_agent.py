import os
from typing import Dict, Generator, List, Any
import logging

from application.agents.base import BaseAgent
from application.logging import build_stack_data, LogContext
from application.retriever.base import BaseRetriever

logger = logging.getLogger(__name__)

current_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
with open(
    os.path.join(current_dir, "application/prompts", "react_planning_prompt.txt"), "r"
) as f:
    planning_prompt_template = f.read()
with open(
    os.path.join(current_dir, "application/prompts", "react_final_prompt.txt"),
    "r",
) as f:
    final_prompt_template = f.read()
    
MAX_ITERATIONS_REASONING = 10

class ReActAgent(BaseAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan: str = ""
        self.observations: List[str] = []

    def _extract_content_from_llm_response(self, resp: Any) -> str:
        """
        Helper to extract string content from various LLM response types.
        Handles strings, message objects (OpenAI-like), and streams.
        Adapt stream handling for your specific LLM client if not OpenAI.
        """
        collected_content = []
        if isinstance(resp, str):
            collected_content.append(resp)
        elif ( # OpenAI non-streaming or Anthropic non-streaming (older SDK style)
            hasattr(resp, "message")
            and hasattr(resp.message, "content")
            and resp.message.content is not None
        ):
            collected_content.append(resp.message.content)
        elif ( # OpenAI non-streaming (Pydantic model), Anthropic new SDK non-streaming
            hasattr(resp, "choices") and resp.choices and
            hasattr(resp.choices[0], "message") and
            hasattr(resp.choices[0].message, "content") and
            resp.choices[0].message.content is not None
        ):
            collected_content.append(resp.choices[0].message.content) # OpenAI
        elif ( # Anthropic new SDK non-streaming content block
             hasattr(resp, "content") and isinstance(resp.content, list) and resp.content and
             hasattr(resp.content[0], "text")
        ):
            collected_content.append(resp.content[0].text) # Anthropic
        else:
            # Assume resp is a stream if not a recognized object
            try:
                for chunk in resp: # This will fail if resp is not iterable (e.g. a non-streaming response object)
                    content_piece = ""
                    # OpenAI-like stream
                    if hasattr(chunk, 'choices') and len(chunk.choices) > 0 and \
                       hasattr(chunk.choices[0], 'delta') and \
                       hasattr(chunk.choices[0].delta, 'content') and \
                       chunk.choices[0].delta.content is not None:
                        content_piece = chunk.choices[0].delta.content
                    # Anthropic-like stream (ContentBlockDelta)
                    elif hasattr(chunk, 'type') and chunk.type == 'content_block_delta' and \
                         hasattr(chunk, 'delta') and hasattr(chunk.delta, 'text'):
                        content_piece = chunk.delta.text
                    elif isinstance(chunk, str): # Simplest case: stream of strings
                        content_piece = chunk

                    if content_piece:
                        collected_content.append(content_piece)
            except TypeError: # If resp is not iterable (e.g. a final response object that wasn't caught above)
                logger.debug(f"Response type {type(resp)} could not be iterated as a stream. It might be a non-streaming object not handled by specific checks.")
            except Exception as e:
                logger.error(f"Error processing potential stream chunk: {e}, chunk was: {getattr(chunk, '__dict__', chunk)}")


        return "".join(collected_content)

    def _gen_inner(
        self, query: str, retriever: BaseRetriever, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        # Reset state for this generation call
        self.plan = ""
        self.observations = []
        retrieved_data = self._retriever_search(retriever, query, log_context)

        if self.user_api_key:
            tools_dict = self._get_tools(self.user_api_key)
        else:
            tools_dict = self._get_user_tools(self.user)
        self._prepare_tools(tools_dict)

        docs_together = "\n".join([doc["text"] for doc in retrieved_data])
        iterating_reasoning = 0
        while iterating_reasoning < MAX_ITERATIONS_REASONING:
            iterating_reasoning += 1
            # 1. Create Plan
            logger.info("ReActAgent: Creating plan...")
            plan_stream = self._create_plan(query, docs_together, log_context)
            current_plan_parts = []
            yield {"thought": f"Reasoning... (iteration {iterating_reasoning})\n\n"}
            for line_chunk in plan_stream:
                current_plan_parts.append(line_chunk)
                yield {"thought": line_chunk}
            self.plan = "".join(current_plan_parts)
            if self.plan:
                self.observations.append(f"Plan: {self.plan} Iteration: {iterating_reasoning}")


            max_obs_len = 20000
            obs_str = "\n".join(self.observations)
            if len(obs_str) > max_obs_len:
                obs_str = obs_str[:max_obs_len] + "\n...[observations truncated]"
            execution_prompt_str = (
                (self.prompt or "")
                + f"\n\nFollow this plan:\n{self.plan}"
                + f"\n\nObservations:\n{obs_str}"
                + f"\n\nIf there is enough data to complete user query '{query}', Respond with 'SATISFIED' only. Otherwise, continue. Dont Menstion 'SATISFIED' in your response if you are not ready. "
            )
            
            messages = self._build_messages(execution_prompt_str, query, retrieved_data)

            resp_from_llm_gen = self._llm_gen(messages, log_context)

            initial_llm_thought_content = self._extract_content_from_llm_response(resp_from_llm_gen)
            if initial_llm_thought_content:
                self.observations.append(f"Initial thought/response: {initial_llm_thought_content}")
            else:
                logger.info("ReActAgent: Initial LLM response (before handler) had no textual content (might be only tool calls).")
            resp_after_handler = self._llm_handler(resp_from_llm_gen, tools_dict, messages, log_context)
            
            for tool_call_info in self.tool_calls: # Iterate over self.tool_calls populated by _llm_handler
                observation_string = (
                    f"Executed Action: Tool '{tool_call_info.get('tool_name', 'N/A')}' "
                    f"with arguments '{tool_call_info.get('arguments', '{}')}'. Result: '{str(tool_call_info.get('result', ''))[:200]}...'"
                )
                self.observations.append(observation_string)

            content_after_handler = self._extract_content_from_llm_response(resp_after_handler)
            if content_after_handler:
                self.observations.append(f"Response after tool execution: {content_after_handler}")
            else:
                logger.info("ReActAgent: LLM response after handler had no textual content.")

            if log_context:
                log_context.stacks.append(
                    {"component": "agent_tool_calls", "data": {"tool_calls": self.tool_calls.copy()}}
                )

            yield {"sources": retrieved_data}

            display_tool_calls = []
            for tc in self.tool_calls:
                cleaned_tc = tc.copy()
                if len(str(cleaned_tc.get("result", ""))) > 50:
                    cleaned_tc["result"] = str(cleaned_tc["result"])[:50] + "..."
                display_tool_calls.append(cleaned_tc)
            if display_tool_calls:
                yield {"tool_calls": display_tool_calls}
            
            if "SATISFIED" in content_after_handler:
                logger.info("ReActAgent: LLM satisfied with the plan and data. Stopping reasoning.")
                break

        # 3. Create Final Answer based on all observations
        final_answer_stream = self._create_final_answer(query, self.observations, log_context)
        for answer_chunk in final_answer_stream:
            yield {"answer": answer_chunk}
        logger.info("ReActAgent: Finished generating final answer.")

    def _create_plan(
        self, query: str, docs_data: str, log_context: LogContext = None
    ) -> Generator[str, None, None]:
        plan_prompt_filled = planning_prompt_template.replace("{query}", query)
        if "{summaries}" in plan_prompt_filled:
            summaries = docs_data if docs_data else "No documents retrieved."
            plan_prompt_filled = plan_prompt_filled.replace("{summaries}", summaries)
        plan_prompt_filled = plan_prompt_filled.replace("{prompt}", self.prompt or "")
        plan_prompt_filled = plan_prompt_filled.replace("{observations}", "\n".join(self.observations))

        messages = [{"role": "user", "content": plan_prompt_filled}]

        plan_stream_from_llm = self.llm.gen_stream(
            model=self.gpt_model, messages=messages, tools=getattr(self, 'tools', None) # Use self.tools
        )
        if log_context:
            data = build_stack_data(self.llm)
            log_context.stacks.append({"component": "planning_llm", "data": data})

        for chunk in plan_stream_from_llm:
            content_piece = self._extract_content_from_llm_response(chunk)
            if content_piece:
                yield content_piece

    def _create_final_answer(
        self, query: str, observations: List[str], log_context: LogContext = None
    ) -> Generator[str, None, None]:
        observation_string = "\n".join(observations)
        max_obs_len = 10000
        if len(observation_string) > max_obs_len:
            observation_string = observation_string[:max_obs_len] + "\n...[observations truncated]"
            logger.warning("ReActAgent: Truncated observations for final answer prompt due to length.")

        final_answer_prompt_filled = final_prompt_template.format(
            query=query, observations=observation_string
        )

        messages = [{"role": "user", "content": final_answer_prompt_filled}]

        # Final answer should synthesize, not call tools.
        final_answer_stream_from_llm = self.llm.gen_stream(
            model=self.gpt_model, messages=messages, tools=None
        )
        if log_context:
            data = build_stack_data(self.llm)
            log_context.stacks.append({"component": "final_answer_llm", "data": data})

        for chunk in final_answer_stream_from_llm:
            content_piece = self._extract_content_from_llm_response(chunk)
            if content_piece:
                yield content_piece