"""Tests for application/services/artifact_resource_service.py.

The service exposes a Bearer-key principal's own artifacts as MCP resources.
These tests patch the DB/storage seams (``db_readonly``, the repositories, and
``StorageCreator``) so they run without Postgres, mirroring the light mocking
in ``tests/services/test_mcp_server.py``. They assert that:

- ``resources/list`` returns only the principal's artifacts;
- ``resources/read`` returns ``text`` vs ``blob`` by mime with the right type;
- a foreign-owner artifact is denied (no cross-principal exposure);
- an unauthenticated / unresolved principal gets an empty list / denied read;
- a non-UUID id is rejected as not-found (no leaked DB error);
- the read is byte-capped.
"""

from __future__ import annotations

import base64
import io
from contextlib import contextmanager

import pytest

from application.services import artifact_resource_service as svc

OWNER = "owner-1"
STRANGER = "stranger-2"

# Real UUIDs: the read path gates non-UUID ids before they reach the DB.
ART_TEXT = "11111111-1111-4111-8111-111111111111"
ART_BIN = "22222222-2222-4222-8222-222222222222"
ART_FOREIGN = "33333333-3333-4333-8333-333333333333"


@contextmanager
def _fake_conn():
    yield object()


class _FakeAgents:
    """Stub AgentsRepository: maps api_key -> agent row (or None)."""

    _MAP = {"owner-key": {"user_id": OWNER}, "stranger-key": {"user_id": STRANGER}}

    def __init__(self, conn):
        pass

    def find_by_key(self, key):
        return self._MAP.get(key)


class _FakeArtifacts:
    """Stub ArtifactsRepository backed by in-memory artifact/version dicts."""

    artifacts: dict = {}
    versions: dict = {}

    def __init__(self, conn):
        pass

    def list_artifacts(self, user_id=None, conversation_id=None, workflow_run_id=None):
        return [a for a in self.artifacts.values() if a["user_id"] == user_id]

    def get_artifact(self, artifact_id):
        return self.artifacts.get(artifact_id)

    def get_version(self, artifact_id, version):
        return self.versions.get((artifact_id, version))


class _FakeStorage:
    """Stub BaseStorage.get_file returning a capped BytesIO of fixed bytes."""

    blob = b"x" * 10

    def get_file(self, path):
        return io.BytesIO(self.blob)


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    """Point the service's DB/storage seams at the in-memory fakes."""
    _FakeArtifacts.artifacts = {
        ART_TEXT: {"id": ART_TEXT, "user_id": OWNER, "kind": "data", "title": "notes", "current_version": 2},
        ART_BIN: {"id": ART_BIN, "user_id": OWNER, "kind": "image", "title": "chart", "current_version": 1},
        ART_FOREIGN: {
            "id": ART_FOREIGN,
            "user_id": STRANGER,
            "kind": "data",
            "title": "secret",
            "current_version": 1,
        },
    }
    _FakeArtifacts.versions = {
        (ART_TEXT, 2): {"mime_type": "text/csv", "storage_path": "k/text.csv", "preview_text": None},
        (ART_BIN, 1): {"mime_type": "image/png", "storage_path": "k/chart.png", "preview_text": None},
        (ART_FOREIGN, 1): {"mime_type": "text/plain", "storage_path": "k/secret.txt", "preview_text": None},
    }
    monkeypatch.setattr(svc, "db_readonly", _fake_conn)
    monkeypatch.setattr(svc, "AgentsRepository", _FakeAgents)
    monkeypatch.setattr(svc, "ArtifactsRepository", _FakeArtifacts)
    monkeypatch.setattr(svc.StorageCreator, "get_storage", staticmethod(lambda: _FakeStorage()))


