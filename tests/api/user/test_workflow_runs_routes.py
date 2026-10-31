"""Workflow run routes: list, read and download what a run produced.

The Flask routes are driven through the app's test client, so the PAT rule
table runs in front of them; the download is the native-async Starlette
route, driven through Starlette's ``TestClient``.
"""

from __future__ import annotations

import io
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text
from starlette.applications import Starlette
from starlette.testclient import TestClient

from docsgpt.api.pat.tokens import expand_scopes
from docsgpt.api.user.workflow_runs import routes as run_routes
from docsgpt.api.user.workflow_runs.download import run_artifact_download_routes
from docsgpt.storage.db.repositories.artifacts import RUN_INPUT_SOURCE, ArtifactsRepository
from docsgpt.storage.db.repositories.workflow_runs import WorkflowRunsRepository

OWNER = "runs-owner"
OTHER = "runs-other"
AGENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
AGENT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SOURCE_A = "cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.fixture(scope="module")
def flask_app():
    from docsgpt.app import app

    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def db(pg_conn, monkeypatch):
    @contextmanager
    def _use_conn():
        yield pg_conn

    monkeypatch.setattr("docsgpt.api.user.workflow_runs.routes.db_readonly", _use_conn)
    monkeypatch.setattr("docsgpt.api.user.workflow_runs.download.db_readonly", _use_conn)
    return pg_conn


def _pat(scopes, resource_filter=None, sub=OWNER):
    return {
        "sub": sub,
        "auth_method": "pat",
        "pat_id": "t1",
        "pat_name": "ci",
        "scopes": sorted(expand_scopes(scopes)),
        "resource_filter": resource_filter or {},
    }


def _get(client, path, claims, **kwargs):
    with patch("docsgpt.app.handle_auth", return_value=claims):
        return client.get(path, **kwargs)


def _body(response):
    return json.loads(response.data)


def _workflow(conn, user=OWNER):
    res = conn.execute(text("INSERT INTO workflows (user_id, name) VALUES (:u, 'wf') RETURNING id"), {"u": user})
    return str(res.fetchone()[0])


def _run(conn, *, user=OWNER, agent=AGENT_A, status="completed", result=None, steps=None, started_at=None):
    inputs = {"query": "Extract the terms"}
    if agent:
        inputs["agent_id"] = agent
    started_at = started_at or datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc)
    row = WorkflowRunsRepository(conn).create(
        _workflow(conn, user),
        user,
        status,
        inputs=inputs,
        result=result if result is not None else {"query": "Extract the terms", "terms": {"days": 30}},
        steps=steps if steps is not None else [],
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=12),
    )
    return str(row["id"])


def _artifact(conn, run_id, *, user=OWNER, filename="report.pdf", source=None):
    produced_by = {"source": source} if source else {"node_id": "code_1", "node_type": "code"}
    row = ArtifactsRepository(conn).create_artifact(
        user,
        "file",
        workflow_run_id=run_id,
        title=filename,
        mime_type="application/pdf",
        filename=filename,
        storage_path=f"inputs/{user}/artifacts/{filename}",
        size=7,
        produced_by=produced_by,
    )
    return str(row["id"])


