from .routes import admin_ns
from . import quotas  # noqa: F401  (registers the quota resources on admin_ns)
from . import activity  # noqa: F401  (registers the activity resources on admin_ns)

__all__ = ["admin_ns"]
