"""Endpoint tests for the merged admin activity feed, its filters and export.

The repository's SQL is covered by
tests/storage/db/repositories/test_activity.py; these pin the route wiring,
the @admin_required boundary, query-argument parsing and the export framing.
"""

from __future__ import annotations

import csv
import io
import json
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@contextmanager
def _fake_conn():
    yield Mock()


@contextmanager
def _admin(repo: Mock):
    with ExitStack() as stack:
        stack.enter_context(
            patch("docsgpt.app.handle_auth", return_value={"sub": "admin1"})
        )
        stack.enter_context(
            patch("docsgpt.app.resolve_roles", return_value=["admin", "user"])
        )
        stack.enter_context(patch("docsgpt.api.admin.activity.db_readonly", _fake_conn))
        stack.enter_context(
            patch(
                "docsgpt.api.admin.activity.ActivityRepository", return_value=repo
            )
        )
        yield


def _row(**overrides):
    base = {
        "feed": "auth",
        "id": "1",
        "event": "oidc_login",
        "category": "identity",
        "actor_id": "u1",
        "target_id": "u1",
        "ip": "203.0.113.1",
        "user_agent": "curl/8",
        "outcome": None,
        "detail": {"via": "oidc"},
        "created_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def _repo(rows=None, total=None):
    repo = Mock()
    rows = [_row()] if rows is None else rows
    repo.list.return_value = rows
    repo.count.return_value = len(rows) if total is None else total
    repo.iter_all.return_value = iter(rows)
    repo.event_names.return_value = [
        {"event": "oidc_login", "category": "identity"},
    ]
    return repo


@pytest.mark.unit
class TestGuard:
    def test_non_admin_forbidden(self, client):
        with patch("docsgpt.app.handle_auth", return_value={"sub": "u"}), patch(
            "docsgpt.app.resolve_roles", return_value=["user"]
        ):
            assert client.get("/api/admin/activity").status_code == 403
            assert client.get("/api/admin/activity/export").status_code == 403
            assert client.get("/api/admin/activity/events").status_code == 403

    def test_unauthenticated(self, client):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.get("/api/admin/activity").status_code == 401


@pytest.mark.unit
class TestFeed:
    def test_returns_rows_with_iso_timestamps(self, client):
        repo = _repo()
        with _admin(repo):
            body = json.loads(client.get("/api/admin/activity").data)
        assert body["success"] is True
        assert body["activity"][0]["created_at"] == "2026-01-02T03:04:05+00:00"
        assert body["total"] == 1
        assert body["has_more"] is False

    def test_has_more_when_the_page_is_short_of_the_total(self, client):
        repo = _repo(total=500)
        with _admin(repo):
            body = json.loads(client.get("/api/admin/activity").data)
        assert body["has_more"] is True

    def test_filters_reach_the_repository(self, client):
        repo = _repo()
        with _admin(repo):
            client.get(
                "/api/admin/activity?feed=auth,device&category=data"
                "&event=source.deleted&actor_id=admin1&user_id=u2"
                "&since=2026-01-01T00:00:00Z&until=2026-02-01&search=handbook"
            )
        kwargs = repo.list.call_args.kwargs
        assert kwargs["feeds"] == ["auth", "device"]
        assert kwargs["categories"] == ["data"]
        assert kwargs["events"] == ["source.deleted"]
        assert kwargs["actor_id"] == "admin1"
        assert kwargs["user_id"] == "u2"
        assert kwargs["since"] == datetime(2026, 1, 1, tzinfo=timezone.utc)
        # A naive bound is read as UTC.
        assert kwargs["until"] == datetime(2026, 2, 1, tzinfo=timezone.utc)
        assert kwargs["search"] == "handbook"

    def test_unknown_facet_values_are_ignored_not_rejected(self, client):
        repo = _repo()
        with _admin(repo):
            resp = client.get("/api/admin/activity?feed=bogus&category=bogus")
        assert resp.status_code == 200
        kwargs = repo.list.call_args.kwargs
        assert kwargs["feeds"] is None and kwargs["categories"] is None

    def test_unparseable_time_is_ignored(self, client):
        repo = _repo()
        with _admin(repo):
            assert client.get("/api/admin/activity?since=nonsense").status_code == 200
        assert repo.list.call_args.kwargs["since"] is None

    def test_repeated_params_accumulate(self, client):
        repo = _repo()
        with _admin(repo):
            client.get("/api/admin/activity?category=data&category=access")
        assert repo.list.call_args.kwargs["categories"] == ["data", "access"]

    def test_search_is_length_capped(self, client):
        repo = _repo()
        with _admin(repo):
            client.get("/api/admin/activity?search=" + "x" * 5000)
        assert len(repo.list.call_args.kwargs["search"]) == 200


@pytest.mark.unit
class TestCatalogue:
    def test_lists_events_categories_and_feeds(self, client):
        repo = _repo()
        with _admin(repo):
            body = json.loads(client.get("/api/admin/activity/events").data)
        assert body["events"] == [{"event": "oidc_login", "category": "identity"}]
        assert "identity" in body["categories"]
        assert body["feeds"] == ["auth", "device", "guardrail"]


@pytest.mark.unit
class TestExport:
    """The export streams lazily, so every test consumes it inside the patch."""

    def test_csv_has_a_header_and_one_row_per_event(self, client):
        repo = _repo(rows=[_row(), _row(id="2", event="pat_created")])
        with _admin(repo):
            resp = client.get("/api/admin/activity/export?format=csv")
            body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        assert "attachment; filename=" in resp.headers["Content-Disposition"]
        rows = list(csv.DictReader(io.StringIO(body)))
        assert [row["event"] for row in rows] == ["oidc_login", "pat_created"]
        # ``detail`` is a JSON object, encoded into the cell.
        assert json.loads(rows[0]["detail"]) == {"via": "oidc"}

    def test_ndjson_emits_one_object_per_line(self, client):
        repo = _repo(rows=[_row(), _row(id="2")])
        with _admin(repo):
            resp = client.get("/api/admin/activity/export?format=ndjson")
            body = resp.get_data(as_text=True)
        assert resp.mimetype == "application/x-ndjson"
        lines = body.strip().split("\n")
        assert [json.loads(line)["id"] for line in lines] == ["1", "2"]

    def test_empty_csv_export_still_has_its_header(self, client):
        with _admin(_repo(rows=[])):
            body = client.get("/api/admin/activity/export").get_data(as_text=True)
        assert body.strip().startswith("feed,id,event,category")

    def test_rejects_an_unknown_format(self, client):
        with _admin(_repo()):
            assert (
                client.get("/api/admin/activity/export?format=xlsx").status_code == 400
            )

    def test_export_applies_the_same_filters(self, client):
        repo = _repo()
        with _admin(repo):
            client.get(
                "/api/admin/activity/export?category=data&search=q"
            ).get_data()
        kwargs = repo.iter_all.call_args.kwargs
        assert kwargs["categories"] == ["data"]
        assert kwargs["search"] == "q"

    def test_row_cap_is_bounded_and_reported(self, client):
        repo = _repo()
        with _admin(repo):
            resp = client.get("/api/admin/activity/export?max_rows=10")
            resp.get_data()
        assert resp.headers["X-Export-Max-Rows"] == "10"
        assert repo.iter_all.call_args.kwargs["max_rows"] == 10

    def test_an_absurd_cap_clamps_to_the_ceiling(self, client):
        repo = _repo()
        with _admin(repo):
            resp = client.get("/api/admin/activity/export?max_rows=999999999")
            resp.get_data()
        assert resp.headers["X-Export-Max-Rows"] == "100000"

    def test_export_is_not_cached(self, client):
        with _admin(_repo()):
            resp = client.get("/api/admin/activity/export")
            resp.get_data()
        assert resp.headers["Cache-Control"] == "no-store"
