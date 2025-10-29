from application.agents.classic_agent import ClassicAgent
from application.agents.react_agent import ReActAgent


cclass AgentCreator:
    """
    AgentCreator enables building, configuring, and deploying custom AI agents in DocsGPT.

    Features:
    - Supports classic, retrieval-augmented, and react agent workflows.
    - Integrates Python, transformers, and enterprise RAG.
    - Easily extensible for new models and prompt strategies.

    Example:
        creator = AgentCreator()
        agent = creator.create_agent("classic", ...)
        agent.query("What is the warranty policy?")

    Hacktoberfest 2025: Improved documentation for new users and enterprise adoption.
    """


    @classmethod
    def create_agent(cls, type, *args, **kwargs):
        agent_class = cls.agents.get(type.lower())
        if not agent_class:
            raise ValueError(f"No agent class found for type {type}")
        return agent_class(*args, **kwargs)
