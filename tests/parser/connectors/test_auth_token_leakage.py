"""Regression tests: connector auth must not leak session tokens.

Three connector auth modules previously interpolated the raw session
token into ``ValueError`` messages. With ``exc_info=True`` on upstream
loggers those messages land in ``stack_logs`` (Postgres) and Sentry.
These tests pin the behaviour so the raw token never reappears in the
raised exception's ``str()`` representation, while a stable, short
SHA-256 fingerprint is present for correlation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from application.parser.connectors._auth_utils import session_token_fingerprint


SECRET_TOKEN = "super-secret-session-token-ABCDEF1234567890"


class _FakeRepo:
    """Fake ``ConnectorSessionsRepository`` returning a preset session."""

    _session: Optional[Dict[str, Any]] = None

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def get_by_session_token(self, session_token: str) -> Optional[Dict[str, Any]]:
        return self._session


class _FakeReadonlyCtx:
    """Fake ``db_readonly`` context manager yielding a dummy connection."""

    def __enter__(self) -> MagicMock:
        return MagicMock()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


def _patches(session_return: Optional[Dict[str, Any]]):
    fake_repo_cls = type(
        "FakeRepo",
        (_FakeRepo,),
        {"_session": session_return},
    )
    return (
        patch(
            "application.storage.db.repositories.connector_sessions."
            "ConnectorSessionsRepository",
            fake_repo_cls,
        ),
        patch(
            "application.storage.db.session.db_readonly",
            lambda: _FakeReadonlyCtx(),
        ),
    )


class TestSessionTokenFingerprint:
    """Unit tests for the shared fingerprint helper."""

    @pytest.mark.unit
    def test_fingerprint_is_stable(self) -> None:
        assert session_token_fingerprint("abc") == session_token_fingerprint("abc")

    @pytest.mark.unit
    def test_fingerprint_does_not_contain_token(self) -> None:
        fp = session_token_fingerprint(SECRET_TOKEN)
        assert SECRET_TOKEN not in fp
        assert fp.startswith("sha256:")
        # 6 hex chars after the prefix.
        assert len(fp) == len("sha256:") + 6

    @pytest.mark.unit
    def test_empty_token_has_sentinel(self) -> None:
        assert session_token_fingerprint("") == "sha256:<empty>"
        # type-check intentionally ignored: defensive for None.
        assert session_token_fingerprint(None) == "sha256:<empty>"  # type: ignore[arg-type]

    @pytest.mark.unit
    def test_different_tokens_produce_different_fingerprints(self) -> None:
        assert session_token_fingerprint("a") != session_token_fingerprint("b")


class TestConfluenceAuthDoesNotLeakToken:

    @pytest.mark.unit
    def test_invalid_session_does_not_interpolate_token(self) -> None:
        from application.parser.connectors.confluence.auth import ConfluenceAuth

        auth = ConfluenceAuth.__new__(ConfluenceAuth)
        repo_patch, ctx_patch = _patches(None)
        with repo_patch, ctx_patch:
            with pytest.raises(ValueError) as excinfo:
                auth.get_token_info_from_session(SECRET_TOKEN)

        message = str(excinfo.value)
        assert SECRET_TOKEN not in message
        assert session_token_fingerprint(SECRET_TOKEN) in message


class TestGoogleDriveAuthDoesNotLeakToken:

    @pytest.mark.unit
    def test_invalid_session_does_not_interpolate_token(self) -> None:
        from application.parser.connectors.google_drive.auth import GoogleDriveAuth

        auth = GoogleDriveAuth.__new__(GoogleDriveAuth)
        repo_patch, ctx_patch = _patches(None)
        with repo_patch, ctx_patch:
            with pytest.raises(ValueError) as excinfo:
                auth.get_token_info_from_session(SECRET_TOKEN)

        # The Google Drive module wraps the inner ValueError in a broad
        # ``except Exception as e: raise ValueError(... {str(e)})`` block,
        # so the outer message still carries the fingerprint from the
        # inner raise but must never carry the raw token.
        message = str(excinfo.value)
        assert SECRET_TOKEN not in message
        assert session_token_fingerprint(SECRET_TOKEN) in message


class TestSharePointAuthDoesNotLeakToken:

    @pytest.mark.unit
    def test_invalid_session_does_not_interpolate_token(self) -> None:
        from application.parser.connectors.share_point.auth import SharePointAuth

        auth = SharePointAuth.__new__(SharePointAuth)
        repo_patch, ctx_patch = _patches(None)
        with repo_patch, ctx_patch:
            with pytest.raises(ValueError) as excinfo:
                auth.get_token_info_from_session(SECRET_TOKEN)

        # SharePoint also wraps the inner ValueError. Same invariants.
        message = str(excinfo.value)
        assert SECRET_TOKEN not in message
        assert session_token_fingerprint(SECRET_TOKEN) in message
