import logging

from application.agents.classic_agent import ClassicAgent
from application.agents.react_agent import ReActAgent
from application.agents.workflow_agent import WorkflowAgent

logger = logging.getLogger(__name__)


class AgentCreator:
    agents = {
        "classic": ClassicAgent,
        "react": ReActAgent,
        "workflow": WorkflowAgent,
    }

    @classmethod
    def create_agent(cls, type, *args, **kwargs):
        agent_class = cls.agents.get(type.lower())
        if not agent_class:
            raise ValueError(f"No agent class found for type {type}")
        return agent_class(*args, **kwargs)
