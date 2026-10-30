"""The published rules, ported from arc-decide's ``tests/test_analytics.py``, and the interval constants."""

import json
from pathlib import Path

import pytest

from docsgpt.analytics import calibration
from docsgpt.analytics import derive as D
from docsgpt.decisions.models import V01, V02, version

GOLDEN = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "analytics_schema.json").read_text(encoding="utf-8")
)
FULL = {"fully answered": 1.0}
DECLINED = {"declined, no information": 1.0}


def _turn(status, grounded=0.9, reaction=None, asks=0.0, frus=0.0):
    return D.Turn(answer_status=status, grounded=grounded, reaction=reaction, asks_human=asks, frustrated=frus)


@pytest.mark.unit
class TestDerivePort:
    def test_constants_match_arc_decide(self):
        assert list(D.NEGATIVE_REACTIONS) == GOLDEN["negative_reactions"]
        assert D.EXPERIENCE_WEIGHTS == GOLDEN["experience_weights"]
        assert list(D.GAP_TYPES) == GOLDEN["gap_types"]
        assert list(D.RESOLUTIONS) == GOLDEN["resolutions"]

    def test_gap_type_separates_not_retrieved_answer_missed_and_missing(self):
        reason = {"docs missing": 1.0}
        assert D.gap_type(DECLINED, reason, None, 0.0, 1.0)["not retrieved"] == pytest.approx(1.0)
        assert D.gap_type(DECLINED, reason, None, 1.0, 1.0)["answer missed"] == pytest.approx(1.0)
        assert D.gap_type(DECLINED, reason, None, 0.0, 0.0)["docs missing"] == pytest.approx(1.0)
        g = D.gap_type(FULL, None, 0.2, 0.9, 0.9)
        assert g["confidently ungrounded"] == pytest.approx(0.8) and g["none"] == pytest.approx(0.2)
        assert D.gap_type({"not a request": 1.0}, None, None, None, None)["none"] == pytest.approx(1.0)

    def test_gap_type_in_v1_puts_every_docs_missing_share_in_docs_missing(self):
        """Without re-retrieval (``answerable_from_corpus`` None) the docs-missing mass is weighted by the turn's
        unanswered mass and nothing splits off, whatever the retrieval relevance."""
        status = {"fully answered": 0.4, "partially answered": 0.3, "declined, no information": 0.2,
                  "asked a clarifying question": 0.1}
        g = D.gap_type(status, {"docs missing": 0.5, "out of scope": 0.5}, None, 0.9, None)
        assert g["docs missing"] == pytest.approx(0.3) and g["out of scope"] == pytest.approx(0.3)
        assert g["not retrieved"] == g["answer missed"] == g["confidently ungrounded"] == 0.0
        assert sum(g.values()) == pytest.approx(1.0)

    def test_resolution_rules_in_order(self):
        thanks = {"thanks or confirmation": 1.0}
        conv = D.Conversation([_turn(FULL), _turn(FULL, reaction=thanks)], goal_met=0.9, idle_hours=1)
        assert D.resolution(conv)["confirmed"] == pytest.approx(1.0)
        conv = D.Conversation([_turn(FULL, asks=1.0)], goal_met=0.9, idle_hours=48)
        assert D.resolution(conv)["escalated"] == pytest.approx(1.0)
        conv = D.Conversation([_turn(DECLINED)], goal_met=0.1, idle_hours=48)
        assert D.resolution(conv)["abandoned"] == pytest.approx(1.0)
        conv = D.Conversation([_turn(FULL)], goal_met=1.0, idle_hours=48)
        assert D.resolution(conv)["assumed"] == pytest.approx(1.0)
        conv = D.Conversation([_turn(FULL), _turn(FULL, reaction={"complaint": 1.0})], goal_met=1.0, idle_hours=48)
        assert D.resolution(conv)["unresolved"] == pytest.approx(1.0)
        conv = D.Conversation([_turn(FULL)], goal_met=1.0, idle_hours=2)
        assert D.resolution(conv)["pending"] == pytest.approx(1.0)
        r = D.resolution(D.Conversation([_turn({"fully answered": 0.6, "declined, no information": 0.4}, asks=0.3)],
                                        goal_met=0.7, idle_hours=30))
        assert sum(r.values()) == pytest.approx(1.0)

    def test_experience_is_explainable_and_bounded(self):
        bad = D.Conversation([_turn(FULL, frus=1.0), _turn(DECLINED, reaction={"re-ask": 1.0}, frus=1.0),
                              _turn(DECLINED, reaction={"complaint": 1.0}, asks=0.0)],
                             goal_met=0.0, idle_hours=48, confidently_ungrounded=[1.0, 0, 0])
        e = D.experience(bad)
        assert e["score"] == pytest.approx(1.0)
        assert e["score"] == max(1.0, 3 + sum(v for k, v in e.items() if k != "score"))
        good = D.Conversation([_turn(FULL), _turn(FULL, reaction={"thanks or confirmation": 1.0})], goal_met=1.0,
                              idle_hours=1)
        assert D.experience(good)["score"] == pytest.approx(4.0)

    def test_rate(self):
        m, lo, hi = D.rate([0.1] * 100, calibration_error=0.02)
        assert m == pytest.approx(0.1) and lo < 0.1 < hi and hi - lo > 0.04
        assert D.rate([]) == (0.0, 0.0, 1.0)


@pytest.mark.unit
class TestCalibration:
    def test_the_shipped_model_gets_its_own_constants(self):
        assert calibration.constants(version(V02)) is calibration.ECE_V02
        assert calibration.constants(version(V01)) is calibration.ECE_V01
        assert calibration.ece("goal_met", version(V02)) == 0.067

    def test_the_issue_table_is_v01s(self):
        assert calibration.ECE_V01 == {
            "answer_status": 0.044, "unanswered_reason": 0.132, "reaction": 0.100, "request_type": 0.154,
            "sentiment": 0.029, "frustrated": 0.023, "asks_human": 0.013, "goal_met": 0.057, "topic": 0.111,
            "tag": 0.025,
        }

    def test_unknown_versions_fall_back_to_the_repository_then_the_worst(self):
        recalibrated = f"{V02.id}/p{V02.prompt_hash}/c000000000000"
        assert calibration.constants(recalibrated) is calibration.ECE_V02
        assert calibration.constants("someone/else/pabc/cdef")["goal_met"] == 0.067
        assert calibration.constants(None)["topic"] == 0.111

    def test_derived_and_tag_labels_read_their_source(self):
        v = version(V02)
        assert calibration.ece("gap_type", v) == calibration.ece("unanswered_reason", v)
        assert calibration.ece("topic_effective", v) == calibration.ece("topic", v)
        assert calibration.ece("tag:a1b2c3d4", v) == calibration.ece("tag", v)
        with pytest.raises(KeyError):
            calibration.ece("resolution", v)

    def test_interval_from_aggregates_equals_derive_rate(self):
        probs = [0.9, 0.1, 0.7, 0.4, 0.95, 0.2]
        expected = D.rate(probs, calibration.ece("frustrated", version(V02)))
        got = calibration.interval("frustrated", sum(probs), len(probs), version(V02))
        assert got == pytest.approx(expected)
        assert calibration.interval("frustrated", 0.0, 0, version(V02)) == (0.0, 0.0, 1.0)
