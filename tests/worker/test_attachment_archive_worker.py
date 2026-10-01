"""A zip attachment is unpacked into one attachment per member.

Runs the worker against a real ephemeral Postgres and local storage, so the
rows it writes are asserted as stored. Members parse as their own Celery
tasks: the dispatch seam is replaced by a queue the tests drain, standing in
for the workers.
"""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest

import docsgpt.storage.db.engine as engine_module
from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
from docsgpt.storage.db.session import db_readonly

USER = "zip-user"


class _StubTask:
    def update_state(self, *args, **kwargs):
        pass


class _RetryingTask(_StubTask):
    """A task with retries left, as Celery binds it on a first attempt."""

    max_retries = 3

    class request:
        retries = 0


@pytest.fixture()
def wired_engine(pg_engine, monkeypatch):
    monkeypatch.setattr(engine_module, "_engine", None)
    eng = engine_module.get_engine()
    yield eng
    eng.dispose()
    monkeypatch.setattr(engine_module, "_engine", None)


@pytest.fixture()
def storage_dir(tmp_path, monkeypatch):
    from docsgpt.storage.local import LocalStorage

    storage = LocalStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(
        "docsgpt.storage.storage_creator.StorageCreator.get_storage",
        classmethod(lambda cls: storage),
    )
    return tmp_path


@pytest.fixture()
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "docsgpt.worker.publish_user_event",
        lambda user, kind, payload, scope=None: seen.append((kind, dict(payload))),
    )
    return seen


def _zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buffer.getvalue()


def _upload(storage_dir, payload, filename="bundle.zip"):
    attachment_id = str(uuid.uuid4())
    rel_path = f"inputs/{USER}/attachments/{attachment_id}/{filename}"
    full = storage_dir / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(payload)
    return {"filename": filename, "attachment_id": attachment_id, "path": rel_path, "metadata": {}}


@pytest.fixture()
def dispatched(monkeypatch):
    """Member tasks handed to Celery, in dispatch order."""
    queue = []
    monkeypatch.setattr(
        "docsgpt.worker._dispatch_archive_member",
        lambda member_info, user: queue.append((member_info, user)),
    )
    return queue


def _run(info):
    """Run the zip's own task (unpack and dispatch), not its members."""
    from docsgpt.worker import attachment_worker

    return attachment_worker(_StubTask(), info, USER)


def _run_member(member_info, task=None):
    from docsgpt.worker import archive_member_worker

    return archive_member_worker(task or _StubTask(), member_info, USER)


def _drain(queue, *, newest_first=False, peak=None):
    """Run every dispatched member task until none is left."""
    while queue:
        if peak is not None:
            peak.append(len(queue))
        member_info, _ = queue.pop() if newest_first else queue.pop(0)
        _run_member(member_info)


def _run_all(info, queue, **kwargs):
    result = _run(info)
    _drain(queue, **kwargs)
    return result


def _parent(info):
    with db_readonly() as conn:
        return AttachmentsRepository(conn).get_by_legacy_id(info["attachment_id"], USER)


def _members(parent_id):
    with db_readonly() as conn:
        rows = AttachmentsRepository(conn).list_for_user(USER)
    members = [r for r in rows if (r.get("metadata") or {}).get("parent_attachment_id") == str(parent_id)]
    return sorted(members, key=lambda r: r["metadata"]["archive_index"])


ENTRIES = [
    ("notes.txt", b"meeting notes about the budget"),
    ("docs/readme.md", b"# Readme\nproject overview"),
    ("tool.exe", bytes(range(256)) * 8),
    ("nested.zip", _zip([("inner.txt", b"inner text file")])),
]