_STEPS = [
    {
        "node_id": "start",
        "node_type": "start",
        "status": "completed",
        "started_at": "2026-10-29T10:00:00+00:00",
        "completed_at": "2026-10-29T10:00:00+00:00",
        "duration_ms": 0,
        "error": None,
        "state_delta": {"query": "Extract the terms"},
        "tool_calls": [],
    },
    {
        "node_id": "extract",
        "node_type": "agent",
        "status": "failed",
        "started_at": "2026-10-29T10:00:00+00:00",
        "completed_at": "2026-10-29T10:00:12+00:00",
        "duration_ms": 12000,
        "error": "Extract: the selected documents take about 500,000 tokens",
        "state_delta": {"secret": "x"},
        "tool_calls": [{"tool_name": "read_document", "action_name": "read", "status": "completed"}],
    },
]


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestList:
    def test_lists_the_callers_runs(self, client, db):
        mine = _run(db)
        _run(db, user=OTHER)

        response = _get(client, "/api/workflow_runs", _pat(["runs:read"]))

        assert response.status_code == 200
        runs = _body(response)["runs"]
        assert [r["id"] for r in runs] == [mine]
        assert runs[0]["agent_id"] == AGENT_A
        assert runs[0]["status"] == "completed"
        assert runs[0]["query"] == "Extract the terms"
        assert runs[0]["duration_ms"] == 12000
        assert "state" not in runs[0] and "steps" not in runs[0]

    def test_filters(self, client, db):
        early = _run(db, started_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
        failed = _run(db, agent=AGENT_B, status="failed")
        late = _run(db, started_at=datetime(2026, 10, 30, tzinfo=timezone.utc))
        claims = _pat(["runs:read"])

        by_agent = _body(_get(client, f"/api/workflow_runs?agent_id={AGENT_B}", claims))["runs"]
        by_status = _body(_get(client, "/api/workflow_runs?status=failed", claims))["runs"]
        since = _body(_get(client, "/api/workflow_runs?since=2026-10-15T00:00:00Z", claims))["runs"]
        limited = _body(_get(client, "/api/workflow_runs?limit=1", claims))["runs"]

        assert [r["id"] for r in by_agent] == [failed]
        assert [r["id"] for r in by_status] == [failed]
        assert {r["id"] for r in since} == {failed, late}
        assert [r["id"] for r in limited] == [late]
        assert early not in {r["id"] for r in since}

    @pytest.mark.parametrize(
        "query",
        ["status=done", "limit=0", "limit=101", "limit=x", "since=yesterday", "agent_id=not-a-uuid"],
    )
    def test_invalid_filters_are_400(self, client, db, query):
        assert _get(client, f"/api/workflow_runs?{query}", _pat(["runs:read"])).status_code == 400

    def test_needs_the_runs_scope(self, client, db):
        response = _get(client, "/api/workflow_runs", _pat(["agents:read", "chat:run"]))
        assert response.status_code == 403
        assert _body(response)["required_scope"] == "runs:read"

    def test_an_agent_restricted_token_sees_only_its_agents(self, client, db):
        a = _run(db, agent=AGENT_A)
        _run(db, agent=AGENT_B)
        _run(db, agent=None)
        claims = _pat(["runs:read"], {"agents": [AGENT_A]})

        runs = _body(_get(client, "/api/workflow_runs", claims))["runs"]
        other = _get(client, f"/api/workflow_runs?agent_id={AGENT_B}", claims)

        assert [r["id"] for r in runs] == [a]
        assert other.status_code == 403
        assert _body(other)["error"] == "resource_not_allowed"

    def test_a_token_restricted_on_another_family_is_kept_out(self, client, db):
        claims = _pat(["runs:read", "sources:read"], {"sources": [SOURCE_A]})
        assert _get(client, "/api/workflow_runs", claims).status_code == 403

    def test_a_session_caller_lists_its_runs(self, client, db):
        mine = _run(db)
        assert [r["id"] for r in _body(_get(client, "/api/workflow_runs", {"sub": OWNER}))["runs"]] == [mine]


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGet:
    def test_returns_the_run_without_extras_by_default(self, client, db):
        run_id = _run(db, status="failed", steps=_STEPS)

        response = _get(client, f"/api/workflow_runs/{run_id}", _pat(["runs:read"]))

        assert response.status_code == 200
        run = _body(response)["run"]
        assert run["id"] == run_id
        assert run["agent_id"] == AGENT_A
        assert run["status"] == "failed"
        assert run["started_at"].startswith("2026-10-29T10:00:00")
        assert run["duration_ms"] == 12000
        assert run["error"] == "Extract: the selected documents take about 500,000 tokens"
        assert "steps" not in run and "state" not in run and "artifacts" not in run

    def test_include_steps_state_and_artifacts(self, client, db):
        run_id = _run(db, steps=_STEPS)
        produced = _artifact(db, run_id)
        _artifact(db, run_id, filename="upload.docx", source=RUN_INPUT_SOURCE)

        response = _get(
            client, f"/api/workflow_runs/{run_id}?include=steps,state,artifacts", _pat(["runs:read"])
        )

        run = _body(response)["run"]
        assert [s["node_id"] for s in run["steps"]] == ["start", "extract"]
        step = run["steps"][1]
        assert step["status"] == "failed"
        assert step["duration_ms"] == 12000
        assert step["error"].startswith("Extract:")
        assert step["tool_calls"][0]["tool_name"] == "read_document"
        assert "state_delta" not in step
        assert run["state"] == {"query": "Extract the terms", "terms": {"days": 30}}
        assert run["state_truncated"] == []
        assert [a["id"] for a in run["artifacts"]] == [produced]
        assert run["artifacts"][0]["filename"] == "report.pdf"
        assert run["artifacts"][0]["download_url"] == f"/api/workflow_runs/{run_id}/artifacts/{produced}/download"

    def test_large_state_values_are_listed_and_fetched_one_at_a_time(self, client, db, monkeypatch):
        monkeypatch.setattr(run_routes, "STATE_VALUE_MAX_BYTES", 64)
        run_id = _run(db, result={"small": "ok", "big": "x" * 500})
        claims = _pat(["runs:read"])

        run = _body(_get(client, f"/api/workflow_runs/{run_id}?include=state", claims))["run"]
        one = _get(client, f"/api/workflow_runs/{run_id}?state_key=big", claims)
        missing = _get(client, f"/api/workflow_runs/{run_id}?state_key=nope", claims)

        assert run["state"] == {"small": "ok"}
        assert run["state_truncated"] == [{"key": "big", "bytes": 502}]
        assert _body(one)["run"]["state"] == {"big": "x" * 500}
        assert missing.status_code == 404

    def test_loop_items_are_listed_with_their_steps(self, client, db):
        loop_step = {
            "node_id": "loop",
            "node_type": "loop",
            "status": "completed",
            "started_at": "2026-10-29T10:00:00+00:00",
            "duration_ms": 5,
            "state_delta": {},
            "tool_calls": [],
            "items": [
                {
                    "item_index": 0,
                    "status": "completed",
                    "duration_ms": 3,
                    "error": None,
                    "steps": [dict(_STEPS[0], node_id="body")],
                }
            ],
        }
        run_id = _run(db, steps=[loop_step])

        run = _body(_get(client, f"/api/workflow_runs/{run_id}?include=steps", _pat(["runs:read"])))["run"]

        item = run["steps"][0]["items"][0]
        assert item["item_index"] == 0
        assert [s["node_id"] for s in item["steps"]] == ["body"]
        assert "state_delta" not in item["steps"][0]

    def test_unknown_include_is_400(self, client, db):
        run_id = _run(db)
        assert _get(client, f"/api/workflow_runs/{run_id}?include=secrets", _pat(["runs:read"])).status_code == 400

    @pytest.mark.parametrize("run_id", ["not-a-uuid", "11111111-1111-1111-1111-111111111111"])
    def test_unknown_runs_are_404(self, client, db, run_id):
        assert _get(client, f"/api/workflow_runs/{run_id}", _pat(["runs:read"])).status_code == 404

    def test_another_users_run_is_404(self, client, db):
        run_id = _run(db, user=OTHER)
        assert _get(client, f"/api/workflow_runs/{run_id}", _pat(["runs:read"])).status_code == 404

    def test_an_agent_restricted_token_cannot_see_another_agents_run(self, client, db):
        a, b, none = _run(db, agent=AGENT_A), _run(db, agent=AGENT_B), _run(db, agent=None)
        claims = _pat(["runs:read"], {"agents": [AGENT_A]})

        assert _get(client, f"/api/workflow_runs/{a}", claims).status_code == 200
        assert _get(client, f"/api/workflow_runs/{b}", claims).status_code == 404
        assert _get(client, f"/api/workflow_runs/{none}", claims).status_code == 404

    def test_needs_the_runs_scope(self, client, db):
        run_id = _run(db)
        assert _get(client, f"/api/workflow_runs/{run_id}", _pat(["artifacts:read"])).status_code == 403


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


class _Storage:
    def get_file(self, path):
        return io.BytesIO(b"PDFDATA")

    def generate_presigned_url(self, path, expires_in=300):
        return f"https://signed.example/{path}"


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setattr(
        "docsgpt.storage.storage_creator.StorageCreator.get_storage", staticmethod(lambda: _Storage())
    )


def _download(run_id, artifact_id, claims, query=None):
    client = TestClient(Starlette(routes=run_artifact_download_routes))
    with patch("docsgpt.api.asgi_auth.handle_auth", return_value=claims):
        return client.get(
            f"/api/workflow_runs/{run_id}/artifacts/{artifact_id}/download",
            params=query or {},
            follow_redirects=False,
        )


@pytest.mark.unit
class TestDownload:
    def test_downloads_a_produced_file(self, db, storage):
        run_id = _run(db)
        artifact_id = _artifact(db, run_id)

        response = _download(run_id, artifact_id, _pat(["artifacts:read"]))

        assert response.status_code == 200
        assert response.content == b"PDFDATA"
        assert response.headers["content-type"].startswith("application/pdf")
        assert 'filename="report.pdf"' in response.headers["content-disposition"]

    def test_without_the_scope_it_is_403(self, db, storage):
        run_id = _run(db)
        artifact_id = _artifact(db, run_id)

        response = _download(run_id, artifact_id, _pat(["runs:read"]))

        assert response.status_code == 403
        assert response.json()["error"] == "insufficient_scope"

    def test_an_agent_restricted_token_downloads_only_its_agents_files(self, db, storage):
        a = _run(db, agent=AGENT_A)
        b = _run(db, agent=AGENT_B)
        a_file, b_file = _artifact(db, a), _artifact(db, b)
        claims = _pat(["artifacts:read"], {"agents": [AGENT_A]})

        assert _download(a, a_file, claims).status_code == 200
        assert _download(b, b_file, claims).status_code == 404

    def test_a_token_restricted_on_another_family_is_kept_out(self, db, storage):
        run_id = _run(db)
        artifact_id = _artifact(db, run_id)
        claims = _pat(["artifacts:read", "sources:read"], {"sources": [SOURCE_A]})

        response = _download(run_id, artifact_id, claims)

        assert response.status_code == 403
        assert response.json()["error"] == "resource_not_allowed"

    def test_a_file_of_another_run_or_user_is_404(self, db, storage):
        mine, other_run = _run(db), _run(db)
        theirs = _run(db, user=OTHER)
        other_file = _artifact(db, other_run)
        their_file = _artifact(db, theirs, user=OTHER)
        claims = _pat(["artifacts:read"])

        assert _download(mine, other_file, claims).status_code == 404
        assert _download(theirs, their_file, claims).status_code == 404

    def test_the_runs_input_documents_are_not_served(self, db, storage):
        run_id = _run(db)
        upload = _artifact(db, run_id, filename="upload.docx", source=RUN_INPUT_SOURCE)
        assert _download(run_id, upload, _pat(["artifacts:read"])).status_code == 404

    def test_a_session_caller_downloads_its_runs_files(self, db, storage):
        run_id = _run(db)
        artifact_id = _artifact(db, run_id)
        assert _download(run_id, artifact_id, {"sub": OWNER}).status_code == 200

    def test_anonymous_is_401(self, db, storage):
        run_id = _run(db)
        artifact_id = _artifact(db, run_id)
        assert _download(run_id, artifact_id, None).status_code == 401

    @pytest.mark.parametrize("version", ["2", "x"])
    def test_a_missing_or_malformed_version(self, db, storage, version):
        run_id = _run(db)
        artifact_id = _artifact(db, run_id)
        response = _download(run_id, artifact_id, _pat(["artifacts:read"]), {"version": version})
        assert response.status_code == (404 if version == "2" else 400)


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEdges:
    def test_a_reaped_run_reports_the_reapers_note(self, client, db):
        run_id = _run(db, status="failed", result={"error": "Run did not complete.", "failed_reason": "stale_reaper"})
        run = _body(_get(client, f"/api/workflow_runs/{run_id}", _pat(["runs:read"])))["run"]
        assert run["error"] == "Run did not complete."

    def test_a_failed_run_without_a_reason_has_no_error(self, client, db):
        run_id = _run(db, status="failed", result={"query": "q"})
        assert _body(_get(client, f"/api/workflow_runs/{run_id}", _pat(["runs:read"])))["run"]["error"] is None

    def test_a_running_run_has_no_duration_yet(self, client, db):
        wf = _workflow(db)
        run_id = str(WorkflowRunsRepository(db).create(wf, OWNER, "running", inputs={"agent_id": AGENT_A})["id"])
        run = _body(_get(client, f"/api/workflow_runs/{run_id}", _pat(["runs:read"])))["run"]
        assert run["status"] == "running" and run["ended_at"] is None and run["duration_ms"] is None

    def test_a_run_whose_agent_id_is_not_a_uuid_is_outside_every_allowlist(self, client, db):
        run_id = _run(db, agent="legacy-agent")
        claims = _pat(["runs:read"], {"agents": [AGENT_A]})
        assert _get(client, f"/api/workflow_runs/{run_id}", claims).status_code == 404
        assert _body(_get(client, f"/api/workflow_runs/{run_id}", _pat(["runs:read"])))["run"]["agent_id"] == (
            "legacy-agent"
        )

    @pytest.mark.parametrize(
        "path",
        [
            "/api/workflow_runs",
            "/api/workflow_runs/11111111-1111-1111-1111-111111111111",
            "/api/workflow_runs/11111111-1111-1111-1111-111111111111/steps/0",
        ],
    )
    def test_anonymous_callers_are_401(self, client, db, path):
        assert _get(client, path, None).status_code == 401

    @pytest.mark.parametrize(
        "path",
        [
            "/api/workflow_runs",
            "/api/workflow_runs/11111111-1111-1111-1111-111111111111",
            "/api/workflow_runs/11111111-1111-1111-1111-111111111111/steps/0",
        ],
    )
    def test_a_database_failure_is_a_500(self, client, monkeypatch, path):
        @contextmanager
        def _broken():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        monkeypatch.setattr("docsgpt.api.user.workflow_runs.routes.db_readonly", _broken)
        response = _get(client, path, _pat(["runs:read"]))
        assert response.status_code == 500
        assert "db down" not in response.get_data(as_text=True)

    def test_a_malformed_download_path_is_404(self, db, storage):
        assert _download("not-a-uuid", "also-not", _pat(["artifacts:read"])).status_code == 404

    def test_a_missing_file_is_404(self, db, monkeypatch):
        run_id = _run(db)
        artifact_id = _artifact(db, run_id)

        class _Gone:
            def get_file(self, path):
                raise FileNotFoundError(path)

        monkeypatch.setattr(
            "docsgpt.storage.storage_creator.StorageCreator.get_storage", staticmethod(lambda: _Gone())
        )
        assert _download(run_id, artifact_id, _pat(["artifacts:read"])).status_code == 404

    def test_an_unexpected_download_failure_is_a_400(self, db, monkeypatch):
        run_id = _run(db)
        artifact_id = _artifact(db, run_id)

        class _Broken:
            def get_file(self, path):
                raise RuntimeError("storage down")

        monkeypatch.setattr(
            "docsgpt.storage.storage_creator.StorageCreator.get_storage", staticmethod(lambda: _Broken())
        )
        response = _download(run_id, artifact_id, _pat(["artifacts:read"]))
        assert response.status_code == 400
        assert "storage down" not in response.text


# ---------------------------------------------------------------------------
# One step's full values
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStep:
    def _steps(self):
        big = "x" * 100_000
        return [
            dict(_STEPS[0]),
            {
                "node_id": "extract",
                "node_type": "agent",
                "status": "completed",
                "started_at": "2026-10-29T10:00:00+00:00",
                "completed_at": "2026-10-29T10:00:12+00:00",
                "duration_ms": 12000,
                "error": None,
                "state_delta": {"node_extract_output": big, "terms": big},
                "tool_calls": [],
            },
        ]

    def test_returns_a_steps_full_output_and_state_changes(self, client, db):
        run_id = _run(db, steps=self._steps())

        response = _get(client, f"/api/workflow_runs/{run_id}/steps/1", _pat(["runs:read"]))

        assert response.status_code == 200
        step = _body(response)["step"]
        assert step["step_index"] == 1
        assert step["node_id"] == "extract"
        assert step["output"] == "x" * 100_000
        assert step["state_delta"] == {"terms": "x" * 100_000}

    def test_a_step_that_set_no_output_has_none(self, client, db):
        run_id = _run(db, steps=self._steps())
        step = _body(_get(client, f"/api/workflow_runs/{run_id}/steps/0", _pat(["runs:read"])))["step"]
        assert step["output"] is None
        assert step["state_delta"] == {"query": "Extract the terms"}

    def test_a_step_not_saved_yet_is_409_while_the_run_runs(self, client, db):
        wf = _workflow(db)
        run_id = str(WorkflowRunsRepository(db).create(wf, OWNER, "running", inputs={"agent_id": AGENT_A})["id"])

        response = _get(client, f"/api/workflow_runs/{run_id}/steps/0", _pat(["runs:read"]))

        assert response.status_code == 409
        assert _body(response)["code"] == "step_not_saved_yet"

    def test_a_step_past_the_end_of_a_finished_run_is_404(self, client, db):
        run_id = _run(db, steps=self._steps())
        assert _get(client, f"/api/workflow_runs/{run_id}/steps/2", _pat(["runs:read"])).status_code == 404

    def test_holds_to_the_same_access_as_the_run(self, client, db):
        theirs = _run(db, user=OTHER, steps=self._steps())
        b = _run(db, agent=AGENT_B, steps=self._steps())

        assert _get(client, f"/api/workflow_runs/{theirs}/steps/1", _pat(["runs:read"])).status_code == 404
        restricted = _pat(["runs:read"], {"agents": [AGENT_A]})
        assert _get(client, f"/api/workflow_runs/{b}/steps/1", restricted).status_code == 404
        assert _get(client, f"/api/workflow_runs/{b}/steps/1", _pat(["artifacts:read"])).status_code == 403

    def test_a_session_caller_reads_its_step(self, client, db):
        run_id = _run(db, steps=self._steps())
        assert _get(client, f"/api/workflow_runs/{run_id}/steps/1", {"sub": OWNER}).status_code == 200

    def test_a_step_saved_before_the_rename_reads_its_state_snapshot(self, client, db):
        legacy = {"node_id": "n", "node_type": "agent", "status": "completed", "state_snapshot": {"node_n_output": "o", "k": 1}}
        run_id = _run(db, steps=[legacy])
        step = _body(_get(client, f"/api/workflow_runs/{run_id}/steps/0", _pat(["runs:read"])))["step"]
        assert step["output"] == "o" and step["state_delta"] == {"k": 1}
