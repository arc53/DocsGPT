"""Unit tests for the SCIM 2.0 provisioning endpoints (application/api/scim/)."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from application.core.settings import settings

TOKEN = "test-scim-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
USER_PK = "3f1f2bd6-8a87-4f7e-9c2b-2f76c1a4f0d3"

ERROR_URN = "urn:ietf:params:scim:api:messages:2.0:Error"
LIST_RESPONSE_URN = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_OP_URN = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
USER_URN = "urn:ietf:params:scim:schemas:core:2.0:User"


def _user_row(pk=USER_PK, user_id="alice@example.com", active=True):
    return {
        "id": pk,
        "user_id": user_id,
        "active": active,
        "agent_preferences": {"pinned": [], "shared_with_me": []},
        "tool_preferences": {},
        "created_at": "2026-06-09T10:00:00+00:00",
        "updated_at": "2026-06-09T11:00:00+00:00",
    }


@pytest.fixture(scope="module")
def app():
    """Import the Flask app with auth mocked to avoid JWT setup issues."""
    with patch("application.app.handle_auth", return_value={"sub": "test_user"}):
        from application.app import app as flask_app

        flask_app.config["TESTING"] = True
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def scim_settings(monkeypatch):
    """Enable SCIM with a known bearer token on the real settings singleton."""
    monkeypatch.setattr(settings, "SCIM_ENABLED", True)
    monkeypatch.setattr(settings, "SCIM_TOKEN", TOKEN)


@pytest.fixture
def scim_mocks():
    """Patch DB plumbing, repositories, and denylist functions used by the routes."""
    with patch("application.api.scim.routes.db_session") as db_session_mock, patch(
        "application.api.scim.routes.db_readonly"
    ) as db_readonly_mock, patch(
        "application.api.scim.routes.UsersRepository"
    ) as users_cls, patch(
        "application.api.scim.routes.AuthEventsRepository"
    ) as audit_cls, patch(
        "application.api.scim.routes.deny_user"
    ) as deny_user_mock:
        conn = MagicMock(name="conn")
        db_session_mock.return_value.__enter__.return_value = conn
        db_readonly_mock.return_value.__enter__.return_value = conn
        # Don't let the mocked context manager swallow exceptions (a real
        # ``engine.begin()`` __exit__ returns None) — _RevocationUnavailable
        # must propagate to the blueprint error handler.
        db_session_mock.return_value.__exit__.return_value = False
        db_readonly_mock.return_value.__exit__.return_value = False
        yield SimpleNamespace(
            users=users_cls.return_value,
            audit=audit_cls.return_value,
            deny_user=deny_user_mock,
            conn=conn,
        )


@pytest.mark.unit
class TestScimGate:

    def test_disabled_returns_scim_404_everywhere(self, client, scim_mocks, monkeypatch):
        monkeypatch.setattr(settings, "SCIM_ENABLED", False)
        monkeypatch.setattr(settings, "SCIM_TOKEN", TOKEN)
        for path in ("/scim/v2/Users", "/scim/v2/ServiceProviderConfig", "/scim/v2/Groups"):
            response = client.get(path, headers=AUTH)
            assert response.status_code == 404
            body = response.get_json()
            assert body["schemas"] == [ERROR_URN]
            assert body["status"] == "404"
        scim_mocks.users.list_paginated.assert_not_called()

    def test_enabled_without_token_returns_503(self, client, scim_mocks, monkeypatch):
        monkeypatch.setattr(settings, "SCIM_ENABLED", True)
        monkeypatch.setattr(settings, "SCIM_TOKEN", None)
        response = client.get("/scim/v2/Users", headers=AUTH)
        assert response.status_code == 503
        body = response.get_json()
        assert body["schemas"] == [ERROR_URN]
        assert body["status"] == "503"

    def test_enabled_with_empty_token_returns_503(self, client, scim_mocks, monkeypatch):
        monkeypatch.setattr(settings, "SCIM_ENABLED", True)
        monkeypatch.setattr(settings, "SCIM_TOKEN", "")
        response = client.get("/scim/v2/Users", headers=AUTH)
        assert response.status_code == 503

    def test_wrong_bearer_returns_401(self, client, scim_settings, scim_mocks):
        response = client.get("/scim/v2/Users", headers={"Authorization": "Bearer wrong-token"})
        assert response.status_code == 401
        assert response.get_json()["schemas"] == [ERROR_URN]
        scim_mocks.users.list_paginated.assert_not_called()

    def test_missing_authorization_returns_401(self, client, scim_settings, scim_mocks):
        response = client.get("/scim/v2/Users")
        assert response.status_code == 401
        assert response.get_json()["status"] == "401"

    def test_non_bearer_scheme_returns_401(self, client, scim_settings, scim_mocks):
        response = client.get("/scim/v2/Users", headers={"Authorization": f"Basic {TOKEN}"})
        assert response.status_code == 401

    def test_errors_use_scim_content_type(self, client, scim_settings, scim_mocks):
        response = client.get("/scim/v2/Users", headers={"Authorization": "Bearer nope"})
        assert response.content_type.startswith("application/scim+json")


@pytest.mark.unit
class TestDiscoveryEndpoints:

    def test_service_provider_config_shape(self, client, scim_settings, scim_mocks):
        response = client.get("/scim/v2/ServiceProviderConfig", headers=AUTH)
        assert response.status_code == 200
        assert response.content_type.startswith("application/scim+json")
        body = response.get_json()
        assert body["schemas"] == ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"]
        assert body["patch"] == {"supported": True}
        assert body["bulk"]["supported"] is False
        assert body["filter"] == {"supported": True, "maxResults": 200}
        assert body["changePassword"] == {"supported": False}
        assert body["sort"] == {"supported": False}
        assert body["etag"] == {"supported": False}
        scheme = body["authenticationSchemes"][0]
        assert scheme["type"] == "oauthbearertoken"
        assert scheme["name"] == "Bearer Token"

    def test_resource_types_advertise_user_only(self, client, scim_settings, scim_mocks):
        response = client.get("/scim/v2/ResourceTypes", headers=AUTH)
        assert response.status_code == 200
        body = response.get_json()
        assert body["schemas"] == [LIST_RESPONSE_URN]
        assert body["totalResults"] == 1
        resource = body["Resources"][0]
        assert resource["name"] == "User"
        assert resource["endpoint"] == "/scim/v2/Users"
        assert resource["schema"] == USER_URN

    def test_schemas_advertise_user_only(self, client, scim_settings, scim_mocks):
        response = client.get("/scim/v2/Schemas", headers=AUTH)
        assert response.status_code == 200
        body = response.get_json()
        assert body["schemas"] == [LIST_RESPONSE_URN]
        assert body["totalResults"] == 1
        assert body["Resources"][0]["id"] == USER_URN


@pytest.mark.unit
class TestListUsers:

    def test_filter_username_eq_passes_value_to_repo(self, client, scim_settings, scim_mocks):
        scim_mocks.users.list_paginated.return_value = (1, [_user_row()])
        response = client.get(
            "/scim/v2/Users",
            headers=AUTH,
            query_string={"filter": 'userName eq "alice smith@example.com"'},
        )
        assert response.status_code == 200
        scim_mocks.users.list_paginated.assert_called_once_with("alice smith@example.com", 0, 100)

    def test_filter_keywords_are_case_insensitive(self, client, scim_settings, scim_mocks):
        scim_mocks.users.list_paginated.return_value = (0, [])
        response = client.get(
            "/scim/v2/Users", headers=AUTH, query_string={"filter": 'UserName EQ "bob@example.com"'}
        )
        assert response.status_code == 200
        scim_mocks.users.list_paginated.assert_called_once_with("bob@example.com", 0, 100)

    @pytest.mark.parametrize(
        "bad_filter",
        [
            'userName co "alice"',
            'displayName eq "alice"',
            'userName eq "a" and active eq true',
            "userName eq alice",
        ],
    )
    def test_unsupported_filter_rejected(self, client, scim_settings, scim_mocks, bad_filter):
        response = client.get("/scim/v2/Users", headers=AUTH, query_string={"filter": bad_filter})
        assert response.status_code == 400
        body = response.get_json()
        assert body["schemas"] == [ERROR_URN]
        assert body["scimType"] == "invalidFilter"
        scim_mocks.users.list_paginated.assert_not_called()

    @pytest.mark.parametrize(
        ("query", "expected_offset", "expected_limit"),
        [
            ({}, 0, 100),
            ({"startIndex": "3", "count": "2"}, 2, 2),
            ({"startIndex": "0", "count": "999"}, 0, 200),
            ({"startIndex": "-4", "count": "-5"}, 0, 0),
        ],
    )
    def test_pagination_offset_limit_math(
        self, client, scim_settings, scim_mocks, query, expected_offset, expected_limit
    ):
        scim_mocks.users.list_paginated.return_value = (0, [])
        response = client.get("/scim/v2/Users", headers=AUTH, query_string=query)
        assert response.status_code == 200
        scim_mocks.users.list_paginated.assert_called_once_with(None, expected_offset, expected_limit)

    def test_list_response_shape(self, client, scim_settings, scim_mocks):
        scim_mocks.users.list_paginated.return_value = (42, [_user_row()])
        response = client.get(
            "/scim/v2/Users", headers=AUTH, query_string={"startIndex": "5", "count": "1"}
        )
        assert response.status_code == 200
        assert response.content_type.startswith("application/scim+json")
        body = response.get_json()
        assert body["schemas"] == [LIST_RESPONSE_URN]
        assert body["totalResults"] == 42
        assert body["startIndex"] == 5
        assert body["itemsPerPage"] == 1
        resource = body["Resources"][0]
        assert resource["schemas"] == [USER_URN]
        assert resource["id"] == USER_PK
        assert resource["userName"] == "alice@example.com"
        assert resource["active"] is True
        assert resource["emails"] == [{"value": "alice@example.com", "primary": True}]
        assert resource["meta"]["resourceType"] == "User"
        assert resource["meta"]["location"] == f"/scim/v2/Users/{USER_PK}"


@pytest.mark.unit
class TestCreateUser:

    def test_missing_username_returns_400(self, client, scim_settings, scim_mocks):
        response = client.post("/scim/v2/Users", headers=AUTH, json={"active": True})
        assert response.status_code == 400
        assert response.get_json()["scimType"] == "invalidValue"
        scim_mocks.users.create.assert_not_called()

    def test_blank_username_returns_400(self, client, scim_settings, scim_mocks):
        response = client.post("/scim/v2/Users", headers=AUTH, json={"userName": "   "})
        assert response.status_code == 400
        assert response.get_json()["scimType"] == "invalidValue"

    def test_conflict_returns_409(self, client, scim_settings, scim_mocks):
        scim_mocks.users.create.return_value = None
        response = client.post("/scim/v2/Users", headers=AUTH, json={"userName": "alice@example.com"})
        assert response.status_code == 409
        body = response.get_json()
        assert body["schemas"] == [ERROR_URN]
        assert body["scimType"] == "uniqueness"
        scim_mocks.audit.insert.assert_not_called()

    def test_create_happy_path(self, client, scim_settings, scim_mocks):
        scim_mocks.users.create.return_value = _user_row()
        response = client.post("/scim/v2/Users", headers=AUTH, json={"userName": "alice@example.com"})
        assert response.status_code == 201
        assert response.content_type.startswith("application/scim+json")
        assert response.headers["Location"].endswith(f"/scim/v2/Users/{USER_PK}")
        scim_mocks.users.create.assert_called_once_with("alice@example.com", active=True)
        scim_mocks.audit.insert.assert_called_once_with(
            "alice@example.com", "scim_created", metadata={"via": "scim"}
        )
        body = response.get_json()
        assert body["id"] == USER_PK
        assert body["userName"] == "alice@example.com"
        assert body["active"] is True
        assert body["emails"] == [{"value": "alice@example.com", "primary": True}]
        assert body["meta"]["resourceType"] == "User"

    def test_create_honors_active_false(self, client, scim_settings, scim_mocks):
        scim_mocks.users.create.return_value = _user_row(active=False)
        response = client.post(
            "/scim/v2/Users", headers=AUTH, json={"userName": "alice@example.com", "active": False}
        )
        assert response.status_code == 201
        scim_mocks.users.create.assert_called_once_with("alice@example.com", active=False)
        assert response.get_json()["active"] is False

    def test_create_accepts_scim_content_type(self, client, scim_settings, scim_mocks):
        scim_mocks.users.create.return_value = _user_row()
        response = client.post(
            "/scim/v2/Users",
            headers=AUTH,
            data=json.dumps({"userName": "alice@example.com"}),
            content_type="application/scim+json",
        )
        assert response.status_code == 201

    def test_create_without_email_username_has_no_emails(self, client, scim_settings, scim_mocks):
        scim_mocks.users.create.return_value = _user_row(user_id="ldap-user-1")
        response = client.post("/scim/v2/Users", headers=AUTH, json={"userName": "ldap-user-1"})
        assert response.status_code == 201
        assert "emails" not in response.get_json()

    def test_audit_failure_does_not_fail_request(self, client, scim_settings, scim_mocks):
        scim_mocks.users.create.return_value = _user_row()
        scim_mocks.audit.insert.side_effect = RuntimeError("audit down")
        response = client.post("/scim/v2/Users", headers=AUTH, json={"userName": "alice@example.com"})
        assert response.status_code == 201


@pytest.mark.unit
class TestGetUser:

    def test_get_user_found(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = _user_row()
        response = client.get(f"/scim/v2/Users/{USER_PK}", headers=AUTH)
        assert response.status_code == 200
        scim_mocks.users.get_by_pk.assert_called_once_with(USER_PK)
        body = response.get_json()
        assert body["id"] == USER_PK
        assert body["userName"] == "alice@example.com"
        assert body["meta"]["location"] == f"/scim/v2/Users/{USER_PK}"

    def test_get_user_missing_returns_404(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = None
        response = client.get(f"/scim/v2/Users/{USER_PK}", headers=AUTH)
        assert response.status_code == 404
        assert response.get_json()["schemas"] == [ERROR_URN]

    def test_get_user_malformed_uuid_returns_404(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = None
        response = client.get("/scim/v2/Users/not-a-uuid", headers=AUTH)
        assert response.status_code == 404
        assert response.get_json()["status"] == "404"


@pytest.mark.unit
class TestReplaceUser:

    def test_username_change_rejected_as_mutability(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = _user_row()
        response = client.put(
            f"/scim/v2/Users/{USER_PK}",
            headers=AUTH,
            json={"userName": "bob@example.com", "active": True},
        )
        assert response.status_code == 400
        assert response.get_json()["scimType"] == "mutability"
        scim_mocks.users.set_active.assert_not_called()

    def test_put_active_true_reactivates(self, client, scim_settings, scim_mocks):
        row = _user_row(active=False)
        scim_mocks.users.get_by_pk.return_value = row
        scim_mocks.users.set_active.return_value = {**row, "active": True}
        response = client.put(
            f"/scim/v2/Users/{USER_PK}",
            headers=AUTH,
            json={"userName": "alice@example.com", "active": True},
        )
        assert response.status_code == 200
        assert response.get_json()["active"] is True
        scim_mocks.users.set_active.assert_called_once_with(USER_PK, True)
        # Reactivation does not touch the denylist (the deactivation watermark
        # already lets a fresh login through on a newer iat).
        scim_mocks.deny_user.assert_not_called()
        scim_mocks.audit.insert.assert_called_once_with(
            "alice@example.com", "scim_reactivated", metadata={"via": "scim"}
        )

    def test_put_active_false_triggers_deny(self, client, scim_settings, scim_mocks):
        row = _user_row(active=True)
        scim_mocks.users.get_by_pk.return_value = row
        scim_mocks.users.set_active.return_value = {**row, "active": False}
        response = client.put(
            f"/scim/v2/Users/{USER_PK}",
            headers=AUTH,
            json={"userName": "alice@example.com", "active": False},
        )
        assert response.status_code == 200
        assert response.get_json()["active"] is False
        scim_mocks.users.set_active.assert_called_once_with(USER_PK, False)
        scim_mocks.deny_user.assert_called_once_with("alice@example.com")
        scim_mocks.audit.insert.assert_called_once_with(
            "alice@example.com", "scim_deactivated", metadata={"via": "scim"}
        )

    def test_put_differently_cased_username_deprovisions(self, client, scim_settings, scim_mocks):
        # userName is case-insensitive: a PUT echoing the stored name under
        # different casing must deactivate, not 400 "userName is immutable".
        row = _user_row(active=True)  # user_id == "alice@example.com"
        scim_mocks.users.get_by_pk.return_value = row
        scim_mocks.users.set_active.return_value = {**row, "active": False}
        response = client.put(
            f"/scim/v2/Users/{USER_PK}",
            headers=AUTH,
            json={"userName": "Alice@Example.com", "active": False},
        )
        assert response.status_code == 200
        assert response.get_json()["active"] is False
        scim_mocks.users.set_active.assert_called_once_with(USER_PK, False)
        scim_mocks.deny_user.assert_called_once_with("alice@example.com")

    def test_put_unchanged_active_has_no_side_effects(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = _user_row(active=True)
        response = client.put(
            f"/scim/v2/Users/{USER_PK}",
            headers=AUTH,
            json={"userName": "alice@example.com", "active": True},
        )
        assert response.status_code == 200
        scim_mocks.users.set_active.assert_not_called()
        scim_mocks.deny_user.assert_not_called()
        scim_mocks.audit.insert.assert_not_called()

    def test_put_missing_user_returns_404(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = None
        response = client.put(
            f"/scim/v2/Users/{USER_PK}", headers=AUTH, json={"userName": "x", "active": True}
        )
        assert response.status_code == 404


@pytest.mark.unit
class TestPatchUser:

    def _patch(self, client, operations):
        return client.patch(
            f"/scim/v2/Users/{USER_PK}",
            headers=AUTH,
            json={"schemas": [PATCH_OP_URN], "Operations": operations},
        )

    def _expect_deactivated(self, scim_mocks, response):
        assert response.status_code == 200
        assert response.get_json()["active"] is False
        scim_mocks.users.set_active.assert_called_once_with(USER_PK, False)
        scim_mocks.deny_user.assert_called_once_with("alice@example.com")
        scim_mocks.audit.insert.assert_called_once_with(
            "alice@example.com", "scim_deactivated", metadata={"via": "scim"}
        )

    def test_replace_with_path_deactivates(self, client, scim_settings, scim_mocks):
        row = _user_row(active=True)
        scim_mocks.users.get_by_pk.return_value = row
        scim_mocks.users.set_active.return_value = {**row, "active": False}
        response = self._patch(client, [{"op": "replace", "path": "active", "value": False}])
        self._expect_deactivated(scim_mocks, response)

    def test_replace_without_path_object_value_deactivates(self, client, scim_settings, scim_mocks):
        row = _user_row(active=True)
        scim_mocks.users.get_by_pk.return_value = row
        scim_mocks.users.set_active.return_value = {**row, "active": False}
        response = self._patch(client, [{"op": "replace", "value": {"active": False}}])
        self._expect_deactivated(scim_mocks, response)

    def test_replace_with_string_false_deactivates(self, client, scim_settings, scim_mocks):
        row = _user_row(active=True)
        scim_mocks.users.get_by_pk.return_value = row
        scim_mocks.users.set_active.return_value = {**row, "active": False}
        response = self._patch(client, [{"op": "Replace", "path": "active", "value": "False"}])
        self._expect_deactivated(scim_mocks, response)

    def test_replace_with_string_true_reactivates(self, client, scim_settings, scim_mocks):
        row = _user_row(active=False)
        scim_mocks.users.get_by_pk.return_value = row
        scim_mocks.users.set_active.return_value = {**row, "active": True}
        response = self._patch(client, [{"op": "replace", "path": "active", "value": "true"}])
        assert response.status_code == 200
        assert response.get_json()["active"] is True
        scim_mocks.users.set_active.assert_called_once_with(USER_PK, True)
        scim_mocks.deny_user.assert_not_called()
        scim_mocks.audit.insert.assert_called_once_with(
            "alice@example.com", "scim_reactivated", metadata={"via": "scim"}
        )

    def test_bogus_path_rejected(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = _user_row()
        response = self._patch(client, [{"op": "replace", "path": "displayName", "value": "X"}])
        assert response.status_code == 400
        assert response.get_json()["scimType"] == "invalidPath"
        scim_mocks.users.set_active.assert_not_called()

    def test_bogus_op_rejected(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = _user_row()
        response = self._patch(client, [{"op": "add", "path": "active", "value": True}])
        assert response.status_code == 400
        assert response.get_json()["scimType"] == "invalidPath"

    def test_invalid_active_value_rejected(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = _user_row()
        response = self._patch(client, [{"op": "replace", "path": "active", "value": "maybe"}])
        assert response.status_code == 400
        assert response.get_json()["scimType"] == "invalidValue"

    def test_unchanged_active_is_noop(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = _user_row(active=True)
        response = self._patch(client, [{"op": "replace", "path": "active", "value": True}])
        assert response.status_code == 200
        scim_mocks.users.set_active.assert_not_called()
        scim_mocks.deny_user.assert_not_called()
        scim_mocks.audit.insert.assert_not_called()

    def test_no_path_value_without_active_is_noop(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = _user_row(active=True)
        response = self._patch(client, [{"op": "replace", "value": {"displayName": "X"}}])
        assert response.status_code == 200
        scim_mocks.users.set_active.assert_not_called()

    def test_missing_operations_rejected(self, client, scim_settings, scim_mocks):
        response = client.patch(
            f"/scim/v2/Users/{USER_PK}", headers=AUTH, json={"schemas": [PATCH_OP_URN]}
        )
        assert response.status_code == 400

    def test_patch_missing_user_returns_404(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = None
        response = self._patch(client, [{"op": "replace", "path": "active", "value": False}])
        assert response.status_code == 404


@pytest.mark.unit
class TestDeleteUser:

    def test_delete_deactivates_and_returns_204(self, client, scim_settings, scim_mocks):
        row = _user_row(active=True)
        scim_mocks.users.get_by_pk.return_value = row
        scim_mocks.users.set_active.return_value = {**row, "active": False}
        response = client.delete(f"/scim/v2/Users/{USER_PK}", headers=AUTH)
        assert response.status_code == 204
        assert response.data == b""
        scim_mocks.users.set_active.assert_called_once_with(USER_PK, False)
        scim_mocks.deny_user.assert_called_once_with("alice@example.com")
        scim_mocks.audit.insert.assert_called_once_with(
            "alice@example.com", "scim_deactivated", metadata={"via": "scim"}
        )

    def test_delete_already_inactive_has_no_side_effects(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = _user_row(active=False)
        response = client.delete(f"/scim/v2/Users/{USER_PK}", headers=AUTH)
        assert response.status_code == 204
        scim_mocks.users.set_active.assert_not_called()
        scim_mocks.deny_user.assert_not_called()

    def test_delete_missing_user_returns_404(self, client, scim_settings, scim_mocks):
        scim_mocks.users.get_by_pk.return_value = None
        response = client.delete(f"/scim/v2/Users/{USER_PK}", headers=AUTH)
        assert response.status_code == 404

    def test_deactivation_revocation_failure_returns_503(self, client, scim_settings, scim_mocks):
        # Redis down: deny_user returns False, so the deactivation rolls back and
        # the IdP gets a 503 to retry instead of a false deprovision success.
        row = _user_row(active=True)
        scim_mocks.users.get_by_pk.return_value = row
        scim_mocks.users.set_active.return_value = {**row, "active": False}
        scim_mocks.deny_user.return_value = False
        response = client.delete(f"/scim/v2/Users/{USER_PK}", headers=AUTH)
        assert response.status_code == 503


@pytest.mark.unit
class TestGroups:

    def test_get_groups_returns_empty_list(self, client, scim_settings, scim_mocks):
        response = client.get("/scim/v2/Groups", headers=AUTH)
        assert response.status_code == 200
        body = response.get_json()
        assert body["schemas"] == [LIST_RESPONSE_URN]
        assert body["totalResults"] == 0
        assert body["Resources"] == []

    def test_post_groups_not_implemented(self, client, scim_settings, scim_mocks):
        response = client.post("/scim/v2/Groups", headers=AUTH, json={"displayName": "Team"})
        assert response.status_code == 501
        body = response.get_json()
        assert body["schemas"] == [ERROR_URN]
        assert body["detail"] == "Group provisioning is not supported"

    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_group_mutations_not_implemented(self, client, scim_settings, scim_mocks, method):
        response = getattr(client, method)("/scim/v2/Groups/some-group", headers=AUTH)
        assert response.status_code == 501
        assert response.get_json()["detail"] == "Group provisioning is not supported"
