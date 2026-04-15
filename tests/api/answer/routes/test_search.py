"""Tests for application/api/answer/routes/search.py.

Previously coupled to mock_mongo_db + bson.ObjectId + bson.DBRef.
Scheduled for rewrite against pg_conn + new repositories.
"""

import pytest


@pytest.mark.skip(reason="needs PG fixture rewrite - tracked separately")
def test_search_resource_pending_pg_rewrite():
    pass
