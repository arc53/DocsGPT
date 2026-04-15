"""Additional tests for application/api/user/base.py to cover remaining branches.

Target missing lines:
  - 131: when "pinned" is missing from existing agent_preferences
  - 157-158: invalid ObjectId in resolve_tool_details (continue branch)
"""

import pytest
from bson import ObjectId
from unittest.mock import patch


@pytest.mark.unit
class TestEnsureUserDocMissingPinnedBranch:
    """Cover line 131: when existing doc has shared_with_me but no pinned."""

    def test_adds_missing_pinned_field(self, mock_mongo_db):
        from application.api.user.base import ensure_user_doc
        from application.core.settings import settings

        users_collection = mock_mongo_db[settings.MONGO_DB_NAME]["users"]
        user_id = "user_missing_pinned"

        # Insert a user that only has shared_with_me but not pinned
        users_collection.insert_one(
            {
                "user_id": user_id,
                "agent_preferences": {
                    "shared_with_me": ["agent-x"],
                    # "pinned" intentionally absent
                },
            }
        )

        result = ensure_user_doc(user_id)

        assert "pinned" in result["agent_preferences"]
        assert result["agent_preferences"]["pinned"] == []
        assert result["agent_preferences"]["shared_with_me"] == ["agent-x"]


@pytest.mark.unit
class TestResolveToolDetailsInvalidIds:
    """Cover lines 157-158: invalid ObjectId strings are skipped silently."""

    def test_skips_invalid_object_ids(self, mock_mongo_db):
        from application.api.user.base import resolve_tool_details
        from application.core.settings import settings

        user_tools = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        valid_id = ObjectId()
        user_tools.insert_one({"_id": valid_id, "name": "valid_tool"})

        result = resolve_tool_details(["not-an-objectid", str(valid_id), "also-invalid"])

        assert len(result) == 1
        assert result[0]["id"] == str(valid_id)
        assert result[0]["name"] == "valid_tool"

    def test_all_invalid_ids_returns_empty(self, mock_mongo_db):
        from application.api.user.base import resolve_tool_details

        result = resolve_tool_details(["bad-id-1", "bad-id-2"])
        assert result == []
