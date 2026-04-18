"""Tests for application/api/user/agents/webhooks.py.

Previously coupled to bson.ObjectId + patched agents_collection. Scheduled
for rewrite against pg_conn + AgentsRepository.
"""

import pytest


@pytest.mark.skip(reason="needs PG fixture rewrite - tracked separately")
def test_agent_webhooks_pending_pg_rewrite():
    pass
