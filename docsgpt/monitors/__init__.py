"""Monitors: polled checks, ingest events, webhook trigger links and approval links that wake a conversation.

Everything a monitor finds reaches the agent through
:func:`docsgpt.background.wake.wake_conversation`; this package decides
when that happens (deterministic checks first, the judge only after).
"""
