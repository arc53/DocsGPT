from .routes import admin_ns
from . import quotas  # noqa: F401  (registers the quota resources on admin_ns)

__all__ = ["admin_ns"]