@pytest.mark.usefixtures("wired_engine", "dispatched")
class TestZipAttachment:
    def test_members_become_their_own_parsed_attachments(self, storage_dir, events, dispatched):
        info = _upload(storage_dir, _zip(ENTRIES))

        result = _run_all(info, dispatched)

        parent = _parent(info)
        members = _members(parent["id"])
        assert [m["metadata"]["archive_path"] for m in members] == [
            "notes.txt", "docs/readme.md", "nested.zip/inner.txt",
        ]
        assert [m["filename"] for m in members] == ["notes.txt", "readme.md", "inner.txt"]
        assert "budget" in members[0]["content"]
        assert "inner text" in members[2]["content"]
        for member in members:
            assert member["metadata"]["extraction"]["status"] == "ok"
            assert member["content_hash"]
            assert (storage_dir / member["upload_path"]).is_file()
            assert member["upload_path"] != parent["upload_path"]
        assert result["attachment_id"] == info["attachment_id"]

    def test_parent_is_an_index_not_the_compressed_bytes(self, storage_dir, events, dispatched):
        info = _upload(storage_dir, _zip(ENTRIES))

        _run_all(info, dispatched)

        parent = _parent(info)
        assert parent["mime_type"] == "application/zip"
        assert "PK" not in parent["content"]
        assert "notes.txt" in parent["content"] and "tool.exe" in parent["content"]
        archive = parent["metadata"]["archive"]
        assert archive["members"] == 3
        assert {"archive_path": "tool.exe", "reason": "unsupported_type"} in archive["skipped"]
        assert archive["skipped_count"] == 1
        assert parent["metadata"]["extraction"]["status"] == "ok"
        assert parent["content_hash"]

    def test_only_the_zip_reports_progress(self, storage_dir, events, dispatched):
        info = _upload(storage_dir, _zip(ENTRIES))

        _run_all(info, dispatched)

        ids = {payload["attachment_id"] for _, payload in events}
        assert ids == {info["attachment_id"]}
        kinds = [kind for kind, _ in events]
        assert kinds[0] == "attachment.queued" and kinds[-1] == "attachment.completed"
        completed = events[-1][1]
        assert completed["archive"] == {"members": 3, "skipped": 1, "failed": 0}
        assert completed["token_count"] > 0

    def test_a_retry_updates_the_same_member_rows(self, storage_dir, events, dispatched):
        info = _upload(storage_dir, _zip(ENTRIES))

        _run_all(info, dispatched)
        _run_all(info, dispatched)

        assert len(_members(_parent(info)["id"])) == 3

    def test_unsupported_members_do_not_use_up_the_file_limit(self, storage_dir, events, dispatched, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_ARCHIVE_MAX_MEMBERS", 2)
        objects = [(f".git/objects/{i:02x}/blob", bytes(range(256)) * 4) for i in range(5)]
        info = _upload(storage_dir, _zip([*objects, ("notes.txt", b"notes"), ("readme.md", b"# readme")]))

        _run_all(info, dispatched)

        parent = _parent(info)
        assert [m["metadata"]["archive_path"] for m in _members(parent["id"])] == ["notes.txt", "readme.md"]
        archive = parent["metadata"]["archive"]
        assert {s["reason"] for s in archive["skipped"]} == {"unsupported_type"}
        assert archive["skipped_count"] == 5

    def test_a_zip_bomb_fails_the_upload(self, storage_dir, events):
        from docsgpt.worker import AttachmentRejectedError

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("zeros.txt", b"\0" * (5 * 1024 * 1024))
        info = _upload(storage_dir, buffer.getvalue())

        with pytest.raises(AttachmentRejectedError):
            _run(info)

        assert events[-1][0] == "attachment.failed"
        assert _parent(info)["metadata"]["extraction"]["status"] == "failed"


def _member_names(queue):
    return [member_info["metadata"]["archive_path"] for member_info, _ in queue]


@pytest.mark.usefixtures("wired_engine")
class TestZipMemberFanOut:
    @pytest.fixture(autouse=True)
    def _window_of_two(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_ARCHIVE_PARALLELISM", 2)

    def test_the_zip_task_dispatches_members_instead_of_parsing_them(self, storage_dir, events, dispatched):
        info = _upload(storage_dir, _zip(ENTRIES))

        _run(info)

        assert _member_names(dispatched) == ["notes.txt", "docs/readme.md"]
        parent = _parent(info)
        assert parent["metadata"]["extraction"]["status"] == "processing"
        assert _members(parent["id"]) == []
        assert "attachment.completed" not in [kind for kind, _ in events]
        for member_info, user in dispatched:
            assert user == USER
            assert member_info["metadata"]["parent_attachment_id"] == str(parent["id"])
            assert (storage_dir / member_info["path"]).is_file()

    def test_at_most_the_window_of_members_is_in_flight(self, storage_dir, events, dispatched):
        info = _upload(storage_dir, _zip(ENTRIES))
        peak = []

        _run(info)
        handled = []
        while dispatched:
            peak.append(len(dispatched))
            member_info, _ = dispatched.pop(0)
            handled.append(member_info["metadata"]["archive_path"])
            _run_member(member_info)

        assert max(peak) == 2
        assert handled == ["notes.txt", "docs/readme.md", "nested.zip/inner.txt"]

    def test_the_zip_completes_once_after_its_last_member(self, storage_dir, events, dispatched):
        info = _upload(storage_dir, _zip(ENTRIES))

        _run_all(info, dispatched, newest_first=True)

        kinds = [kind for kind, _ in events]
        assert kinds.count("attachment.completed") == 1
        assert kinds[-1] == "attachment.completed"
        parent = _parent(info)
        members = _members(parent["id"])
        assert events[-1][1]["token_count"] == sum(m["token_count"] for m in members)
        assert events[-1][1]["archive"] == {"members": 3, "skipped": 1, "failed": 0}
        assert parent["metadata"]["extraction"]["status"] == "ok"
        assert "nested.zip/inner.txt" in parent["content"]
        assert all(m["metadata"]["extraction"]["status"] == "ok" for m in members)

    def test_progress_moves_as_members_finish(self, storage_dir, events, dispatched):
        info = _upload(storage_dir, _zip(ENTRIES))

        _run_all(info, dispatched)

        currents = [p["current"] for kind, p in events if kind == "attachment.progress"]
        assert currents == sorted(currents)
        assert len(set(currents)) >= 4

    def test_a_failed_member_is_recorded_with_its_reason(self, storage_dir, events, dispatched, monkeypatch):
        import docsgpt.worker as worker

        real = worker._single_attachment_worker

        def flaky(task, member_info, user, **kwargs):
            if member_info["metadata"]["archive_path"] == "docs/readme.md":
                raise ValueError("parser exploded")
            return real(task, member_info, user, **kwargs)

        monkeypatch.setattr(worker, "_single_attachment_worker", flaky)
        info = _upload(storage_dir, _zip(ENTRIES))

        _run_all(info, dispatched)

        parent = _parent(info)
        archive = parent["metadata"]["archive"]
        assert archive["failed"] == 1
        assert archive["failed_members"] == [{"archive_path": "docs/readme.md", "reason": "parser exploded"}]
        assert "docs/readme.md (could not be parsed: parser exploded)" in parent["content"]
        assert events[-1][0] == "attachment.completed"
        assert events[-1][1]["archive"] == {"members": 3, "skipped": 1, "failed": 1}

    def test_a_member_with_retries_left_does_not_count_until_it_settles(
        self, storage_dir, events, dispatched, monkeypatch
    ):
        import docsgpt.worker as worker

        real = worker._single_attachment_worker
        failures = {"left": 1}

        def blip(task, member_info, user, **kwargs):
            if member_info["metadata"]["archive_path"] == "notes.txt" and failures["left"]:
                failures["left"] -= 1
                raise ConnectionError("storage blip")
            return real(task, member_info, user, **kwargs)

        monkeypatch.setattr(worker, "_single_attachment_worker", blip)
        info = _upload(storage_dir, _zip(ENTRIES))
        _run(info)
        first, _ = dispatched.pop(0)

        with pytest.raises(ConnectionError):
            _run_member(first, task=_RetryingTask())

        assert _member_names(dispatched) == ["docs/readme.md"]
        assert "outcomes" in _parent(info)["metadata"]["archive"]
        assert first["attachment_id"] not in _parent(info)["metadata"]["archive"]["outcomes"]

        _run_member(first, task=_RetryingTask())
        _drain(dispatched)

        archive = _parent(info)["metadata"]["archive"]
        assert archive["failed"] == 0
        assert events[-1][0] == "attachment.completed"

    def test_a_redelivered_member_is_counted_once(self, storage_dir, events, dispatched):
        info = _upload(storage_dir, _zip(ENTRIES))
        _run(info)
        first, _ = dispatched.pop(0)

        _run_member(first)
        _run_member(first)
        _drain(dispatched)

        kinds = [kind for kind, _ in events]
        assert kinds.count("attachment.completed") == 1
        assert _parent(info)["metadata"]["archive"]["members"] == 3

    def test_a_poisoned_member_still_lets_the_zip_complete(self, storage_dir, events, dispatched):
        from docsgpt.api.user.tasks import _emit_archive_member_poison_event

        info = _upload(storage_dir, _zip(ENTRIES))
        _run(info)
        first, _ = dispatched.pop(0)

        _emit_archive_member_poison_event("store_archive_member", {"user": USER, "member_info": first})
        _drain(dispatched)

        parent = _parent(info)
        archive = parent["metadata"]["archive"]
        assert archive["failed"] == 1
        assert archive["failed_members"][0]["archive_path"] == "notes.txt"
        assert events[-1][0] == "attachment.completed"
        member = next(m for m in _members(parent["id"]) if m["metadata"]["archive_path"] == "notes.txt")
        assert member["metadata"]["extraction"]["status"] == "failed"

    def test_a_poisoned_zip_task_keeps_its_members_bookkeeping(self, storage_dir, events, dispatched):
        from docsgpt.api.user.tasks import _emit_attachment_poison_event

        info = _upload(storage_dir, _zip(ENTRIES))
        _run(info)

        _emit_attachment_poison_event("store_attachment", {"user": USER, "file_info": info})

        parent = _parent(info)
        assert parent["metadata"]["extraction"]["status"] == "failed"
        assert parent["metadata"]["archive"]["status"] == "processing"
        assert len(parent["metadata"]["archive"]["planned"]) == 3
        _drain(dispatched)
        archive = _parent(info)["metadata"]["archive"]
        assert archive["status"] == "complete"
        assert archive["members"] == 3 and archive["failed"] == 0

    def test_a_zip_poisoned_before_it_has_a_row_gets_a_failure_row(self, storage_dir, events):
        from docsgpt.api.user.tasks import _emit_attachment_poison_event

        info = _upload(storage_dir, _zip(ENTRIES))

        _emit_attachment_poison_event("store_attachment", {"user": USER, "file_info": info})

        extraction = _parent(info)["metadata"]["extraction"]
        assert extraction["status"] == "failed"
        assert extraction["parser"] == "archive"

    def test_a_retried_zip_keeps_the_members_that_finished(self, storage_dir, events, dispatched):
        info = _upload(storage_dir, _zip(ENTRIES))
        _run(info)
        first, _ = dispatched.pop(0)
        _run_member(first)

        _run(info)
        _drain(dispatched)

        assert [kind for kind, _ in events].count("attachment.completed") == 1
        parent = _parent(info)
        assert parent["metadata"]["archive"]["members"] == 3
        assert parent["metadata"]["archive"]["failed"] == 0
        assert len(_members(parent["id"])) == 3

    def test_a_zip_with_nothing_to_parse_completes_at_once(self, storage_dir, events, dispatched):
        info = _upload(storage_dir, _zip([("tool.exe", bytes(range(256)) * 8)]))

        _run(info)

        assert dispatched == []
        assert events[-1][0] == "attachment.completed"
        assert events[-1][1]["archive"] == {"members": 0, "skipped": 1, "failed": 0}
        assert _parent(info)["metadata"]["extraction"]["status"] == "ok"


def test_members_are_dispatched_as_their_own_idempotent_task(monkeypatch):
    from docsgpt.api.user import tasks
    from docsgpt.worker import _dispatch_archive_member

    calls = []
    monkeypatch.setattr(tasks.store_archive_member, "apply_async", lambda **kw: calls.append(kw))
    member_info = {"attachment_id": "h-1", "filename": "a.csv", "path": "p", "metadata": {}}

    _dispatch_archive_member(member_info, USER)

    assert calls == [{"args": [member_info, USER], "kwargs": {"idempotency_key": "archive-member:h-1"}}]
    assert tasks.store_archive_member.acks_late is True


def _backdate_dispatches(info, minutes):
    """Make the zip's dispatched members look ``minutes`` old."""
    from datetime import datetime, timedelta, timezone

    from docsgpt.storage.db.session import db_session

    stamp = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    with db_session() as conn:
        repo = AttachmentsRepository(conn)
        row = repo.get_by_legacy_id(info["attachment_id"], USER)
        archive = row["metadata"]["archive"]
        archive["dispatched_at"] = {handle: stamp for handle in archive["dispatched_at"]}
        repo.update(str(row["id"]), USER, {"metadata": {**row["metadata"], "archive": archive}})


# Just past the default ATTACHMENT_ARCHIVE_MEMBER_TIMEOUT (90 minutes).
_PAST_TIMEOUT_MINUTES = 91


def _hold_lease(member_info):
    """Make a member's task look like it is running right now (a live lease)."""
    from docsgpt.storage.db.repositories.idempotency import IdempotencyRepository
    from docsgpt.storage.db.session import db_session

    with db_session() as conn:
        IdempotencyRepository(conn).try_claim_lease(
            f"archive-member:{member_info['attachment_id']}", "store_archive_member", "t-1", "owner-1"
        )


@pytest.fixture()
def swept_events(monkeypatch):
    """Events the reconciler publishes after its sweeps commit."""
    seen = []
    monkeypatch.setattr(
        "docsgpt.events.publisher.publish_user_event",
        lambda user, kind, payload, scope=None: seen.append((kind, dict(payload))),
    )
    return seen


@pytest.mark.usefixtures("wired_engine")
class TestStuckZipMemberSweep:
    def test_the_timeout_outlasts_the_brokers_redelivery(self):
        # A member whose worker died is redelivered after the visibility
        # timeout; failing it before then would fail a task about to rerun.
        from docsgpt.core.settings.ingestion import IngestionSettings
        from docsgpt.core.settings.workers import WorkerSettings

        timeout = IngestionSettings.model_fields["ATTACHMENT_ARCHIVE_MEMBER_TIMEOUT"].default
        assert timeout > WorkerSettings.model_fields["CELERY_VISIBILITY_TIMEOUT"].default

    def test_members_pending_past_the_timeout_fail_and_the_zip_completes(
        self, storage_dir, events, dispatched, swept_events
    ):
        from docsgpt.api.user.reconciliation import run_reconciliation

        info = _upload(storage_dir, _zip(ENTRIES))
        _run(info)
        first, _ = dispatched.pop(0)
        _run_member(first)
        dispatched.clear()  # the broker lost the other two
        _backdate_dispatches(info, _PAST_TIMEOUT_MINUTES)

        summary = run_reconciliation()

        assert summary["archive_members_failed"] == 2
        parent = _parent(info)
        archive = parent["metadata"]["archive"]
        assert archive["status"] == "complete"
        assert archive["failed"] == 2
        assert [f["archive_path"] for f in archive["failed_members"]] == ["docs/readme.md", "nested.zip/inner.txt"]
        assert all("90 minutes" in f["reason"] for f in archive["failed_members"])
        assert parent["metadata"]["extraction"]["status"] == "ok"
        assert swept_events[-1][0] == "attachment.completed"
        completed = swept_events[-1][1]
        assert completed["attachment_id"] == info["attachment_id"]
        assert completed["archive"] == {"members": 3, "skipped": 1, "failed": 2}
        stuck = [m for m in _members(parent["id"]) if m["metadata"]["archive_path"] != "notes.txt"]
        assert [m["metadata"]["extraction"]["status"] for m in stuck] == ["failed", "failed"]

    def test_fresh_members_are_left_alone(self, storage_dir, events, dispatched, swept_events):
        from docsgpt.api.user.reconciliation import run_reconciliation

        info = _upload(storage_dir, _zip(ENTRIES))
        _run(info)

        summary = run_reconciliation()

        assert summary["archive_members_failed"] == 0
        assert _parent(info)["metadata"]["archive"]["status"] == "processing"
        assert swept_events == []

    def test_a_failed_member_frees_its_slot_for_the_next(
        self, storage_dir, events, dispatched, swept_events, monkeypatch
    ):
        from docsgpt.api.user.reconciliation import run_reconciliation
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_ARCHIVE_PARALLELISM", 1)
        info = _upload(storage_dir, _zip(ENTRIES))
        _run(info)
        dispatched.clear()  # notes.txt was lost
        _backdate_dispatches(info, _PAST_TIMEOUT_MINUTES)

        assert run_reconciliation()["archive_members_failed"] == 1

        assert _member_names(dispatched) == ["docs/readme.md"]
        assert "attachment.completed" not in [kind for kind, _ in swept_events]
        _drain(dispatched)
        archive = _parent(info)["metadata"]["archive"]
        assert archive["failed"] == 1
        assert archive["failed_members"][0]["archive_path"] == "notes.txt"
        assert events[-1][0] == "attachment.completed"

    def test_a_member_still_running_is_not_failed(self, storage_dir, events, dispatched, swept_events):
        from docsgpt.api.user.reconciliation import run_reconciliation

        info = _upload(storage_dir, _zip(ENTRIES))
        _run(info)
        running, _ = dispatched[0]
        _hold_lease(running)
        dispatched.clear()
        _backdate_dispatches(info, _PAST_TIMEOUT_MINUTES)

        assert run_reconciliation()["archive_members_failed"] == 2

        archive = _parent(info)["metadata"]["archive"]
        assert archive["status"] == "processing"
        assert running["attachment_id"] not in archive["outcomes"]
        assert [m["metadata"]["archive_path"] for m in archive["planned"]
                if m["attachment_id"] in archive["outcomes"]] == ["docs/readme.md", "nested.zip/inner.txt"]


def _flaky_broker(monkeypatch, queue, failing_path, failures):
    """Dispatch into ``queue``, but raise for ``failing_path`` ``failures`` times."""
    left = {"n": failures}

    def dispatch(member_info, user):
        if member_info["metadata"]["archive_path"] == failing_path and left["n"]:
            left["n"] -= 1
            raise ConnectionError("broker unreachable")
        queue.append((member_info, user))

    monkeypatch.setattr("docsgpt.worker._dispatch_archive_member", dispatch)


@pytest.mark.usefixtures("wired_engine")
class TestZipMemberDispatchFailure:
    def test_a_failed_dispatch_is_retried_once(self, storage_dir, events, monkeypatch):
        queue = []
        _flaky_broker(monkeypatch, queue, "docs/readme.md", failures=1)
        info = _upload(storage_dir, _zip(ENTRIES))

        _run_all(info, queue)

        archive = _parent(info)["metadata"]["archive"]
        assert archive["status"] == "complete"
        assert archive["failed"] == 0

    def test_a_member_that_cannot_be_queued_fails_with_a_reason(self, storage_dir, events, monkeypatch):
        queue = []
        _flaky_broker(monkeypatch, queue, "docs/readme.md", failures=99)
        info = _upload(storage_dir, _zip(ENTRIES))

        _run_all(info, queue)

        parent = _parent(info)
        archive = parent["metadata"]["archive"]
        assert archive["status"] == "complete"
        assert archive["failed"] == 1
        assert archive["failed_members"][0]["archive_path"] == "docs/readme.md"
        assert "broker unreachable" in archive["failed_members"][0]["reason"]
        assert events[-1][0] == "attachment.completed"
        member = next(m for m in _members(parent["id"]) if m["metadata"]["archive_path"] == "docs/readme.md")
        assert member["metadata"]["extraction"]["status"] == "failed"

    def test_a_member_freed_by_an_outcome_that_cannot_be_queued_fails_too(
        self, storage_dir, events, monkeypatch
    ):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_ARCHIVE_PARALLELISM", 1)
        queue = []
        _flaky_broker(monkeypatch, queue, "docs/readme.md", failures=99)
        info = _upload(storage_dir, _zip(ENTRIES))

        _run_all(info, queue)

        archive = _parent(info)["metadata"]["archive"]
        assert archive["status"] == "complete"
        assert [f["archive_path"] for f in archive["failed_members"]] == ["docs/readme.md"]
