"""Unit tests for the anonymous startup version-check client.

All external dependencies (Postgres, Redis, HTTP) are mocked so the
suite runs in pure-Python isolation. The focus is on the branching
behavior described in the spec: opt-out, cache-hit, cache-miss,
lock-denied, and the various failure paths that must never propagate.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
import requests

from application.updates import version_check as vc_module


class _FakeRepo:
    """Stand-in for AppMetadataRepository backed by a plain dict."""

    def __init__(self, store: dict | None = None, *, raise_on_get_instance: bool = False):
        self._store: dict[str, str] = dict(store) if store else {}
        self._raise = raise_on_get_instance

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def get_or_create_instance_id(self) -> str:
        if self._raise:
            raise RuntimeError("simulated Postgres outage")
        existing = self._store.get("instance_id")
        if existing:
            return existing
        self._store["instance_id"] = "11111111-2222-3333-4444-555555555555"
        return self._store["instance_id"]


@contextmanager
def _fake_db_session():
    """Stand-in for ``db_session()`` — yields ``None`` because the fake
    repository ignores its connection argument."""
    yield None


def _install_repo(monkeypatch, repo: _FakeRepo):
    """Patch the repo constructor so ``AppMetadataRepository(conn)`` → ``repo``."""
    monkeypatch.setattr(
        vc_module, "AppMetadataRepository", lambda conn: repo
    )


def _install_db_session(monkeypatch, *, raise_exc: Exception | None = None):
    if raise_exc is not None:

        @contextmanager
        def boom():
            raise raise_exc
            yield  # pragma: no cover - unreachable

        monkeypatch.setattr(vc_module, "db_session", boom)
    else:
        monkeypatch.setattr(vc_module, "db_session", _fake_db_session)


def _make_redis_mock(*, get_return=None, set_return=True):
    client = MagicMock()
    client.get.return_value = get_return
    client.set.return_value = set_return
    client.setex.return_value = True
    client.delete.return_value = 1
    return client


@pytest.fixture
def enable_check(monkeypatch):
    monkeypatch.setattr(vc_module.settings, "VERSION_CHECK", True)


@pytest.mark.unit
def test_opt_out_short_circuits(monkeypatch):
    """VERSION_CHECK=0 → no Postgres, no Redis, no network."""
    monkeypatch.setattr(vc_module.settings, "VERSION_CHECK", False)
    db_spy = MagicMock()
    redis_spy = MagicMock()
    post_spy = MagicMock()
    monkeypatch.setattr(vc_module, "db_session", db_spy)
    monkeypatch.setattr(vc_module, "get_redis_instance", redis_spy)
    monkeypatch.setattr(vc_module.requests, "post", post_spy)

    vc_module.run_check()

    db_spy.assert_not_called()
    redis_spy.assert_not_called()
    post_spy.assert_not_called()


@pytest.mark.unit
def test_cache_hit_renders_without_lock_or_network(monkeypatch, enable_check, capsys):
    repo = _FakeRepo({"version_check_notice_shown": "1"})
    _install_repo(monkeypatch, repo)
    _install_db_session(monkeypatch)

    cached = {
        "advisories": [
            {
                "id": "DOCSGPT-TEST-1",
                "title": "Example",
                "severity": "high",
                "fixed_in": "0.17.0",
                "url": "https://example.test/a",
                "summary": "Upgrade required.",
            }
        ]
    }
    redis_client = _make_redis_mock(get_return=json.dumps(cached).encode("utf-8"))
    monkeypatch.setattr(vc_module, "get_redis_instance", lambda: redis_client)

    post_spy = MagicMock()
    monkeypatch.setattr(vc_module.requests, "post", post_spy)

    vc_module.run_check()

    redis_client.get.assert_called_once_with(vc_module.CACHE_KEY)
    redis_client.set.assert_not_called()
    redis_client.setex.assert_not_called()
    post_spy.assert_not_called()
    assert "SECURITY ADVISORY: DOCSGPT-TEST-1" in capsys.readouterr().out


@pytest.mark.unit
def test_cache_miss_lock_acquired_fetches_and_caches(monkeypatch, enable_check):
    repo = _FakeRepo({"version_check_notice_shown": "1"})
    _install_repo(monkeypatch, repo)
    _install_db_session(monkeypatch)

    redis_client = _make_redis_mock(get_return=None, set_return=True)
    monkeypatch.setattr(vc_module, "get_redis_instance", lambda: redis_client)

    response_body = {
        "advisories": [
            {
                "id": "DOCSGPT-LOW-1",
                "title": "Minor",
                "severity": "low",
                "fixed_in": "0.17.0",
                "url": "https://example.test/low",
            }
        ],
        "next_check_after": 1800,
    }
    post_response = MagicMock()
    post_response.status_code = 200
    post_response.json.return_value = response_body
    post_spy = MagicMock(return_value=post_response)
    monkeypatch.setattr(vc_module.requests, "post", post_spy)

    vc_module.run_check()

    post_spy.assert_called_once()
    call_kwargs = post_spy.call_args
    assert call_kwargs.args[0] == vc_module.ENDPOINT_URL
    payload = call_kwargs.kwargs["json"]
    assert payload["client"] == "docsgpt-backend"
    assert payload["instance_id"] == "11111111-2222-3333-4444-555555555555"
    assert "version" in payload and "python_version" in payload

    # Lock acquired with NX EX, cache written with server-specified TTL,
    # lock released.
    redis_client.set.assert_called_once()
    set_kwargs = redis_client.set.call_args.kwargs
    assert set_kwargs == {"nx": True, "ex": vc_module.LOCK_TTL_SECONDS}
    redis_client.setex.assert_called_once()
    setex_args = redis_client.setex.call_args.args
    assert setex_args[0] == vc_module.CACHE_KEY
    assert setex_args[1] == 1800  # server override under 6h
    redis_client.delete.assert_called_once_with(vc_module.LOCK_KEY)


@pytest.mark.unit
def test_cache_miss_lock_denied_skips_silently(monkeypatch, enable_check):
    repo = _FakeRepo({"version_check_notice_shown": "1"})
    _install_repo(monkeypatch, repo)
    _install_db_session(monkeypatch)

    redis_client = _make_redis_mock(get_return=None, set_return=False)  # lock not acquired
    monkeypatch.setattr(vc_module, "get_redis_instance", lambda: redis_client)

    post_spy = MagicMock()
    monkeypatch.setattr(vc_module.requests, "post", post_spy)

    vc_module.run_check()

    post_spy.assert_not_called()
    redis_client.setex.assert_not_called()
    redis_client.delete.assert_not_called()


@pytest.mark.unit
def test_instance_id_persisted_across_runs(monkeypatch, enable_check):
    repo = _FakeRepo({"version_check_notice_shown": "1"})
    _install_repo(monkeypatch, repo)
    _install_db_session(monkeypatch)

    redis_client = _make_redis_mock(get_return=None, set_return=True)
    monkeypatch.setattr(vc_module, "get_redis_instance", lambda: redis_client)

    post_response = MagicMock()
    post_response.status_code = 200
    post_response.json.return_value = {}
    monkeypatch.setattr(
        vc_module.requests, "post", MagicMock(return_value=post_response)
    )

    vc_module.run_check()
    first_id = repo.get("instance_id")
    vc_module.run_check()
    second_id = repo.get("instance_id")

    assert first_id is not None
    assert first_id == second_id


@pytest.mark.unit
def test_first_run_notice_emitted_once(monkeypatch, enable_check, capsys):
    repo = _FakeRepo()  # empty — notice not shown yet
    _install_repo(monkeypatch, repo)
    _install_db_session(monkeypatch)

    # Cache hit so we don't need to mock HTTP. Notice logic runs before cache.
    redis_client = _make_redis_mock(get_return=json.dumps({}).encode("utf-8"))
    monkeypatch.setattr(vc_module, "get_redis_instance", lambda: redis_client)

    vc_module.run_check()
    first_out = capsys.readouterr().out
    assert "Anonymous version check enabled" in first_out
    assert repo.get("version_check_notice_shown") == "1"

    vc_module.run_check()
    second_out = capsys.readouterr().out
    assert "Anonymous version check enabled" not in second_out


@pytest.mark.unit
def test_postgres_unavailable_skips_silently(monkeypatch, enable_check):
    _install_db_session(monkeypatch, raise_exc=RuntimeError("db down"))
    redis_spy = MagicMock()
    post_spy = MagicMock()
    monkeypatch.setattr(vc_module, "get_redis_instance", redis_spy)
    monkeypatch.setattr(vc_module.requests, "post", post_spy)

    vc_module.run_check()

    redis_spy.assert_not_called()
    post_spy.assert_not_called()


@pytest.mark.unit
def test_postgres_repo_raises_skips_silently(monkeypatch, enable_check):
    repo = _FakeRepo(raise_on_get_instance=True)
    _install_repo(monkeypatch, repo)
    _install_db_session(monkeypatch)
    redis_spy = MagicMock()
    post_spy = MagicMock()
    monkeypatch.setattr(vc_module, "get_redis_instance", redis_spy)
    monkeypatch.setattr(vc_module.requests, "post", post_spy)

    vc_module.run_check()

    redis_spy.assert_not_called()
    post_spy.assert_not_called()


@pytest.mark.unit
def test_redis_unavailable_proceeds_uncached(monkeypatch, enable_check):
    """``get_redis_instance()`` → None should not abort the check."""
    repo = _FakeRepo({"version_check_notice_shown": "1"})
    _install_repo(monkeypatch, repo)
    _install_db_session(monkeypatch)
    monkeypatch.setattr(vc_module, "get_redis_instance", lambda: None)

    post_response = MagicMock()
    post_response.status_code = 200
    post_response.json.return_value = {"advisories": []}
    post_spy = MagicMock(return_value=post_response)
    monkeypatch.setattr(vc_module.requests, "post", post_spy)

    vc_module.run_check()

    post_spy.assert_called_once()


@pytest.mark.unit
def test_http_5xx_swallowed(monkeypatch, enable_check):
    repo = _FakeRepo({"version_check_notice_shown": "1"})
    _install_repo(monkeypatch, repo)
    _install_db_session(monkeypatch)
    redis_client = _make_redis_mock(get_return=None, set_return=True)
    monkeypatch.setattr(vc_module, "get_redis_instance", lambda: redis_client)

    post_response = MagicMock()
    post_response.status_code = 503
    post_response.json.return_value = {}
    monkeypatch.setattr(
        vc_module.requests, "post", MagicMock(return_value=post_response)
    )

    vc_module.run_check()

    redis_client.setex.assert_not_called()
    # Lock still released so the next cycle can retry.
    redis_client.delete.assert_called_once_with(vc_module.LOCK_KEY)


@pytest.mark.unit
def test_http_timeout_swallowed(monkeypatch, enable_check):
    repo = _FakeRepo({"version_check_notice_shown": "1"})
    _install_repo(monkeypatch, repo)
    _install_db_session(monkeypatch)
    redis_client = _make_redis_mock(get_return=None, set_return=True)
    monkeypatch.setattr(vc_module, "get_redis_instance", lambda: redis_client)
    monkeypatch.setattr(
        vc_module.requests,
        "post",
        MagicMock(side_effect=requests.Timeout("boom")),
    )

    # Must not raise.
    vc_module.run_check()

    redis_client.setex.assert_not_called()
    redis_client.delete.assert_called_once_with(vc_module.LOCK_KEY)


@pytest.mark.unit
def test_compute_ttl_honors_server_override():
    assert vc_module._compute_ttl({"next_check_after": 300}) == 300
    assert vc_module._compute_ttl({"next_check_after": 60000}) == vc_module.CACHE_TTL_SECONDS
    assert vc_module._compute_ttl({}) == vc_module.CACHE_TTL_SECONDS
    assert vc_module._compute_ttl({"next_check_after": "bad"}) == vc_module.CACHE_TTL_SECONDS
    # Zero/negative overrides fall back to the 6h default.
    assert vc_module._compute_ttl({"next_check_after": 0}) == vc_module.CACHE_TTL_SECONDS


@pytest.mark.unit
def test_render_advisories_logs_warning_and_prints_banner(monkeypatch, capsys):
    with patch.object(vc_module, "logger") as mock_logger:
        vc_module._render_advisories(
            {
                "advisories": [
                    {
                        "id": "DOCSGPT-2025-001",
                        "title": "SSRF",
                        "severity": "critical",
                        "fixed_in": "0.17.0",
                        "url": "https://example.test/a",
                        "summary": "Your DocsGPT is vulnerable.",
                    },
                    {
                        "id": "DOCSGPT-2025-002",
                        "title": "Low-sev",
                        "severity": "low",
                    },
                ]
            }
        )
    # Both advisories logged as warnings.
    assert mock_logger.warning.call_count == 2
    out = capsys.readouterr().out
    # Only the high/critical one gets the console banner.
    assert "DOCSGPT-2025-001" in out
    assert "DOCSGPT-2025-002" not in out
