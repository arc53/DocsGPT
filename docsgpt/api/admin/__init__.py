from .routes import admin_ns
from . import quotas  # noqa: F401  (registers the quota resources on admin_ns)
from . import activity  # noqa: F401  (registers the activity resources on admin_ns)
from . import connectors  # noqa: F401  (registers the connector policy resources on admin_ns)
from . import decisions  # noqa: F401  (registers the decision model status on admin_ns)
from . import defaults  # noqa: F401  (registers the default settings for new sources and agents on admin_ns)
from . import guardrails  # noqa: F401  (registers the floor and MCP description warnings on admin_ns)

__all__ = ["admin_ns"]
