"""The pass plan, the latency fit and the ``auto`` verdicts built on them."""

from types import SimpleNamespace

import pytest

from docsgpt.decisions import features
from docsgpt.decisions.latency import Pass, SpeedProfile, fit, plan
from docsgpt.decisions.types import FeatureSpec, Shape


@pytest.mark.unit
class TestPlan:
    def test_one_hot_question_is_one_pass(self):
        assert plan(170, [30], "hot") == [Pass(-1, 0, 200, 0, single=True)]

    def test_several_questions_prefill_in_256_token_passes(self):
        assert plan(600, [30, 40], "hot") == [
            Pass(-1, 0, 256, 0), Pass(-1, 256, 512, 256), Pass(-1, 512, 600, 512),
            Pass(0, 0, 30, 600), Pass(1, 0, 40, 600),
        ]

    def test_background_never_takes_the_single_pass(self):
        assert plan(300, [30], "background") == [Pass(-1, 0, 256, 0), Pass(-1, 256, 300, 256), Pass(0, 0, 30, 300)]

    def test_long_suffixes_are_chunked_too(self):
        assert plan(10, [300, 5], "hot")[1:3] == [Pass(0, 0, 256, 10), Pass(0, 256, 300, 266)]


@pytest.mark.unit
class TestFit:
    def test_recovers_the_coefficients(self):
        c, a, b = 0.01, 0.0005, 2e-7
        passes = [(200, 0), (256, 0), (256, 256), (256, 512), (30, 768), (30, 768)]
        samples = [(n, k, c + n * (a + b * (k + n / 2))) for n, k in passes]
        assert fit(samples) == pytest.approx((c, a, b), rel=1e-6)

    def test_coefficients_are_never_negative(self):
        # timings that a free fit would explain with a negative per-pass cost
        assert all(v >= 0 for v in fit([(10, 0, 0.0), (100, 0, 0.2), (200, 0, 0.5)]))


def profile(c=0.01, a=0.001, b=0.0, overhead=50, drift=1.0) -> SpeedProfile:
    return SpeedProfile(c=c, a=a, b=b, overhead=overhead, threads=4, measured_at=0.0, drift=drift)


@pytest.mark.unit
class TestPredict:
    def test_sums_the_passes_of_the_plan(self):
        p = profile(c=0.1, a=0.001, b=1e-6)
        shape = Shape(state_tokens=450, question_tokens=(30, 40))
        expected = sum(p.pass_s(s.tokens, s.cached) for s in plan(500, [30, 40], "hot"))
        assert p.predict_s(shape) == pytest.approx(expected)
        assert p.predict_s(Shape(450, (30, 40), states=3)) == pytest.approx(3 * expected)

    def test_single_pass_rule(self):
        p = profile(c=1.0, a=0.0)
        assert p.predict_s(Shape(100, (20,))) == pytest.approx(1.0)  # one pass
        assert p.predict_s(Shape(100, (20,), lane="background")) == pytest.approx(2.0)  # prefill + suffix

    def test_a_long_single_pass_pays_for_attention_within_it(self):
        # each token attends to the rows before it in the same pass, so one long pass costs more than its tokens
        p = profile(c=0.01, a=0.0008, b=6e-7, overhead=44)
        n = 1259 + 44 + 30
        assert p.predict_s(Shape(1259, (30,))) == pytest.approx(0.01 + n * (0.0008 + 6e-7 * n / 2))
        assert p.predict_s(Shape(1259, (30,))) > 1.3 * (0.01 + n * 0.0008)

    def test_drift_scales_predictions(self):
        p = profile()
        before = p.predict_s(Shape(100, (20,)))
        step = Pass(-1, 0, 100, 0)
        for _ in range(200):
            p.observe(step, 2 * p.pass_s(step.tokens, step.cached))
        assert p.drift == pytest.approx(2.0, rel=1e-3)
        assert p.predict_s(Shape(100, (20,))) == pytest.approx(2 * before, rel=1e-3)

    @pytest.mark.parametrize("drift, steady", [(1.0, True), (0.67, True), (1.5, True), (0.6, False), (1.6, False)])
    def test_drift_band(self, drift, steady):
        assert profile(drift=drift).steady() is steady

    def test_report(self):
        report = profile().report()
        assert set(report) == {"threads", "measured_at", "drift", "guard_s", "relevance_s", "analytics_s"}
        assert report["measured_at"] == "1970-01-01T00:00:00+00:00"

    def test_wire_round_trip(self):
        sent = profile(c=0.02, b=1e-7, drift=1.1)
        got = SpeedProfile.from_wire(sent.wire())
        assert got == sent and got.predict_s(Shape(300, (30, 30))) == sent.predict_s(Shape(300, (30, 30)))

    @pytest.mark.parametrize("wire", [{}, {"c": 0.1, "a": 0.1, "b": "x", "overhead": 1}])
    def test_wire_rejects_a_partial_profile(self, wire):
        with pytest.raises((KeyError, ValueError)):
            SpeedProfile.from_wire(wire)


