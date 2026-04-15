"""Tests for application/api/answer/routes/answer.py.

Previously coupled to mock_mongo_db + bson.ObjectId. Scheduled for rewrite
against pg_conn + new repositories.
"""

import pytest


@pytest.mark.skip(reason="needs PG fixture rewrite - tracked separately")
def test_answer_resource_pending_pg_rewrite():
    pass
