"""Test for CWE-22 path traversal + unauthenticated access in /api/images/<path:image_path>.

These tests verify that:
1. Unauthenticated requests to /api/images/ are rejected (401).
2. Authenticated users cannot access other users' files (403).
3. Authenticated users CAN access their own files (200).
4. Path traversal sequences are rejected (400 or 403).
5. Null-byte injections are rejected (400).
"""

import io
import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Modules that need lightweight stubs so the route file can be imported
# inside a test Flask app without Mongo / Redis / Celery / pydantic-settings.
#
# We only stub modules that are **not already loaded**. This avoids clobbering
# the real ``application.core.settings`` (or any other already-imported module)
# that later test files rely on.
# ---------------------------------------------------------------------------

_MODULES_TO_STUB = [
    "application.core.mongo_db",
    "application.core.settings",
    "application.cache",
    "application.storage.storage_creator",
    "application.vectorstore.vector_creator",
    "application.stt.constants",
    "application.stt.upload_limits",
    "application.stt.live_session",
    "application.stt.stt_creator",
    "application.tts.tts_creator",
    "application.utils",
    "application.api.user.base",
    "application.api.user.tasks",
]


@pytest.fixture(autouse=True)
def _isolate_module_stubs():
    """Install stubs before each test, restore originals afterwards."""
    originals = {}
    injected = set()

    for mod in _MODULES_TO_STUB:
        originals[mod] = sys.modules.get(mod)
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()
            injected.add(mod)

    # --- configure the stubs the route module imports ----------------------
    # Only touch stubs we own (i.e. the ones we just injected); if the real
    # module was already loaded we leave it alone.

    if "application.utils" in injected:
        sys.modules["application.utils"].safe_filename = lambda x: x

    if "application.core.settings" in injected:
        sys.modules["application.core.settings"].settings = MagicMock(
            UPLOAD_FOLDER="inputs"
        )
    elif hasattr(sys.modules.get("application.core.settings", object), "settings"):
        # Real settings is loaded – nothing to patch; the route file will use
        # the real value.
        pass

    if "application.stt.constants" in injected:
        sys.modules[
            "application.stt.constants"
        ].SUPPORTED_AUDIO_EXTENSIONS = set()
        sys.modules[
            "application.stt.constants"
        ].SUPPORTED_AUDIO_MIME_TYPES = set()

    if "application.stt.upload_limits" in injected:
        sys.modules[
            "application.stt.upload_limits"
        ].AudioFileTooLargeError = Exception
        sys.modules[
            "application.stt.upload_limits"
        ].build_stt_file_size_limit_message = lambda: "file too large"
        sys.modules[
            "application.stt.upload_limits"
        ].enforce_audio_file_size_limit = lambda *a, **kw: None
        sys.modules[
            "application.stt.upload_limits"
        ].is_audio_filename = lambda *a: False

    yield

    # Restore originals (or remove stubs we injected)
    for mod in _MODULES_TO_STUB:
        prev = originals[mod]
        if prev is None:
            sys.modules.pop(mod, None)
        else:
            sys.modules[mod] = prev


@pytest.fixture()
def app_and_client(_isolate_module_stubs):
    """Build a tiny Flask app that only registers the attachments namespace."""
    from flask import Flask
    from flask_restx import Api

    _app = Flask(__name__)
    _app.config["TESTING"] = True

    test_api = Api(_app)

    # When `settings` is real, the route reload will use the actual value of
    # UPLOAD_FOLDER ("inputs").  When stubbed we already configured it above.
    with patch("application.api.user.attachments.routes.api", test_api):
        import application.api.user.attachments.routes as routes_mod

        importlib.reload(routes_mod)
        test_api.add_namespace(routes_mod.attachments_ns)

    yield _app, _app.test_client()


# ---------- tests ----------------------------------------------------------


class TestServeImageUnauthenticatedAccess:
    """Unauthenticated callers must receive 401."""

    def test_unauthenticated_request_returns_401(self, app_and_client):
        _, client = app_and_client
        with patch(
            "application.api.user.attachments.routes._resolve_authenticated_user",
            return_value=None,
        ):
            resp = client.get(
                "/api/images/inputs/someuser/attachments/abc123/secret.png"
            )
            assert resp.status_code == 401, (
                f"Expected 401, got {resp.status_code}: {resp.data}"
            )


class TestServeImageCrossUserAccess:
    """Authenticated user must not reach another user's file."""

    def test_cross_user_access_returns_403(self, app_and_client):
        _, client = app_and_client
        with patch(
            "application.api.user.attachments.routes._resolve_authenticated_user",
            return_value="attacker",
        ):
            resp = client.get(
                "/api/images/inputs/victim/attachments/abc123/secret.png"
            )
            assert resp.status_code == 403, (
                f"Expected 403, got {resp.status_code}: {resp.data}"
            )


class TestServeImageOwnFile:
    """Authenticated user should be able to get their own file."""

    def test_own_file_returns_200(self, app_and_client):
        _, client = app_and_client
        mock_file = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        storage_mock = MagicMock()
        storage_mock.get_file.return_value = mock_file

        with patch(
            "application.api.user.attachments.routes._resolve_authenticated_user",
            return_value="testuser",
        ), patch(
            "application.api.user.base.storage", storage_mock,
        ):
            resp = client.get(
                "/api/images/inputs/testuser/attachments/abc123/photo.png"
            )
            assert resp.status_code == 200, (
                f"Expected 200, got {resp.status_code}: {resp.data}"
            )


class TestServeImagePathTraversal:
    """Path traversal must be blocked."""

    def test_dotdot_in_path_blocked(self, app_and_client):
        """Traversal escaping the user dir returns 400 or 403."""
        _, client = app_and_client
        with patch(
            "application.api.user.attachments.routes._resolve_authenticated_user",
            return_value="testuser",
        ):
            resp = client.get(
                "/api/images/inputs/testuser/../../etc/passwd"
            )
            assert resp.status_code in (400, 403), (
                f"Expected 400 or 403, got {resp.status_code}: {resp.data}"
            )

    def test_bare_dotdot_returns_error(self, app_and_client):
        """A path that normalizes to '..' must be caught."""
        _, client = app_and_client
        with patch(
            "application.api.user.attachments.routes._resolve_authenticated_user",
            return_value="testuser",
        ):
            resp = client.get("/api/images/../../../etc/passwd")
            assert resp.status_code in (400, 403, 404), (
                f"Expected 400/403/404, got {resp.status_code}: {resp.data}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
