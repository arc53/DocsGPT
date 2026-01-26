"""Workflow Node Agents - defines specialized agents for workflow nodes."""

from typing import Any, Dict, List, Optional, Type

from application.agents.base import BaseAgent
from application.agents.classic_agent import ClassicAgent
from application.agents.react_agent import ReActAgent
from application.agents.workflows.schemas import AgentType


class ToolFilterMixin:
    """Mixin that filters fetched tools to only those specified in tool_ids."""

    _allowed_tool_ids: List[str]

    def _get_user_tools(self, user: str = "local") -> Dict[str, Dict[str, Any]]:
        all_tools = super()._get_user_tools(user)
        if not self._allowed_tool_ids:
            return {}
        filtered_tools = {
            tool_id: tool
            for tool_id, tool in all_tools.items()
            if str(tool.get("_id", "")) in self._allowed_tool_ids
        }
        return filtered_tools

    def _get_tools(self, api_key: str = None) -> Dict[str, Dict[str, Any]]:
        all_tools = super()._get_tools(api_key)
        if not self._allowed_tool_ids:
            return {}
        filtered_tools = {
            tool_id: tool
            for tool_id, tool in all_tools.items()
            if str(tool.get("_id", "")) in self._allowed_tool_ids
        }
        return filtered_tools


class WorkflowNodeClassicAgent(ToolFilterMixin, ClassicAgent):

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
        self._allowed_tool_ids = tool_ids or []


class WorkflowNodeReActAgent(ToolFilterMixin, ReActAgent):

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
        self._allowed_tool_ids = tool_ids or []


class WorkflowNodeAgentFactory:

    _agents: Dict[AgentType, Type[BaseAgent]] = {
        AgentType.CLASSIC: WorkflowNodeClassicAgent,
        AgentType.REACT: WorkflowNodeReActAgent,
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
