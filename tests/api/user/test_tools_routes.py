"""Tests for application/api/user/tools/routes.py.

Previously coupled to bson.ObjectId + Mongo-shaped collection mocks.
Scheduled for rewrite against pg_conn + UserToolsRepository.
"""

import pytest


@pytest.mark.skip(reason="needs PG fixture rewrite - tracked separately")
def test_user_tools_routes_pending_pg_rewrite():
    pass
