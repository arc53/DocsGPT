"""Workflow Node Agents - defines specialized agents for workflow nodes."""

from typing import Dict, List, Optional, Type

from application.agents.agentic_agent import AgenticAgent
from application.agents.base import BaseAgent
from application.agents.classic_agent import ClassicAgent
from application.agents.research_agent import ResearchAgent
from application.agents.workflows.schemas import AgentType


class _WorkflowNodeMixin:
    """Common __init__ for all workflow node agents."""

    def __init__(
        self,
        endpoint: str,
        llm_name: str,
        model_id: str,
        api_key: str,
        tool_ids: Optional[List[str]] = None,
        **kwargs,
    ):
        super().__init__(
            endpoint=endpoint,
            llm_name=llm_name,
            model_id=model_id,
            api_key=api_key,
            **kwargs,
        )
        # Scope the executor to exactly the node's configured tools. Agents
        # fetch their toolset via ``tool_executor.get_tools()``, so the scope
        # must live on the executor — it resolves builtin synthetic ids
        # (Artifact / Code Executor / Read Document) and ``user_tools`` rows
        # alike, and an empty list means the node's LLM gets no tools.
        self.tool_executor.allowed_tool_ids = [str(t) for t in (tool_ids or [])]


class WorkflowNodeClassicAgent(_WorkflowNodeMixin, ClassicAgent):
    pass


class WorkflowNodeAgenticAgent(_WorkflowNodeMixin, AgenticAgent):
    pass


class WorkflowNodeResearchAgent(_WorkflowNodeMixin, ResearchAgent):
    pass


class WorkflowNodeAgentFactory:

    _agents: Dict[AgentType, Type[BaseAgent]] = {
        AgentType.CLASSIC: WorkflowNodeClassicAgent,
        AgentType.REACT: WorkflowNodeClassicAgent,  # backwards compat
        AgentType.AGENTIC: WorkflowNodeAgenticAgent,
        AgentType.RESEARCH: WorkflowNodeResearchAgent,
    }

    @classmethod
    def create(
        cls,
        agent_type: AgentType,
        endpoint: str,
        llm_name: str,
        model_id: str,
        api_key: str,
        tool_ids: Optional[List[str]] = None,
        **kwargs,
    ) -> BaseAgent:
        agent_class = cls._agents.get(agent_type)
        if not agent_class:
            raise ValueError(f"Unsupported agent type: {agent_type}")
        return agent_class(
            endpoint=endpoint,
            llm_name=llm_name,
            model_id=model_id,
            api_key=api_key,
            tool_ids=tool_ids,
            **kwargs,
        )
