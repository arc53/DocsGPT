from application.agents.classic_agent import ClassicAgent
from application.agents.react_agent import ReActAgent
import logging

logger = logging.getLogger(__name__)


class AgentCreator:
    agents = {
        "classic": ClassicAgent,
        "react": ReActAgent,
    }

    @classmethod
    def create_agent(cls, type, *args, **kwargs):
        agent_class = cls.agents.get(type.lower())
        if not agent_class:
            raise ValueError(f"No agent class found for type {type}")
        
        return agent_class(*args, **kwargs)


DOCSGPT_DEFAULT_ORIGINS = {
    "https://app.docsgpt.cloud",
    "https://ent.docsgpt.cloud",
}


def _is_origin_allowed(agent, origin: str | None) -> bool:
    """
    Basic origin whitelist check.

    - If agent has no origin whitelisting enabled/configured, allow all.
    - If whitelisting is enabled and Origin is missing, reject.
    - Always allow DocsGPT default origins.
    - Otherwise, check against agent-configured allowed origins.
    """
    # If feature is not enabled or no config on this agent, allow
    if not getattr(agent, "origin_whitelist_enabled", False):
        return True

    # No Origin header and whitelist enabled → reject
    if origin is None:
        return False

    # Always allow internal DocsGPT origins
    if origin in DOCSGPT_DEFAULT_ORIGINS:
        return True

    # Read agent-configured allowed origins
    raw_allowed = getattr(agent, "allowed_origins", "") or ""
    allowed = {o.strip() for o in raw_allowed.split(",") if o.strip()}

    # If no custom origins, fall back to only default ones (already checked)
    if not allowed:
        return False

    return origin in allowed
