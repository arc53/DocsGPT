import logging

from docsgpt.agents.agentic_agent import AgenticAgent
from docsgpt.agents.classic_agent import ClassicAgent
from docsgpt.agents.research_agent import ResearchAgent
from docsgpt.agents.workflow_agent import WorkflowAgent

logger = logging.getLogger(__name__)


class AgentCreator:
    agents = {
        "classic": ClassicAgent,
        "react": ClassicAgent,  # backwards compat: react falls back to classic
        "agentic": AgenticAgent,
        "research": ResearchAgent,
        "workflow": WorkflowAgent,
    }

    @classmethod
    def create_agent(cls, type, *args, **kwargs):
        agent_class = cls.agents.get(type.lower())
        if not agent_class:
            raise ValueError(f"No agent class found for type {type}")
        return agent_class(*args, **kwargs)