@pytest.mark.unit
class TestListArtifactResources:
    def test_lists_only_principal_artifacts(self):
        out = svc.list_artifact_resources("owner-key")
        uris = {str(r.uri) for r in out}
        assert uris == {f"artifact://{ART_TEXT}/v2", f"artifact://{ART_BIN}/v1"}
        assert f"artifact://{ART_FOREIGN}/v1" not in uris

    def test_unresolved_principal_is_empty(self):
        assert svc.list_artifact_resources("bogus-key") == []

    def test_missing_token_is_empty(self):
        assert svc.list_artifact_resources(None) == []

    def test_resource_carries_name_and_mime(self):
        out = {str(r.uri): r for r in svc.list_artifact_resources("owner-key")}
        assert out[f"artifact://{ART_TEXT}/v2"].name == "notes"
        # The list row never advertises a wildcard/wrong type; the image kind
        # falls back to the generic octet-stream hint. FastMCP Resource uses
        # ``mime_type`` (and must survive ``to_mcp_resource()`` for the wire).
        assert out[f"artifact://{ART_BIN}/v1"].mime_type == "application/octet-stream"

    def test_resources_are_fastmcp_and_render_to_wire(self):
        # Regression: ``resources/list`` must yield FastMCP Resource objects so
        # the server's list pipeline (reads ``.version``/``.auth``, calls
        # ``to_mcp_resource``) does not raise AttributeError on a raw mcp.types.
        from fastmcp.resources.base import Resource as FastMCPResource

        out = svc.list_artifact_resources("owner-key")
        assert out and all(isinstance(r, FastMCPResource) for r in out)
        for r in out:
            wire = r.to_mcp_resource()
            assert str(wire.uri).startswith("artifact://")


@pytest.mark.unit
class TestReadArtifactResource:
    def test_text_mime_returns_text(self):
        res = svc.read_artifact_resource("owner-key", f"artifact://{ART_TEXT}/v2")
        assert res.text == _FakeStorage.blob.decode("utf-8")
        assert res.blob_b64 is None
        assert res.mime_type == "text/csv"

    def test_binary_mime_returns_blob(self):
        res = svc.read_artifact_resource("owner-key", f"artifact://{ART_BIN}/v1")
        assert res.blob_b64 == base64.b64encode(_FakeStorage.blob).decode("ascii")
        assert res.text is None
        assert res.mime_type == "image/png"

    def test_prefers_preview_text_when_present(self, monkeypatch):
        _FakeArtifacts.versions[(ART_TEXT, 2)]["preview_text"] = "cached preview"
        res = svc.read_artifact_resource("owner-key", f"artifact://{ART_TEXT}/v2")
        assert res.text == "cached preview"

    def test_foreign_owner_is_denied(self):
        with pytest.raises(svc.ResourceDenied):
            svc.read_artifact_resource("owner-key", f"artifact://{ART_FOREIGN}/v1")

    def test_unauthenticated_is_denied(self):
        with pytest.raises(svc.ResourceDenied):
            svc.read_artifact_resource(None, f"artifact://{ART_TEXT}/v2")
        with pytest.raises(svc.ResourceDenied):
            svc.read_artifact_resource("bogus-key", f"artifact://{ART_TEXT}/v2")

    def test_unknown_uri_scheme_not_found(self):
        with pytest.raises(svc.ResourceNotFound):
            svc.read_artifact_resource("owner-key", "https://example.com/x")

    def test_non_uuid_id_is_not_found(self):
        # A non-UUID id must be rejected before the DB cast (no leaked DataError).
        with pytest.raises(svc.ResourceNotFound):
            svc.read_artifact_resource("owner-key", "artifact://not-a-uuid/v1")

    def test_missing_version_not_found(self):
        with pytest.raises(svc.ResourceNotFound):
            svc.read_artifact_resource("owner-key", f"artifact://{ART_TEXT}/v99")

    def test_read_is_byte_capped(self, monkeypatch):
        monkeypatch.setattr(svc.settings, "ARTIFACT_RESOURCE_READ_MAX_BYTES", 3)
        _FakeStorage.blob = b"abcdefghij"
        try:
            res = svc.read_artifact_resource("owner-key", f"artifact://{ART_BIN}/v1")
            assert base64.b64decode(res.blob_b64) == b"abc"
        finally:
            _FakeStorage.blob = b"x" * 10
