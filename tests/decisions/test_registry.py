"""Model constants, model selection and the question registry, checked against the release files."""

import hashlib

import pytest

from docsgpt.core.settings import settings
from docsgpt.decisions import models
from docsgpt.decisions.backends.onnx import Engine
from docsgpt.decisions.models import V01, V02, calibration_hash, lookup, select, version
from docsgpt.decisions.questions import FIXED, Q, family, validate

from .conftest import FIXTURES

V02_ID, V01_ID = "arc53/arc-decide-0.4b-v0.2", "arc53/arc-decide-0.6b-v0.1"


@pytest.mark.unit
class TestModelConstants:
    def test_pins(self, release):
        assert V02.revision == release[V02_ID]["revision"] == "cb32fe9190a78aed4291fd8e8f087628dc5053df"
        assert V01.revision == release[V01_ID]["revision"] == "a03cd6bc45fa7b75e05489454e2084bd3516db17"

    def test_calibration_hashes_match_the_serving_files(self, serving_v02, serving_v01):
        assert calibration_hash(serving_v02) == V02.calibration == "c3bc72ff6907"
        assert calibration_hash(serving_v01) == V01.calibration == "680b3c70a92c"

    def test_prompt_and_state_limit_match_the_serving_files(self, serving_v02, serving_v01):
        for spec, serving in ((V02, serving_v02), (V01, serving_v01)):
            assert serving["prompt_hash"] == spec.prompt_hash == "78cfb276f93a"
            assert serving["max_state_tokens"] == spec.max_state_tokens == 2048

    def test_both_models_share_questions_and_tokenizer(self, release):
        for name in ("questions.json", "onnx/tokenizer.json"):
            assert release[V02_ID]["sha256"][name] == release[V01_ID]["sha256"][name]

    def test_heads_and_temperatures_match_the_serving_files(self, serving_v02, serving_v01):
        for spec, serving in ((V02, serving_v02), (V01, serving_v01)):
            fitted = {k: v for k, v in serving["temperature"].items() if k != "fit_sets"}
            assert spec.serving == {"heads": serving["heads"], "temperature": fitted}
            assert calibration_hash({**spec.serving, "temperature": serving["temperature"]}) == spec.calibration

    def test_memory_defaults_per_model(self):
        assert (V02.min_free_mb, V01.min_free_mb) == (1200, 3200)

    def test_version_string(self):
        assert version(V02) == "arc53/arc-decide-0.4b-v0.2/p78cfb276f93a/cc3bc72ff6907"
        assert version(V02, "abc") == "arc53/arc-decide-0.4b-v0.2/p78cfb276f93a/cabc"


@pytest.mark.unit
class TestSelection:
    def test_onnx_uses_v02_by_default(self, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_MODEL", None)
        assert select("onnx") is V02

    def test_decision_model_overrides_the_runtime_default(self, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_MODEL", "Arc53/Arc-Decide-0.6b-v0.1")
        assert select("onnx") is V01

    def test_vllm_and_a_silent_decide_server_use_v01(self, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_MODEL", None)
        assert select("vllm") is V01 and select("remote") is V01
        monkeypatch.setattr(settings, "DECISION_MODEL", V02.id)
        assert select("vllm") is V02

    def test_unregistered_model_selects_nothing(self, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_MODEL", "someone/else")
        assert select("onnx") is None
        assert lookup("someone/else") is None

    def test_registry_is_keyed_by_id(self):
        assert set(models.REGISTRY) == {V02_ID, V01_ID}


@pytest.mark.unit
class TestQuestions:
    def test_fixed_questions_are_the_release_wording(self, questions_json):
        assert set(FIXED) == {
            "relevant", "grade", "injection", "severity", "supported", "needs_retrieval", "needs_clarification",
            "complexity", "answer_status", "unanswered_reason", "request_type", "reaction", "sentiment",
            "frustrated", "asks_human", "goal_met", "tool_needed", "right_tool", "tool_succeeded", "result_used",
            "induced_by_untrusted",
        }
        for key, question in FIXED.items():
            assert question == questions_json[key], key

    def test_choice_options_keep_the_release_order(self, questions_json):
        for key in ("answer_status", "unanswered_reason", "request_type", "reaction"):
            assert list(FIXED[key]["criteria"]) == list(questions_json[key]["criteria"])

    def test_fixture_is_the_release_file(self, release):
        digest = hashlib.sha256((FIXTURES / "questions.json").read_bytes()).hexdigest()
        assert digest == release[V02_ID]["sha256"]["questions.json"]

    def test_q_names_the_trained_keys(self):
        assert Q.INJECTION is FIXED["injection"]
        assert Q.TOOL_SUCCEEDED is FIXED["tool_succeeded"]

    def test_every_fixed_question_validates(self):
        validate(dict(FIXED))

    def test_family(self):
        assert family("tag:billing") == "tag"
        assert family("relevant") == "relevant"


@pytest.mark.unit
class TestTemperature:
    def _engine(self, serving):
        engine = Engine.__new__(Engine)  # no session: only the temperature lookup is exercised
        engine.meta = serving
        return engine

    def test_instance_keys_use_their_familys_temperature(self, serving_v02):
        engine = self._engine(serving_v02)
        assert engine._temperature("noul", "tag:billing") == pytest.approx(0.926118728128794)
        assert engine._temperature("noul", "tag:billing") == engine._temperature("noul", "tag")

    def test_trained_keys_keep_their_own(self, serving_v02):
        assert self._engine(serving_v02)._temperature("noul", "relevant") == pytest.approx(0.926118728128794)

    def test_unknown_keys_use_the_head(self, serving_v02):
        assert self._engine(serving_v02)._temperature("choice", "route:x") == pytest.approx(1.4125375446227555)
