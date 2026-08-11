"""Integration tests for the SCIM 2.0 endpoints against a live Postgres.

These tests drive the real Flask app through its test client and verify
row state in the database configured by ``POSTGRES_URI``. Redis is not
required — the denylist functions are stubbed. They are skipped by the
default ``pytest`` run (``--ignore=tests/integration`` in ``pytest.ini``)
and marked ``@pytest.mark.integration``. Run them locally with::

    .venv/bin/python -m pytest tests/integration/test_scim.py -q --no-cov \\
        -p no:cacheprovider --override-ini "addopts="
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text

from application.core.settings import settings
from application.storage.db.repositories.auth_events import AuthEventsRepository
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.session import db_readonly, db_session

SCIM_TOKEN = "scim-test-token"
AUTH = {"Authorization": f"Bearer {SCIM_TOKEN}"}

ERROR_URN = "urn:ietf:params:scim:api:messages:2.0:Error"
PATCH_OP_URN = "urn:ietf:params:scim:api:messages:2.0:PatchOp"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not settings.POSTGRES_URI,
        reason="POSTGRES_URI not set — skipping SCIM integration tests",
    ),
]


@pytest.fixture(scope="module")
def app():
    """Real Flask app; /scim/ paths bypass JWT auth so no handle_auth patching is needed."""
    from application.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def scim_env(monkeypatch):
    """Enable SCIM on the settings singleton and stub the Redis denylist."""
    monkeypatch.setattr(settings, "SCIM_ENABLED", True)
    monkeypatch.setattr(settings, "SCIM_TOKEN", SCIM_TOKEN)
    with patch("application.api.scim.routes.deny_user") as deny_user_mock:
        yield SimpleNamespace(deny_user=deny_user_mock)


@pytest.fixture
def scim_user_name():
    """Unique per-run userName; deletes the user + audit rows afterwards."""
    name = f"scim-it-{uuid.uuid4().hex[:10]}@example.com"
    yield name
    with db_session() as conn:
        conn.execute(text("DELETE FROM auth_events WHERE user_id = :user_id"), {"user_id": name})
        conn.execute(text("DELETE FROM users WHERE user_id = :user_id"), {"user_id": name})


def _fetch_user(user_name: str):
    with db_readonly() as conn:
        return UsersRepository(conn).get(user_name)


def _fetch_events(user_name: str):
    with db_readonly() as conn:
        return AuthEventsRepository(conn).list_recent(user_name)


@pytest.mark.integration
class TestScimLifecycle:

    def test_full_user_lifecycle(self, client, scim_env, scim_user_name):
        # Create
        response = client.post("/scim/v2/Users", headers=AUTH, json={"userName": scim_user_name})
        assert response.status_code == 201, response.get_data(as_text=True)
        created = response.get_json()
        pk = created["id"]
        assert created["userName"] == scim_user_name
        assert created["active"] is True
        assert created["emails"] == [{"value": scim_user_name, "primary": True}]
        assert response.headers["Location"].endswith(f"/scim/v2/Users/{pk}")

        row = _fetch_user(scim_user_name)
        assert row is not None
        assert row["active"] is True
        assert [event["event"] for event in _fetch_events(scim_user_name)] == ["scim_created"]

        # GET by id
        response = client.get(f"/scim/v2/Users/{pk}", headers=AUTH)
        assert response.status_code == 200
        assert response.get_json()["id"] == pk

        # List with exact userName filter
        response = client.get(
            "/scim/v2/Users",
            headers=AUTH,
            query_string={"filter": f'userName eq "{scim_user_name}"'},
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["totalResults"] == 1
        assert body["itemsPerPage"] == 1
        assert body["Resources"][0]["id"] == pk

        # Deactivate via PATCH (Okta no-path form with string value)
        response = client.patch(
            f"/scim/v2/Users/{pk}",
            headers=AUTH,
            json={
                "schemas": [PATCH_OP_URN],
                "Operations": [{"op": "replace", "value": {"active": "False"}}],
            },
        )
        assert response.status_code == 200
        assert response.get_json()["active"] is False
        assert _fetch_user(scim_user_name)["active"] is False
        deactivations = [e for e in _fetch_events(scim_user_name) if e["event"] == "scim_deactivated"]
        assert len(deactivations) == 1
        assert deactivations[0]["metadata"] == {"via": "scim"}
        scim_env.deny_user.assert_called_once_with(scim_user_name)

        # Reactivate via PUT (full replace; only active is honored)
        response = client.put(
            f"/scim/v2/Users/{pk}",
            headers=AUTH,
            json={"userName": scim_user_name, "active": True},
        )
        assert response.status_code == 200
        assert response.get_json()["active"] is True
        assert _fetch_user(scim_user_name)["active"] is True
        # Reactivation no longer clears the denylist (watermark model).
        scim_env.deny_user.assert_called_once_with(scim_user_name)
        assert any(e["event"] == "scim_reactivated" for e in _fetch_events(scim_user_name))

        # Soft delete deactivates again
        response = client.delete(f"/scim/v2/Users/{pk}", headers=AUTH)
        assert response.status_code == 204
        assert response.data == b""
        assert _fetch_user(scim_user_name)["active"] is False
        assert scim_env.deny_user.call_count == 2

        # Duplicate create conflicts (row still exists after soft delete)
        response = client.post("/scim/v2/Users", headers=AUTH, json={"userName": scim_user_name})
        assert response.status_code == 409
        body = response.get_json()
        assert body["schemas"] == [ERROR_URN]
        assert body["scimType"] == "uniqueness"


@pytest.mark.integration
class TestScimAccess:

    def test_wrong_bearer_token_rejected(self, client, scim_env):
        response = client.get("/scim/v2/Users", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401
        assert response.get_json()["schemas"] == [ERROR_URN]

    def test_get_user_with_malformed_uuid_returns_404(self, client, scim_env):
        response = client.get("/scim/v2/Users/not-a-uuid", headers=AUTH)
        assert response.status_code == 404
        assert response.get_json()["status"] == "404"

    def test_service_provider_config_served(self, client, scim_env):
        response = client.get("/scim/v2/ServiceProviderConfig", headers=AUTH)
        assert response.status_code == 200
        assert response.content_type.startswith("application/scim+json")
        assert response.get_json()["patch"] == {"supported": True}
