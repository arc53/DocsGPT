from typing import Dict, Generator, List

from application.agents.base import BaseAgent
from application.logging import build_stack_data, LogContext
from application.retriever.base import BaseRetriever


class ReActAgent(BaseAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan = ""
        self.planning_prompt: str = (
            "You are an AI assistant and talk like you're thinking out loud. Given the following query, outline a concise thought process that includes key steps and considerations necessary for effective analysis and response and don't give pointwise. The goal is to break down the query into manageable components without excessive detail, focusing on clarity and logical progression.Include the following elements in your thought process: 1.Identify the main objective of the query.2.Determine any relevant context or background information needed to understand the query.3.List potential approaches or methods to address the query.4.Highlight any critical factors or constraints that may influence the outcome.5.Summarize the anticipated next steps based on the outlined thought process. Query: {query} Summaries: {summaries}"
        )
        self.observations: List[str] = []

    def _gen_inner(
        self, query: str, retriever: BaseRetriever, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        retrieved_data = self._retriever_search(retriever, query, log_context)

        tools_dict = self._get_user_tools(self.user)
        self._prepare_tools(tools_dict)

        docs_together = "\n".join([doc["text"] for doc in retrieved_data])
        plan = self._create_plan(query, docs_together, log_context)
        for line in plan:
            if isinstance(line, str):
                self.plan += line
                yield {"thought": line}

        prompt = self.prompt + f"\nFollow this plan: {self.plan}"
        messages = self._build_messages(prompt, query, retrieved_data)

        resp = self._llm_gen(messages, log_context)

        if isinstance(resp, str):
            self.observations.append(resp)
        if (
            hasattr(resp, "message")
            and hasattr(resp.message, "content")
            and resp.message.content is not None
        ):
            self.observations.append(resp.message.content)

        resp = self._llm_handler(resp, tools_dict, messages, log_context)

        for tool_call in self.tool_calls:
            observation = (
                f"Action '{tool_call['action_name']}' of tool '{tool_call['tool_name']}' "
                f"with arguments '{tool_call['arguments']}' returned: '{tool_call['result']}'"
            )
            self.observations.append(observation)

        if isinstance(resp, str):
            self.observations.append(resp)
        elif (
            hasattr(resp, "message")
            and hasattr(resp.message, "content")
            and resp.message.content is not None
        ):
            self.observations.append(resp.message.content)
        else:
            completion = self.llm.gen_stream(
                model=self.gpt_model, messages=messages, tools=self.tools
            )
            for line in completion:
                if isinstance(line, str):
                    self.observations.append(line)

        yield {"sources": retrieved_data}
        yield {"tool_calls": self.tool_calls.copy()}

        final_answer = self._create_final_answer(query, self.observations, log_context)
        for line in final_answer:
            if isinstance(line, str):
                yield {"answer": line}

    def _create_plan(
        self, query: str, docs_data: str, log_context: LogContext = None
    ) -> Generator[str, None, None]:
        plan_prompt = self.planning_prompt.replace("{query}", query)
        if "{summaries}" in self.planning_prompt:
            summaries = docs_data
            plan_prompt = plan_prompt.replace("{summaries}", summaries)

        messages = [{"role": "user", "content": plan_prompt}]
        print(self.tools)
        plan = self.llm.gen_stream(
            model=self.gpt_model, messages=messages, tools=self.tools
        )
        if log_context:
            data = build_stack_data(self.llm)
            log_context.stacks.append({"component": "planning_llm", "data": data})
        return plan

    def _create_final_answer(
        self, query: str, observations: List[str], log_context: LogContext = None
    ) -> str:
        observation_string = "\n".join(observations)
        final_answer_prompt = f"Query: {query} \n Observations: {observation_string} \n Now, using the insights from the observations, formulate a well-structured and precise final answer."

        messages = [{"role": "user", "content": final_answer_prompt}]
        final_answer = self.llm.gen_stream(model=self.gpt_model, messages=messages)
        if log_context:
            data = build_stack_data(self.llm)
            log_context.stacks.append({"component": "final_answer_llm", "data": data})
        return final_answer
