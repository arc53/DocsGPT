"""Unit tests for the bounded-drain gunicorn worker."""

from unittest import mock

import pytest

from application.core import shutdown
from application.core.settings import settings
from application.gunicorn_worker import (
    BoundedDrainUvicornWorker,
    _ShutdownAwareServer,
)


@pytest.fixture(autouse=True)
def _reset_flag():
    shutdown.reset_shutdown()
    yield
    shutdown.reset_shutdown()


@pytest.mark.unit
def test_worker_bounds_graceful_shutdown():
    cfg = BoundedDrainUvicornWorker.CONFIG_KWARGS
    assert cfg["timeout_graceful_shutdown"] == settings.GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS
    assert isinstance(cfg["timeout_graceful_shutdown"], int)
    # Must sit under the gunicorn --timeout (180) or the watchdog fires first.
    assert 0 < cfg["timeout_graceful_shutdown"] < 180


@pytest.mark.unit
@pytest.mark.asyncio
async def test_server_shutdown_raises_flag():
    from uvicorn.config import Config

    async def _dummy_asgi(scope, receive, send):  # pragma: no cover - never called
        pass

    server = _ShutdownAwareServer(Config(app=_dummy_asgi))
    assert shutdown.is_shutting_down() is False

    # Stub the heavy uvicorn drain so the test only exercises our override.
    with mock.patch("uvicorn.server.Server.shutdown", new=mock.AsyncMock()) as sup:
        await server.shutdown()

    # The flag is raised before delegating to uvicorn's real shutdown.
    assert shutdown.is_shutting_down() is True
    sup.assert_awaited_once()
