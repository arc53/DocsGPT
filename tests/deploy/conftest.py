"""Shared fixtures for the ``docsgpt.deploy`` tests."""

import pytest

from docsgpt.deploy import commands, stack


@pytest.fixture(autouse=True)
def _default_port_reads_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a dev server on the default port from failing the deploy tests.

    Many tests run ``up`` or ``restart`` without ``--port``, so the busy-port
    check probes the real ``stack.DEFAULT_PORT`` (7091), the same port the
    documented dev setup binds. That one port is reported free. Every other
    port still goes through the real probe, so the tests that hold an
    ephemeral port to exercise the refusal are unaffected.
    """
    real_port_is_free = commands._port_is_free
    monkeypatch.setattr(
        commands,
        "_port_is_free",
        lambda port: port == stack.DEFAULT_PORT or real_port_is_free(port),
    )
