"""Teams API namespace: team CRUD, membership, and resource-sharing grants."""

from .routes import teams_ns

# Registered on ``teams_ns`` when imported.
from . import chat_export, outside, usage  # noqa: E402,F401

__all__ = ["teams_ns"]
