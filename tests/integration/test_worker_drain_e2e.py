"""End-to-end regression tests for the gunicorn graceful-shutdown drain fix.

Boots real gunicorn against a minimal a2wsgi+Flask SSE app, holds an SSE
connection open, trips a ``max_requests`` recycle, and checks the worker log:
RED proves the stock worker is ``WORKER TIMEOUT``'d; GREEN proves the
bounded-drain worker recycles cleanly. Opt-in (slow). Run with:
    python -m pytest tests/integration/test_worker_drain_e2e.py -o addopts=""
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_ROOT = Path(__file__).resolve().parents[2]
_APP = "tests.integration._drain_harness_app:asgi_app"
_GUNICORN = Path(sys.executable).with_name("gunicorn")

# Shrunk timing so a full recycle takes seconds, not the production minutes.
_MAX_REQUESTS = "5"
_TIMEOUT = "6"            # gunicorn worker-timeout watchdog
_GRACEFUL = "30"          # gunicorn --graceful-timeout (not the lever; here for parity)
_GUNICORN_CONF = _ROOT / "application" / "gunicorn_conf.py"

pytestmark.append(
    pytest.mark.skipif(not _GUNICORN.exists(), reason="gunicorn binary not found")
)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _boot(worker_class: str, port: int, logpath: Path, extra_env: dict) -> tuple:
    env = dict(os.environ)
    env.update(
        {
            "OTEL_SDK_DISABLED": "true",
            "AUTO_MIGRATE": "false",
            "AUTO_CREATE_DB": "false",
            "GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS": "3",
            **extra_env,
        }
    )
    cmd = [
        str(_GUNICORN),
        "-w", "1",
        "-k", worker_class,
        "--bind", f"127.0.0.1:{port}",
        "--timeout", _TIMEOUT,
        "--graceful-timeout", _GRACEFUL,
        "--keep-alive", "2",
        "--max-requests", _MAX_REQUESTS,
        "--max-requests-jitter", "0",
        "--pythonpath", str(_ROOT),
        "--config", str(_GUNICORN_CONF),
        _APP,
    ]
    fh = open(logpath, "w")
    proc = subprocess.Popen(
        cmd, cwd=str(_ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return proc, fh


def _reap(proc, fh) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            proc.kill()
    finally:
        try:
            fh.close()
        except Exception:
            pass


def _get(url: str, timeout: float = 3.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            r.read()
            return r.status
    except Exception:
        return 0


def _wait_http(base: str, timeout: float = 30.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _get(base + "/health", timeout=2) == 200:
            return True
        time.sleep(0.2)
    return False


def _hold_sse(url: str, hold: float = 25.0) -> threading.Thread:
    def _run():
        try:
            urllib.request.urlopen(url, timeout=hold).read()
        except Exception:
            pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def _trip_recycle(base: str, n: int = 8) -> None:
    # Fire more than --max-requests completed responses so the recycle trips
    # deterministically (the held SSE response never completes, so it doesn't
    # count, and some requests race the drain once it starts).
    for _ in range(n):
        _get(base + "/health", timeout=3)


def _wait_for(logpath: Path, needle: str, timeout: float) -> str:
    end = time.monotonic() + timeout
    text = ""
    while time.monotonic() < end:
        text = logpath.read_text()
        if needle in text:
            return text
        time.sleep(0.3)
    return text


@pytest.mark.integration
@pytest.mark.slow
def test_stock_worker_is_force_killed_with_held_sse(tmp_path):
    """RED: stock worker + non-cooperative SSE -> drain hangs -> WORKER TIMEOUT."""
    port = _free_port()
    log = tmp_path / "stock.log"
    base = f"http://127.0.0.1:{port}"
    proc, fh = _boot("uvicorn_worker.UvicornWorker", port, log, {})
    try:
        assert _wait_http(base), f"app never came up:\n{log.read_text()}"
        _hold_sse(base + "/sse", hold=25)
        time.sleep(1.0)  # let the SSE request register before tripping
        _trip_recycle(base)
        text = _wait_for(log, "WORKER TIMEOUT", timeout=15)
    finally:
        _reap(proc, fh)

    assert "Maximum request limit" in text, text
    # The held SSE hangs the unbounded drain until the watchdog force-kills it.
    assert "WORKER TIMEOUT" in text, text


@pytest.mark.integration
@pytest.mark.slow
def test_bounded_drain_worker_exits_cleanly_with_held_sse(tmp_path):
    """GREEN: bounded-drain worker + cooperative SSE -> clean recycle, no kill."""
    port = _free_port()
    log = tmp_path / "fixed.log"
    base = f"http://127.0.0.1:{port}"
    proc, fh = _boot(
        "application.gunicorn_worker.BoundedDrainUvicornWorker",
        port,
        log,
        {"DRAIN_HARNESS_COOPERATIVE": "1"},
    )
    try:
        assert _wait_http(base), f"app never came up:\n{log.read_text()}"
        _hold_sse(base + "/sse", hold=25)
        time.sleep(1.0)
        _trip_recycle(base)
        # Clean recycle => replacement worker reaches "Application startup complete" twice.
        end = time.monotonic() + 14
        text = ""
        while time.monotonic() < end:
            text = log.read_text()
            if text.count("Application startup complete") >= 2:
                break
            time.sleep(0.3)
    finally:
        _reap(proc, fh)

    assert "Maximum request limit" in text, text
    assert text.count("Application startup complete") >= 2, (
        f"replacement worker did not boot cleanly:\n{text}"
    )
    for bad in ("WORKER TIMEOUT", "was sent SIGABRT", "was sent SIGKILL"):
        assert bad not in text, f"unexpected watchdog kill ({bad}):\n{text}"
