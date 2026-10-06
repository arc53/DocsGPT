"""Monitors module: the public trigger and approval links, and the Monitors page's routes."""

from .public import approvals_ns, triggers_ns
from .routes import monitors_ns

__all__ = ["approvals_ns", "monitors_ns", "triggers_ns"]