@pytest.fixture
def feature(monkeypatch):
    """A registered feature reading its mode and budget from a stand-in settings object."""
    fake = SimpleNamespace(TEST_FEATURE_MODE="auto", TEST_FEATURE_BUDGET=1.0)
    monkeypatch.setattr("docsgpt.core.settings.settings", fake)
    spec = FeatureSpec("test_feature", "TEST_FEATURE_MODE", "TEST_FEATURE_BUDGET", Shape(0, (0,)))
    monkeypatch.setattr(features, "_specs", {})
    monkeypatch.setattr(features, "_on", {})
    features.register(spec)
    return SimpleNamespace(settings=fake, spec=spec)


def costing(seconds: float) -> SpeedProfile:
    return profile(c=seconds, a=0.0, overhead=0)


@pytest.mark.unit
class TestVerdict:
    def test_on_at_the_budget_and_off_above_it(self, feature):
        assert features.verdict(feature.spec, costing(1.0))[0] is True
        features.reset()
        assert features.verdict(feature.spec, costing(1.01)) == (False, pytest.approx(1.01), "over_budget")

    def test_hysteresis(self, feature):
        assert features.verdict(feature.spec, costing(0.9))[0] is True
        assert features.verdict(feature.spec, costing(1.2))[0] is True  # on stays on up to 1.25x
        assert features.verdict(feature.spec, costing(1.3))[0] is False
        assert features.verdict(feature.spec, costing(1.2))[0] is False  # off comes back only under the budget

    def test_not_measured(self, feature):
        assert features.verdict(feature.spec, None) == (False, None, "not_measured")

    @pytest.mark.parametrize("mode", ["off", "monitor", "on"])
    def test_explicit_modes_win(self, feature, mode):
        feature.settings.TEST_FEATURE_MODE = mode
        assert features.effective(feature.spec, True, costing(9.0))[0] == mode

    def test_auto_resolves_to_the_declared_mode(self, feature):
        assert features.effective(feature.spec, True, costing(0.5))[0] == "on"
        shadow = FeatureSpec("shadow", "TEST_FEATURE_MODE", "TEST_FEATURE_BUDGET", Shape(0, (0,)), auto_mode="monitor")
        assert features.effective(shadow, True, costing(0.5))[0] == "monitor"
        assert features.effective(feature.spec, True, costing(5.0))[0] == "off"

    def test_everything_is_off_when_decisions_are(self, feature):
        feature.settings.TEST_FEATURE_MODE = "on"
        assert features.effective(feature.spec, False, costing(0.1))[0] == "off"

    def test_nothing_fits_when_every_auto_verdict_is_off(self, feature):
        assert features.nothing_fits(costing(5.0))
        assert not features.nothing_fits(costing(0.5))

    @pytest.mark.parametrize("mode", ["on", "monitor"])
    def test_an_explicit_feature_still_uses_the_model(self, feature, mode):
        other = FeatureSpec("other", "OTHER_MODE", "TEST_FEATURE_BUDGET", Shape(0, (0,)))
        feature.settings.OTHER_MODE = mode
        features.register(other)
        assert not features.nothing_fits(costing(5.0))

    def test_a_boolean_switch_reads_as_on_or_off(self, feature):
        switch = FeatureSpec("test_switch", "TEST_SWITCH", "TEST_FEATURE_BUDGET", Shape(0, (0,)))
        features.register(switch)
        feature.settings.TEST_SWITCH = False
        assert features.configured(switch) == "off" and features.nothing_fits(costing(5.0))
        feature.settings.TEST_SWITCH = True
        assert features.configured(switch) == "on"
        # A switch that is on uses the model, so the model was not loaded for nothing.
        assert not features.nothing_fits(costing(5.0))

    def test_without_an_auto_feature_nothing_is_judged(self, feature):
        feature.settings.TEST_FEATURE_MODE = "off"
        assert not features.nothing_fits(costing(5.0))

    def test_unset_mode_is_off(self, feature):
        feature.settings.TEST_FEATURE_MODE = None
        assert features.configured(feature.spec) == "off"


@pytest.mark.unit
class TestWire:
    def test_the_plan_crosses_the_wire(self):
        torch = SpeedProfile(c=0.01, a=0.001, b=0.0, overhead=50, threads=0, measured_at=0.0, plan="torch")
        assert SpeedProfile.from_wire(torch.wire()) == torch
        assert SpeedProfile.from_wire({**profile().wire(), "plan": None}).plan == "onnx"

    def test_a_torch_profile_predicts_on_its_plan(self):
        torch = SpeedProfile(c=1.0, a=0.0, b=0.0, overhead=0, threads=0, plan="torch")
        assert torch.predict_s(Shape(100, (20,))) == pytest.approx(2.0)  # the state, then the question
