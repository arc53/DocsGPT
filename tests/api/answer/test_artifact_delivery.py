"""Artifact entries described for API clients: version metadata, download URL and the turn's list."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from docsgpt.api.answer.services import artifact_delivery
from docsgpt.api.answer.services.artifact_delivery import ArtifactDescriber, artifact_download_url
from docsgpt.storage.db.repositories.artifacts import ArtifactsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository

OWNER = "delivery-owner"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def _db(pg_conn, monkeypatch):
    @contextmanager
    def _use_conn():
        yield pg_conn

    monkeypatch.setattr(artifact_delivery, "db_readonly", _use_conn)
    return pg_conn


def _artifact(conn, conversation_id, user_id=OWNER):
    repo = ArtifactsRepository(conn)
    artifact = repo.create_artifact(
        user_id,
        "document",
        conversation_id=conversation_id,
        title="Services Agreement",
        mime_type=DOCX,
        filename="Services Agreement.docx",
        size=1200,
        sha256="a" * 64,
    )
    repo.append_version(str(artifact["id"]), mime_type=DOCX, filename="Services Agreement.docx", size=1500, sha256="b" * 64)
    return str(artifact["id"])


# ---------------------------------------------------------------------------
# Download URL
# ---------------------------------------------------------------------------


def test_download_url_is_relative_without_a_public_base(monkeypatch):
    monkeypatch.setattr(artifact_delivery.settings, "PUBLIC_API_BASE_URL", None, raising=False)
    url = artifact_download_url("abc", version=2, conversation_id="c-1")
    assert url == "/api/artifacts/abc/download?conversation_id=c-1&version=2"


def test_download_url_is_absolute_with_a_public_base(monkeypatch):
    monkeypatch.setattr(artifact_delivery.settings, "PUBLIC_API_BASE_URL", "https://docs.example.com/", raising=False)
    assert artifact_download_url("abc") == "https://docs.example.com/api/artifacts/abc/download"


def test_download_url_never_carries_a_key(monkeypatch):
    monkeypatch.setattr(artifact_delivery.settings, "PUBLIC_API_BASE_URL", None, raising=False)
    assert "api_key" not in artifact_download_url("abc", version=1, conversation_id="c")


# ---------------------------------------------------------------------------
# Describer
# ---------------------------------------------------------------------------


def test_describe_adds_the_produced_versions_metadata(_db, monkeypatch):
    monkeypatch.setattr(artifact_delivery.settings, "PUBLIC_API_BASE_URL", None, raising=False)
    conv = ConversationsRepository(_db).create(OWNER, name="c")
    artifact_id = _artifact(_db, str(conv["id"]))
    describer = ArtifactDescriber(OWNER, str(conv["id"]))

    [v1] = describer.describe([{"id": artifact_id, "filename": "Services Agreement.docx", "ref": "A1", "version": 1}])
    assert v1 == {
        "id": artifact_id,
        "filename": "Services Agreement.docx",
        "ref": "A1",
        "version": 1,
        "mime_type": DOCX,
        "size": 1200,
        "sha256": "a" * 64,
        "kind": "document",
        "title": "Services Agreement",
        "download_url": f"/api/artifacts/{artifact_id}/download?conversation_id={conv['id']}&version=1",
    }
    # Without a version the current one is described.
    [current] = describer.describe([{"id": artifact_id}])
    assert current["version"] == 2 and current["sha256"] == "b" * 64


def test_summary_lists_each_artifact_once_at_its_latest_version(_db):
    conv = ConversationsRepository(_db).create(OWNER, name="c")
    first = _artifact(_db, str(conv["id"]))
    second = _artifact(_db, str(conv["id"]))
    describer = ArtifactDescriber(OWNER, str(conv["id"]))
    describer.tool_call({"call_id": "1", "artifacts": [{"id": first, "version": 1}]})
    describer.tool_call({"call_id": "2", "artifacts": [{"id": second, "version": 1}]})
    describer.tool_call({"call_id": "3", "artifacts": [{"id": first, "version": 2}]})

    summary = describer.summary()
    assert [(a["id"], a["version"]) for a in summary] == [(first, 2), (second, 1)]


def test_reads_once_per_artifact_version(_db, monkeypatch):
    conv = ConversationsRepository(_db).create(OWNER, name="c")
    artifact_id = _artifact(_db, str(conv["id"]))
    describer = ArtifactDescriber(OWNER, str(conv["id"]))
    loads = []
    original = describer._load
    monkeypatch.setattr(describer, "_load", lambda *a: loads.append(a) or original(*a))

    calls = [{"call_id": "1", "artifacts": [{"id": artifact_id, "version": 1}]}]
    describer.tool_calls(calls)
    describer.tool_calls(calls)
    assert len(loads) == 1


def test_another_users_artifact_is_not_described(_db):
    conv = ConversationsRepository(_db).create("someone-else", name="c")
    artifact_id = _artifact(_db, str(conv["id"]), user_id="someone-else")
    [entry] = ArtifactDescriber(OWNER, None).describe([{"id": artifact_id, "filename": "x.docx", "version": 1}])
    assert "sha256" not in entry and "title" not in entry
    assert entry["download_url"].endswith(f"/api/artifacts/{artifact_id}/download?version=1")


def test_a_failed_read_keeps_the_entry(monkeypatch):
    @contextmanager
    def _broken():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(artifact_delivery, "db_readonly", _broken)
    entry_id = "6f1c3f0e-1d1b-4b8a-9a3e-0f6d2a1b9c11"
    [entry] = ArtifactDescriber(OWNER, "conv-1").describe([{"id": entry_id, "filename": "a.csv", "version": 3}])
    assert entry["filename"] == "a.csv"
    assert entry["download_url"].endswith(f"{entry_id}/download?conversation_id=conv-1&version=3")


def test_entries_without_artifacts_pass_through():
    describer = ArtifactDescriber(OWNER, None)
    data = {"call_id": "x", "result": "ok"}
    assert describer.tool_call(data) is data
    assert describer.tool_calls(None) is None
    assert describer.describe("not a list") == []
    assert describer.describe(["junk", {"filename": "no id"}]) == []
    assert describer.summary() == []


def test_a_malformed_id_is_not_looked_up(monkeypatch):
    def _no_db():
        raise AssertionError("must not read")

    monkeypatch.setattr(artifact_delivery, "db_readonly", _no_db)
    [entry] = ArtifactDescriber(OWNER, "conv-1").describe([{"id": "A1"}])
    assert entry["download_url"].endswith("/api/artifacts/A1/download?conversation_id=conv-1")


# ---------------------------------------------------------------------------
# complete_stream / process_response_stream
# ---------------------------------------------------------------------------


def _events(stream):
    out = []
    for frame in stream:
        for line in frame.split("\n"):
            if line.startswith("data:"):
                out.append(json.loads(line[len("data:"):].strip()))
    return out


def _describe_as(monkeypatch, rows):
    monkeypatch.setattr(ArtifactDescriber, "_load", lambda self, artifact_id, version: dict(rows.get(artifact_id, {})))


@pytest.mark.unit
class TestCompleteStreamArtifacts:
    def _stream(self, flask_app, events):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            agent = MagicMock()
            agent.gen.return_value = iter(events)
            agent.tool_calls = []
            return list(
                BaseAnswerResource().complete_stream(
                    question="Draft it",
                    agent=agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": OWNER},
                    should_persist=False,
                )
            )

    def test_tool_call_events_and_end_carry_described_artifacts(self, flask_app, monkeypatch):
        monkeypatch.setattr(artifact_delivery.settings, "PUBLIC_API_BASE_URL", "https://api.example.com", raising=False)
        _describe_as(
            monkeypatch,
            {"art-1": {"mime_type": DOCX, "size": 10, "sha256": "c" * 64, "kind": "document", "title": "Deal",
                       "conversation_id": "conv-9"}},
        )
        call = {
            "call_id": "c1",
            "tool_name": "artifact_generator",
            "action_name": "create_artifact",
            "status": "completed",
            "artifact_id": "art-1",
            "artifacts": [{"id": "art-1", "filename": "Deal.docx", "ref": "A1", "version": 1}],
        }
        events = _events(
            self._stream(
                flask_app,
                [{"type": "tool_call", "data": call}, {"tool_calls": [call]}, {"answer": "Done."}],
            )
        )

        tool_call = next(e for e in events if e.get("type") == "tool_call")
        [entry] = tool_call["data"]["artifacts"]
        assert entry["mime_type"] == DOCX and entry["sha256"] == "c" * 64 and entry["version"] == 1
        assert entry["download_url"] == "https://api.example.com/api/artifacts/art-1/download?conversation_id=conv-9&version=1"
        tool_calls = next(e for e in events if e.get("type") == "tool_calls")
        assert tool_calls["tool_calls"][0]["artifacts"][0]["download_url"] == entry["download_url"]
        end = events[-1]
        assert end["type"] == "end"
        assert end["artifacts"] == [entry]
        # The persisted copy keeps the plain entry.
        assert "download_url" not in call["artifacts"][0]

    def test_end_has_no_artifacts_when_none_were_made(self, flask_app):
        events = _events(self._stream(flask_app, [{"answer": "Hi."}]))
        assert events[-1] == {"type": "end"}

    def test_process_response_stream_returns_the_turn_artifacts(self, flask_app, monkeypatch):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        _describe_as(monkeypatch, {"art-1": {"mime_type": "text/csv", "conversation_id": "conv-1"}})
        call = {"call_id": "c1", "status": "completed", "artifacts": [{"id": "art-1", "version": 2}]}
        stream = self._stream(flask_app, [{"type": "tool_call", "data": call}, {"tool_calls": [call]}, {"answer": "x"}])
        with flask_app.app_context():
            result = BaseAnswerResource().process_response_stream(iter(stream))
        assert [a["id"] for a in result["artifacts"]] == ["art-1"]
        assert result["artifacts"][0]["mime_type"] == "text/csv"
        assert result["tool_calls"][0]["artifacts"][0]["download_url"].endswith("version=2")
