"""Celery tasks on a team's sources (STEP1_PLAN D14; WP4b).

A team's source runs as the team's principal, so its ingest slots are keyed
by the person who started it (one busy member doesn't block the team), and a
poisoned task's terminal event reaches that person, never the principal.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from docsgpt.api.user import ingest_slots
from docsgpt.core.settings import settings

PRINCIPAL = "__team__3f2a0000-0000-4000-8000-000000000001"


def _task(task_id="task-1"):
    return SimpleNamespace(request=SimpleNamespace(id=task_id, called_directly=False, is_eager=False, retries=0))


def _ingest(self, source_id, user, idempotency_key=None, actor_id=None):  # the shape of reingest_source_task
    return None


@pytest.fixture
def cap(monkeypatch):
    monkeypatch.setattr(settings, "INGEST_MAX_CONCURRENT_PER_USER", 2)


class TestSlotsKeyedByActor:
    def test_a_team_ingest_takes_the_slot_of_the_person_who_started_it(self, cap):
        gate = ingest_slots._gated_call(_ingest, _task(), ("s1", PRINCIPAL), {"actor_id": "eddie"})

        assert gate[0] == "eddie"

    def test_a_team_ingest_nobody_started_counts_against_the_team(self, cap):
        gate = ingest_slots._gated_call(_ingest, _task(), ("s1", PRINCIPAL), {})

        assert gate[0] == PRINCIPAL

    def test_a_personal_ingest_keeps_its_owners_slots(self, cap):
        # A team editor working on someone's personal source keeps counting against the owner, as before.
        gate = ingest_slots._gated_call(_ingest, _task(), ("s1", "sam"), {"actor_id": "eddie"})

        assert gate[0] == "sam"


class TestPoisonEventRouting:
    def test_a_poisoned_team_ingest_tells_the_actor(self, monkeypatch):
        from docsgpt.api.user import tasks

        sent = []
        monkeypatch.setattr("docsgpt.worker.close_failed_ingest_progress", lambda *a, **k: None)
        monkeypatch.setattr(
            "docsgpt.events.publisher.publish_user_event", lambda user, kind, payload, **kw: sent.append(user),
        )

        tasks._emit_ingest_poison_event(
            "reingest_source_task", {"user": PRINCIPAL, "source_id": "s1", "actor_id": "eddie"},
        )

        assert sent == ["eddie"]

    def test_a_poisoned_team_graph_build_tells_the_actor(self, monkeypatch):
        from docsgpt.api.user import tasks

        sent = []
        monkeypatch.setattr(
            "docsgpt.events.publisher.publish_user_event", lambda user, kind, payload, **kw: sent.append(user),
        )

        tasks._emit_graph_poison_event("extract_graph", {"user": PRINCIPAL, "source_id": "s1", "actor_id": "eddie"})

        assert sent == ["eddie"]

    def test_a_poisoned_personal_ingest_still_tells_the_owner(self, monkeypatch):
        from docsgpt.api.user import tasks

        sent = []
        monkeypatch.setattr("docsgpt.worker.close_failed_ingest_progress", lambda *a, **k: None)
        monkeypatch.setattr(
            "docsgpt.events.publisher.publish_user_event", lambda user, kind, payload, **kw: sent.append(user),
        )

        tasks._emit_ingest_poison_event("ingest", {"user": "sam", "source_id": "s1"})

        assert sent == ["sam"]


class TestTaskSignatures:
    """New kwargs default, so messages queued before the change still run."""

    @pytest.mark.parametrize("name", ["ingest", "ingest_remote", "extract_graph"])
    def test_actor_id_is_an_optional_kwarg(self, name):
        import inspect

        from docsgpt.api.user import tasks

        task = getattr(tasks, name)
        params = inspect.signature(task.run).parameters
        assert params["actor_id"].default is None
