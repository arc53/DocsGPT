"""The process-wide decision client: validation, the answer cache, and the mode that picks a backend.

``local`` runs the model in the API process (``backends.onnx``), which Celery task processes call through the
API's internal routes (``backends.http.ApiProcessBackend``); ``api`` calls the server at ``DECISION_BASE_URL`` with
the ``decide`` protocol (``backends.http``) or as stock vLLM (``backends.vllm``).

Callers get answers or ``None``, never an exception at run time: a model that is off, loading, refused or busy
answers ``None`` with a reason, and the feature falls back to what it does without the model. Caller bugs (a
malformed question, too many states) are the exception, raised synchronously as ``ValueError``.

Every call outside mode ``none`` is a ``decision`` span in the request's trace, a count in ``decision_usage``
(``docsgpt.decisions.usage``) and an OTel metric; none of them holds text. Decision calls never write
``token_usage`` rows: the model has no per-token price, and the rows would count against users' limits.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from docsgpt import tracing
from docsgpt.decisions import features, files, questions, usage
from docsgpt.decisions.models import ModelSpec, select, version
from docsgpt.decisions.types import BatchResult, Budget, Decision, Lane, ModelInfo, Request
from docsgpt.decisions.vendor.arc_decide import to_text
from docsgpt.tracing.otel import record_decision_metrics

logger = logging.getLogger(__name__)


def runtime() -> str:
    """What the selected model runs on, for ``models.select``: ``onnx`` here, ``vllm``, or ``remote`` for a
    ``decide`` server."""
    from docsgpt.core.settings import settings

    if _mode() != "api":
        return "onnx"
    return "vllm" if settings.DECISION_PROTOCOL == "vllm" else "remote"


def _mode() -> str:
    from docsgpt.core.settings import settings

    return settings.DECISION_MODE or ("api" if settings.DECISION_BASE_URL else "local")


def _in_worker() -> bool:
    """Whether this is a Celery task process; one that never imported the Celery app is not, so a process that only
    asks (``decide-server``, the CLI) does not import it."""
    celery_init = sys.modules.get("docsgpt.celery_init")
    return celery_init is not None and celery_init.in_worker()


def validate(requests: list[Request]) -> None:
    """Raise ``ValueError`` for a batch the model cannot take: more than ``DECISION_MAX_BATCH_STATES`` requests
    or any malformed question set."""
    from docsgpt.core.settings import settings

    if len(requests) > settings.DECISION_MAX_BATCH_STATES:
        raise ValueError(f"{len(requests)} states in one call; the limit is {settings.DECISION_MAX_BATCH_STATES}")
    for request in requests:
        if not isinstance(request, Request):
            raise ValueError("decide_batch takes Request objects")
        questions.validate(request.questions)


class _AnswerCache:
    """A per-process LRU of answers keyed on model version, rendered state and rendered questions."""

    def __init__(self) -> None:
        self._items: OrderedDict[str, tuple] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(model_version: str, request: Request) -> str:
        """The content key; question order is kept, since it is the order of the answers and of choice options."""
        payload = json.dumps(list(request.questions.items()), ensure_ascii=False)
        return hashlib.sha256("\x1f".join([model_version, to_text(request.state), payload]).encode()).hexdigest()

    def get(self, key: str) -> Optional[tuple]:
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key: str, value: tuple) -> None:
        from docsgpt.core.settings import settings

        size = settings.DECISION_CACHE_SIZE
        if size <= 0:
            return
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > size:
                self._items.popitem(last=False)


class DecisionClient:
    """What ``docsgpt.decisions.get_decider()`` returns: one per process, never ``None``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._backend = None
        self._cache = _AnswerCache()

    @property
    def mode(self) -> str:
        """``none``, ``local`` or ``api``; unset is ``api`` when ``DECISION_BASE_URL`` is set, else ``local``."""
        return _mode()

    @property
    def enabled(self) -> bool:
        """False when ``DECISION_MODE=none``: every call then answers ``None`` at once."""
        return self.mode != "none"

    def _spec(self) -> Optional[ModelSpec]:
        return select(runtime())

    def _get(self, create: bool):
        """The backend: created (nothing loaded or sent) on first use."""
        if self._backend is None and create:
            with self._lock:
                if self._backend is None:
                    self._backend = self._new_backend()
        return self._backend

    def _new_backend(self):
        if self.mode == "api":
            from docsgpt.core.settings import settings

            if settings.DECISION_PROTOCOL == "vllm":
                from docsgpt.decisions.backends.vllm import VllmBackend

                return VllmBackend()
            from docsgpt.decisions.backends.http import DecideBackend

            return DecideBackend()
        if _in_worker():  # task processes never load the model: they call the API process's
            from docsgpt.decisions.backends.http import ApiProcessBackend

            return ApiProcessBackend()
        from docsgpt.decisions.backends.onnx import OnnxBackend

        return OnnxBackend(self._spec())

    def _unusable(self) -> Optional[str]:
        """Why no call can be answered here, or ``None``."""
        if not self.enabled:
            return "off"
        if self._spec() is None:
            return "wrong_model"
        from docsgpt.core.settings import settings

        if self.mode == "api":
            return None if settings.DECISION_BASE_URL else "no_decider"
        if _in_worker() and not settings.INTERNAL_KEY:  # the API's internal routes refuse every call without it
            return "no_decider"
        return None

    def served(self):
        """The backend the API's internal routes serve to Celery workers: this process's own model, created (not
        loaded) on first use; ``None`` where this process runs none (mode ``none`` or ``api``, an unknown model, a
        worker)."""
        if self.mode != "local" or self._unusable() or _in_worker():
            return None
        return self._get(create=True)

    def decide(self, state: Any, questions: dict[str, dict], *, feature: str,
               budget: Budget = Budget.HOT) -> Optional[Decision]:
        """Every question about one state, or ``None``. See ``decide_batch``."""
        return self.decide_batch([Request(state, questions)], feature=feature, budget=budget)[0]

    def decide_batch(self, requests: list[Request], *, feature: str, budget: Budget = Budget.HOT) -> BatchResult:
        """Answer many states in one call, in order, each item independently.

        Args:
            requests: Up to ``DECISION_MAX_BATCH_STATES`` requests; each carries its own questions.
            feature: Short label of the calling feature (``rag_rerank``, ``injection_input``, ...).
            budget: Lane and deadline. The deadline covers waiting, loading and compute; items not reached by it
                come back ``None`` with ``timeout``.

        Returns:
            One ``Decision`` or ``None`` per request, with ``reasons`` and a batch ``status``.

        Raises:
            ValueError: For caller bugs, whatever the mode: see ``questions.validate``.
        """
        started = time.monotonic()
        validate(requests)
        if not requests:
            return BatchResult([], [])
        if not self.enabled:  # nothing is asked, so nothing is traced or counted
            return self._logged(feature, BatchResult([None] * len(requests), ["off"] * len(requests)))
        with tracing.span(tracing.KIND_DECISION, f"decision {feature}") as span:
            result, predicted_ms = self._decide(requests, budget, started)
            self._report(span, feature, budget.lane, requests, result, time.monotonic() - started, predicted_ms)
        return self._logged(feature, result)

    def _decide(self, requests: list[Request], budget: Budget, started: float) -> tuple[BatchResult, Optional[float]]:
        """The answers, and the time the backend predicted for the states it ran (``None`` when it gave none)."""
        reason = self._unusable()
        if reason:
            return BatchResult([None] * len(requests), [reason] * len(requests)), None
        backend = self._get(create=True)
        info = self.model_info()
        decisions: list[Optional[Decision]] = [None] * len(requests)
        reasons: list[Optional[str]] = [None] * len(requests)
        keys: list[Optional[str]] = [None] * len(requests)
        todo = []
        for i, request in enumerate(requests):
            try:
                keys[i] = self._cache.key(info.version, request)
            except (TypeError, ValueError):  # the state does not render
                reasons[i] = "bad_item"
                continue
            hit = self._cache.get(keys[i])
            if hit is None:
                todo.append(i)
            else:
                answers, truncated, input_tokens = hit
                decisions[i] = Decision(answers, info, cached=True, truncated=truncated, input_tokens=input_tokens)
        predicted = []
        if todo:
            outcomes = backend.run([requests[i] for i in todo], budget.lane, started + budget.timeout())
            # a load or the first probe during the call may have changed the identity; the answers are that model's
            before, info = info, self.model_info()
            for i, outcome in zip(todo, outcomes):
                if isinstance(outcome, str):
                    reasons[i] = outcome
                    continue
                decisions[i] = Decision(outcome.answers, info, outcome.ms, outcome.queue_ms,
                                        truncated=outcome.truncated, input_tokens=outcome.input_tokens)
                if outcome.predicted_ms is not None:
                    predicted.append(outcome.predicted_ms)
                key = keys[i] if info.version == before.version else self._cache.key(info.version, requests[i])
                self._cache.put(key, (outcome.answers, outcome.truncated, outcome.input_tokens))
        return BatchResult(decisions, reasons), (sum(predicted) if predicted else None)

    def _report(self, span: Any, feature: str, lane: Lane, requests: list[Request], result: BatchResult,
                seconds: float, predicted_ms: Optional[float]) -> None:
        """Describe a finished call on its span, in the usage counts and in the OTel metrics: numbers only."""
        info = self.model_info()
        answered = [d for d in result if d is not None]
        computed = [d for d in answered if not d.cached]
        reason = next((r for r in result.reasons if r), None)
        input_tokens = sum(d.input_tokens for d in computed)
        span.set(
            **{
                "gen_ai.operation.name": "decide",
                "gen_ai.request.model": info.id if info else None,
                "docsgpt.decision.feature": feature,
                "docsgpt.decision.mode": self.mode,
                "docsgpt.decision.runtime": info.runtime if info else None,
                "docsgpt.decision.version": info.version if info else None,
                "docsgpt.decision.lane": lane,
                "docsgpt.decision.states": len(result),
                "docsgpt.decision.questions": sum(len(r.questions) for r in requests),
                "docsgpt.decision.answered": len(answered),
                "docsgpt.decision.cached": len(answered) - len(computed),
                "docsgpt.decision.truncated": sum(d.truncated for d in answered),
                "docsgpt.decision.input_tokens": input_tokens,
                "docsgpt.decision.queue_ms": round(max((d.queue_ms for d in computed), default=0.0), 1),
                "docsgpt.decision.predicted_ms": None if predicted_ms is None else round(predicted_ms, 1),
                "docsgpt.decision.status": result.status,
                "docsgpt.decision.reason": reason,
            }
        )
        if not answered:
            span.end(tracing.STATUS_SKIPPED)
        usage.count(feature, self.mode, info.version if info else None, result.status, states=len(result),
                    answered=len(answered), ms=seconds * 1000, queue_ms=sum(d.queue_ms for d in computed))
        record_decision_metrics(feature=feature, status=result.status, model=info.id if info else None,
                                input_tokens=input_tokens, duration_s=seconds,
                                error_type=None if answered else (reason or result.status))

    @staticmethod
    def _logged(feature: str, result: BatchResult) -> BatchResult:
        if result.status != "ok":
            logger.debug("Decision call for %s: %s (%s)", feature, result.status,
                         ", ".join(sorted({r for r in result.reasons if r})))
        return result

    def warm(self) -> None:
        """Start loading the model in the background; never blocks, and does nothing where calls cannot run."""
        if self._unusable() is None:
            self._get(create=True).warm()

    def probe(self, timeout: float = 5.0) -> Optional[bool]:
        """Ask the decision server once what it runs and how it is (``docsgpt decisions status``).

        Returns:
            Whether it answered; ``None`` where calls do not go to a server (local model, off, misconfigured).
        """
        if self.mode != "api" or self._unusable():
            return None
        return self._get(create=True)._probe(timeout)

    def model_info(self) -> Optional[ModelInfo]:
        """The model calls go to, without loading it; ``None`` when off or misconfigured."""
        spec = self._spec()
        if not self.enabled or spec is None:
            return None
        backend = self._get(create=False)
        if self.mode == "api" or _in_worker():
            if backend is not None:  # what the server (in a worker, the API) reported at its last probe
                return backend.model_info(self.mode)
            from docsgpt.decisions.backends.http import API_PROCESS

            label = runtime() if self.mode == "api" else API_PROCESS
            return ModelInfo(id=spec.id, revision=files.revision(spec), runtime=label, mode=self.mode,
                             prompt_hash=spec.prompt_hash, calibration=spec.calibration, version=version(spec))
        calibration = backend.calibration if backend else spec.calibration
        return ModelInfo(id=spec.id, revision=files.revision(spec), runtime=f"onnx-{spec.onnx_dtype}",
                         mode=self.mode, prompt_hash=spec.prompt_hash, calibration=calibration,
                         version=version(spec, calibration))

    def model_version(self) -> Optional[str]:
        """``<repo>/p<prompt_hash>/c<calibration>``, available without loading; ``None`` when off."""
        info = self.model_info()
        return info.version if info else None

    def speed(self):
        """This machine's ``SpeedProfile`` (in API mode the server's ``RemoteProfile``), or ``None`` before the
        model has been timed."""
        backend = self._get(create=False)
        return backend.profile if backend and self.enabled else None

    def status(self) -> dict:
        """The state ``/api/admin/decisions`` reports (``/api/config`` shows only ``available``).

        Reads only this process's own state: no load, no network.
        """
        info = self.model_info()
        backend = self._get(create=False)
        unusable = self._unusable() if self.enabled else None
        if not self.enabled:
            state, reason = "off", None
        elif info is None:
            state, reason = "unavailable", "wrong_model"
        elif unusable:
            state, reason = "unavailable", unusable
        elif backend is None:
            state, reason = "idle", None
        else:
            state, reason = backend.status, backend.reason
        profile = self.speed()
        verdicts = {}
        for spec in features.specs():
            effective, predicted, why = features.effective(spec, self.enabled, profile)
            verdicts[spec.name] = {
                "mode": features.configured(spec),
                "effective": effective,
                "predicted_s": None if predicted is None else round(predicted, 3),
                "budget_s": _budget(spec),
                "reason": why,
            }
        return {
            "available": self.enabled and state not in ("unavailable", "off"),
            "mode": self.mode,
            "status": state,
            "reason": reason,
            "model": info.id if info else None,
            "version": info.version if info else None,
            "runtime": info.runtime if info else None,
            "speed": profile.report() if profile else None,
            "features": verdicts,
        }


def _budget(spec) -> Optional[float]:
    from docsgpt.core.settings import settings

    value = getattr(settings, spec.budget_setting, None)
    return None if value is None else float(value)
