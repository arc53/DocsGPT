"""The boxd sandbox backend against real boxd machines.

Opt-in: it creates one isolated machine (two for the reattach check run in the same one), runs code in it, and
deletes it at the end. It needs a boxd API key::

    BOXD_LIVE=1 BOXD_API_KEY=bxd_... BOXD_REGION=fra \\
        python -m pytest tests/integration/test_boxd_sandbox_live.py --override-ini="addopts=" -v

``BOXD_ORG``, ``BOXD_NAME_PREFIX`` and ``BOXD_DELETE_AFTER`` (minutes, default 60; 0 turns the timer off) are read
as the app reads them. The tests run in file order and share the
machine, as one conversation's runs would.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("BOXD_LIVE") != "1" or not os.environ.get("BOXD_API_KEY"),
        reason="set BOXD_LIVE=1 and BOXD_API_KEY to run against real boxd machines",
    ),
]

SESSION = f"live-{uuid.uuid4().hex[:12]}"
_DELETE_AFTER = int(os.environ.get("BOXD_DELETE_AFTER") or 60) * 60


@pytest.fixture(autouse=True)
def _no_network():
    """Overrides the suite-wide network guard: these tests talk to boxd on purpose."""
    yield


def _backend(**overrides):
    from docsgpt.sandbox.boxd import BoxdSandbox

    kwargs = dict(
        api_key=os.environ["BOXD_API_KEY"],
        org=os.environ.get("BOXD_ORG") or None,
        region=os.environ.get("BOXD_REGION") or None,
        name_prefix=os.environ.get("BOXD_NAME_PREFIX") or "docsgpt-live",
        default_timeout=60,
        max_file_bytes=10 * 1024 * 1024,
        delete_after=_DELETE_AFTER,
    )
    kwargs.update(overrides)
    return BoxdSandbox(**kwargs)


@pytest.fixture(scope="module")
def box():
    backend = _backend()
    started = time.monotonic()
    opened = backend.open_session(SESSION)
    print(f"\nopened machine {opened.handle} in {time.monotonic() - started:.2f}s (created={opened.created})")
    assert opened.created is True
    yield backend
    # A no-op after test_close_deletes_the_machine; deletes the machine when a run stops before it.
    backend.close(SESSION)


def test_a_run_prints_its_output(box):
    started = time.monotonic()
    result = box.exec(SESSION, "import sys\nprint(1 + 1)\nprint(sys.version_info[:2])")
    print(f"first run in {time.monotonic() - started:.2f}s")
    assert result.ok, result
    assert result.stdout.splitlines()[0] == "2"


def test_the_machine_is_isolated(box):
    machine = box._client.machines.get(box._get_handle(SESSION).machine_id)
    assert machine.networking.isolated is True
    assert machine.labels.get("docsgpt_session_id") == SESSION


@pytest.mark.skipif(not _DELETE_AFTER, reason="BOXD_DELETE_AFTER=0 turns the timer off")
def test_the_machine_carries_its_delete_after_timer(box):
    handle = box._get_handle(SESSION)
    first = box._client.machines.get(handle.machine_id).delete_at
    print(f"delete_at after create: {first}")
    assert first is not None
    time.sleep(2)
    box._keep(handle, force=True)
    refreshed = box._client.machines.get(handle.machine_id).delete_at
    print(f"delete_at after a refresh: {refreshed}")
    assert refreshed is not None and refreshed > first


def test_an_exception_is_an_error_with_its_traceback(box):
    result = box.exec(SESSION, "print('before')\nraise ValueError('boom')")
    assert not result.ok
    assert result.exit_code == 1
    assert result.error_name == "ExecutionError"
    assert "before" in result.stdout and "ValueError: boom" in result.stdout


def test_a_run_over_its_timeout_is_stopped(box):
    started = time.monotonic()
    result = box.exec(SESSION, "import time\nprint('started', flush=True)\ntime.sleep(60)", timeout=3)
    assert time.monotonic() - started < 20
    assert result.error_name == "TimeoutError"
    assert "started" in result.stdout


def test_files_persist_between_runs_and_variables_do_not(box):
    first = box.exec(SESSION, "x = 41\nopen('note.txt', 'w').write('kept')")
    assert first.ok, first
    second = box.exec(SESSION, "print(open('note.txt').read())\nprint(x)")
    assert "kept" in second.stdout
    assert "NameError" in second.stdout


def test_pip_installs_persist_and_charts_are_captured(box):
    install = box.exec(
        SESSION,
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'matplotlib'], check=True)\n"
        "import matplotlib\n"
        "print(matplotlib.__version__)",
        timeout=300,
    )
    assert install.ok, install
    chart = box.exec(SESSION, "import matplotlib.pyplot as plt\nplt.plot([1, 3, 2])\nplt.show()\nprint('drawn')")
    assert chart.ok, chart
    assert "drawn" in chart.stdout
    assert len(chart.plots) == 1
    assert base64.b64decode(chart.plots[0].content_base64).startswith(b"\x89PNG")


def test_a_5_mib_file_round_trips(box):
    data = os.urandom(5 * 1024 * 1024)
    box.put_file(SESSION, "inputs/blob.bin", data)
    seen = box.exec(SESSION, "import hashlib\nprint(hashlib.sha256(open('inputs/blob.bin','rb').read()).hexdigest())")
    assert seen.stdout.strip() == hashlib.sha256(data).hexdigest()
    assert hashlib.sha256(box.get_file(SESSION, "inputs/blob.bin")).digest() == hashlib.sha256(data).digest()
    assert "inputs/blob.bin" in box.list_files(SESSION)


def test_an_empty_file_is_written(box):
    box.put_file(SESSION, "scratch/empty/.keep", b"")
    assert "scratch/empty/.keep" in box.list_files(SESSION)
    assert box.get_file(SESSION, "scratch/empty/.keep") == b""


def test_a_file_over_the_cap_is_not_read(box):
    from docsgpt.sandbox.base import FileTooLargeError

    box.exec(SESSION, "open('big.bin', 'wb').write(b'0' * (11 * 1024 * 1024))")
    with pytest.raises(FileTooLargeError):
        box.get_file(SESSION, "big.bin")
    box.remove_path(SESSION, "big.bin")
    assert "big.bin" not in box.list_files(SESSION)


def test_a_detached_run_finishes_after_its_launch_returned(box):
    run = box.start_detached(SESSION, "import time\nprint('one', flush=True)\ntime.sleep(3)\nprint('two')", 60, "k1")
    deadline = time.monotonic() + 60
    state = box.poll_detached(SESSION, run, with_output=True)
    assert not state.done
    while not state.done and time.monotonic() < deadline:
        time.sleep(1)
        state = box.poll_detached(SESSION, run)
    assert state.done and state.result.ok, state
    assert state.result.stdout.split() == ["one", "two"]
    assert not any(p.startswith("scratch/jobs/k1/") for p in box.list_files(SESSION))


def test_a_detached_run_can_be_cancelled(box):
    run = box.start_detached(SESSION, "import time\ntime.sleep(120)", 300, "k2")
    box.cancel_detached(SESSION, run)
    deadline = time.monotonic() + 30
    state = box.poll_detached(SESSION, run)
    while not state.done and time.monotonic() < deadline:
        time.sleep(1)
        state = box.poll_detached(SESSION, run)
    assert state.done and not state.result.ok


def test_another_process_reattaches_by_label(box):
    other = _backend()
    opened = other.open_session(SESSION)
    assert opened.created is False
    assert opened.handle == box._get_handle(SESSION).machine_id
    assert other.exec(SESSION, "print(open('note.txt').read())").stdout.strip() == "kept"
    other.release_handle(SESSION, opened.handle)


def test_a_hibernated_machine_runs_code_again(box):
    machine_id = box._get_handle(SESSION).machine_id
    box._client.machines.hibernate(machine_id)
    deadline = time.monotonic() + 120
    while str(box._client.machines.get(machine_id).status) != "hibernated" and time.monotonic() < deadline:
        time.sleep(1)
    started = time.monotonic()
    result = box.exec(SESSION, "print(open('note.txt').read())")
    print(f"run on a hibernated machine in {time.monotonic() - started:.2f}s")
    assert result.ok and result.stdout.strip() == "kept", result


def test_a_wrong_key_fails_clearly():
    from boxd.errors import AuthenticationError

    backend = _backend(api_key="not-a-real-key")
    with pytest.raises(AuthenticationError):
        backend.open(f"live-{uuid.uuid4().hex[:12]}")


def test_close_deletes_the_machine(box):
    from boxd.errors import NotFoundError

    machine_id = box._get_handle(SESSION).machine_id
    box.close(SESSION)
    with pytest.raises(NotFoundError):
        box._client.machines.get(machine_id)
