"""Tests for the deterministic checks."""

from __future__ import annotations

import pytest

from docsgpt.monitors.checks import CheckError, Content, evaluate, resolve_path, to_number


def _json(data):
    import json

    return Content(text=json.dumps(data, sort_keys=True), data=data)


class TestPaths:
    def test_resolve_path(self):
        data = {"a": {"b": [{"c": 1}, {"c": 2}]}, "items": [1, 2]}
        assert resolve_path(data, "a.b[1].c") == 2
        assert resolve_path(data, "$.a.b.0.c") == 1
        assert resolve_path(data, "items[-1]") == 2
        assert resolve_path(data, "") is data
        from docsgpt.monitors.checks import _MISSING

        assert resolve_path(data, "a.x") is _MISSING
        assert resolve_path(data, "items[5]") is _MISSING

    @pytest.mark.parametrize(
        "raw,number", [(" $52,140.10", 52140.1), ("-3", -3.0), (7, 7.0), ("none", None), (True, None)]
    )
    def test_to_number(self, raw, number):
        assert to_number(raw) == number


class TestThreshold:
    CHECK = {"type": "threshold", "value_path": "price", "op": "<", "value": 90.0}

    def test_baseline_never_fires_and_crossing_fires_once(self):
        base = evaluate(self.CHECK, _json({"price": 100}), None, baseline=True)
        assert not base.fire and not base.holds and base.detail["value"] == 100
        above = evaluate(self.CHECK, _json({"price": 95}), base.state)
        assert not above.fire
        below = evaluate(self.CHECK, _json({"price": 88}), above.state)
        assert below.fire and "88" in below.summary
        still = evaluate(self.CHECK, _json({"price": 85}), below.state)
        assert still.holds and not still.fire
        back = evaluate(self.CHECK, _json({"price": 99}), still.state)
        again = evaluate(self.CHECK, _json({"price": 80}), back.state)
        assert again.fire and again.key != below.key

    def test_already_true_at_baseline_does_not_fire_later_without_recovery(self):
        base = evaluate(self.CHECK, _json({"price": 80}), None, baseline=True)
        assert base.holds and not base.fire
        assert not evaluate(self.CHECK, _json({"price": 79}), base.state).fire

    def test_text_content_uses_the_first_number(self):
        check = {"type": "threshold", "value_path": "", "op": ">=", "value": 50000}
        result = evaluate(check, Content(text="BTC is $52,140 today"), {"holds": False})
        assert result.fire

    def test_missing_path_is_a_check_error(self):
        with pytest.raises(CheckError):
            evaluate(self.CHECK, _json({"cost": 1}), None)


class TestStatus:
    CHECK = {"type": "status", "value_path": "status", "terminal": ["success", "failure", "cancelled"]}

    def test_poll_fires_on_entering_a_terminal_state(self):
        base = evaluate(self.CHECK, _json({"status": "queued"}), None, baseline=True)
        running = evaluate(self.CHECK, _json({"status": "in_progress"}), base.state)
        assert not running.fire
        done = evaluate(self.CHECK, _json({"status": "SUCCESS"}), running.state)
        assert done.fire and done.detail["value"] == "success"
        failed = evaluate(self.CHECK, _json({"status": "failure"}), done.state)
        assert failed.fire

    def test_event_mode_judges_each_delivery(self):
        assert not evaluate(self.CHECK, _json({"status": "in_progress"}), None, mode="event").fire
        hit = evaluate(self.CHECK, _json({"status": "success"}), None, mode="event")
        assert hit.fire
        assert evaluate(self.CHECK, _json({"status": "success"}), hit.state, mode="event").fire


class TestRegex:
    def test_new_matches_fire(self):
        check = {"type": "regex", "pattern": r"(?i)series [a-d]", "when": "match"}
        base = evaluate(check, Content(text="nothing yet"), None, baseline=True)
        hit = evaluate(check, Content(text="We raised a Series B"), base.state)
        assert hit.fire and hit.detail["matches"] == ["Series B"]
        same = evaluate(check, Content(text="We raised a Series B. Also a blog post."), hit.state)
        assert not same.fire
        more = evaluate(check, Content(text="Series B and Series C"), same.state)
        assert more.fire

    def test_no_match_fires_when_text_disappears(self):
        check = {"type": "regex", "pattern": "Out of stock", "when": "no_match"}
        base = evaluate(check, Content(text="Out of stock"), None, baseline=True)
        assert not base.holds
        back = evaluate(check, Content(text="In stock: 3"), base.state)
        assert back.fire

    def test_catastrophic_pattern_times_out_as_a_check_error(self):
        check = {"type": "regex", "pattern": r"(a|aa)+$", "when": "match"}
        with pytest.raises(CheckError, match="too long"):
            evaluate(check, Content(text="a" * 60 + "b"), None)


class TestNewItems:
    CHECK = {"type": "new_items", "items_path": "issues", "id_field": "id"}

    def test_only_unseen_ids_fire(self):
        base = evaluate(self.CHECK, _json({"issues": [{"id": 1}, {"id": 2}]}), None, baseline=True)
        assert not base.fire and base.state["seen"] == ["1", "2"]
        nothing = evaluate(self.CHECK, _json({"issues": [{"id": 2}, {"id": 1}]}), base.state)
        assert not nothing.fire
        new = evaluate(self.CHECK, _json({"issues": [{"id": 3, "title": "x"}, {"id": 1}]}), nothing.state)
        assert new.fire and new.detail["new_items"] == [{"id": 3, "title": "x"}]
        assert new.state["seen"] == ["1", "2", "3"]

    def test_not_a_list(self):
        with pytest.raises(CheckError):
            evaluate(self.CHECK, _json({"issues": {"id": 1}}), None)

    def test_seen_ring_is_bounded(self):
        items = [{"id": i} for i in range(1500)]
        result = evaluate(self.CHECK, _json({"issues": items}), None, baseline=True)
        assert len(result.state["seen"]) == 1000 and result.state["seen"][-1] == "1499"


class TestChanged:
    def test_changed_fires_after_the_baseline(self):
        assert not evaluate(None, Content(text="a"), None, baseline=True).fire
        assert evaluate({"type": "changed"}, Content(text="b"), {"holds": True}).fire
        first = evaluate(None, Content(text="x"), None, mode="event")
        assert first.fire and first.key.endswith(Content(text="x").digest[:16])
