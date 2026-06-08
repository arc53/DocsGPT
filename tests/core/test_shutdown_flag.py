"""Unit tests for the process-wide graceful-shutdown flag."""

import pytest

from application.core import shutdown


@pytest.fixture(autouse=True)
def _reset_flag():
    shutdown.reset_shutdown()
    yield
    shutdown.reset_shutdown()


@pytest.mark.unit
def test_flag_starts_clear():
    assert shutdown.is_shutting_down() is False


@pytest.mark.unit
def test_begin_shutdown_sets_flag():
    shutdown.begin_shutdown()
    assert shutdown.is_shutting_down() is True


@pytest.mark.unit
def test_begin_shutdown_is_idempotent():
    shutdown.begin_shutdown()
    shutdown.begin_shutdown()
    assert shutdown.is_shutting_down() is True


@pytest.mark.unit
def test_reset_clears_flag():
    shutdown.begin_shutdown()
    shutdown.reset_shutdown()
    assert shutdown.is_shutting_down() is False
