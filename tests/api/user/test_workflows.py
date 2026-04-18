"""Tests for application/api/user/workflows/routes.py.

Previously asserted on bson.ObjectId serialization. Workflow persistence is
now Postgres-backed; coverage will be rebuilt via pg_conn + WorkflowsRepository.
"""

import pytest


@pytest.mark.skip(reason="needs PG fixture rewrite - tracked separately")
def test_user_workflows_routes_pending_pg_rewrite():
    pass
