"""Optional live smoke test against real Daytona Cloud; skipped unless explicitly enabled.

Run with both flags set so CI/normal runs never burn cloud quota::

    RUN_DAYTONA_LIVE=1 DAYTONA_API_KEY=dtn_... .venv/bin/python -m pytest \
        tests/sandbox/test_daytona_live.py -q --no-cov
"""

import os
import uuid

import pytest

pytest.importorskip("daytona")

_ENABLED = os.environ.get("RUN_DAYTONA_LIVE") == "1" and bool(os.environ.get("DAYTONA_API_KEY"))

pytestmark = pytest.mark.skipif(
    not _ENABLED,
    reason="set RUN_DAYTONA_LIVE=1 and DAYTONA_API_KEY to run the live Daytona smoke test",
)


@pytest.fixture()
def live_sandbox():
    from application.sandbox.daytona import DaytonaSandbox

    s = DaytonaSandbox(
        api_key=os.environ["DAYTONA_API_KEY"],
        api_url=os.environ.get("DAYTONA_API_URL") or None,
        target=os.environ.get("DAYTONA_TARGET") or None,
    )
    session_id = "smoke" + uuid.uuid4().hex[:8]
    s.open(session_id)
    try:
        yield s, session_id
    finally:
        s.close(session_id)  # always delete the cloud sandbox so we never leak cost


def test_live_exec_and_file_roundtrip(live_sandbox):
    s, session_id = live_sandbox

    res = s.exec(session_id, "print(6 * 7)")
    assert res.ok, res.error_value
    assert "42" in res.stdout

    s.put_file(session_id, "hello.txt", b"daytona-smoke")
    assert s.get_file(session_id, "hello.txt") == b"daytona-smoke"
    assert "hello.txt" in s.list_files(session_id)
