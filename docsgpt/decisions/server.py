"""``docsgpt decide-server``: the decision model behind the ``/v1/decide`` contract, in a process of its own.

Every shipped stack runs it as the ``decider`` sidecar, which the API and the Celery worker call in API mode
(``backends.http``); on a Mac it runs natively on the GPU (``--device mps``), which Docker cannot reach. It imports
``docsgpt.decisions`` and the settings only, never ``docsgpt.app``: no Flask, no faiss, no database pool.

- **Routes.** ``POST /v1/decide`` and ``/v1/decide/batch`` (``arcd serve``'s shapes, wire-compatible with TypeSafe
  System One), ``GET /v1/models`` with the model's identity, load status and timing profile, ``POST /v1/load`` to
  start loading, and ``GET /health``, which answers while the process runs, loaded or not. A batch item that
  cannot be answered comes back as ``{"error": <reason>}`` (``bad_item``, ``timeout``, ``loading``, ...) in its
  place; a full lane answers 429 with ``Retry-After``.
- **Lanes and deadlines.** ``X-Decision-Priority`` (``hot``, the default, or ``background``) picks the lane of the
  backend's gate, and states not started within ``X-Decision-Deadline-Ms`` come back ``timeout``.
- **Nothing loads until asked**: a call, ``POST /v1/load``, ``DECISION_PRELOAD``, or a feature in this process's
  settings set to anything but ``off``.
- **The key.** With ``DECISION_KEY`` set, every route but ``/health`` needs it as a bearer key, compared in constant
  time. Without one the server binds only to a loopback address.
- **Logs** hold counts and latencies, never what is decided.

``DecideService`` is the routes' work without HTTP, so the API's internal routes serve the same contract to Celery
workers in local mode (``docsgpt.api.internal.routes``).
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import time
from typing import Any, Callable, Optional

from docsgpt.decisions import features, files, questions
from docsgpt.decisions.backends import Outcome
from docsgpt.decisions.models import ModelSpec, lookup, select
from docsgpt.decisions.types import Lane, Request
from docsgpt.decisions.vendor.arc_decide import PROMPT_HASH

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7095

#: Seconds a client is told to wait after a 429.
RETRY_AFTER_S = 1


def loopback(host: str) -> bool:
    """Whether binding ``host`` keeps the server on this machine."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def authorized(header: Optional[str], key: Optional[str]) -> bool:
    """Whether an ``Authorization`` header carries ``key`` as a bearer key; anything passes when there is no key.

    The comparison takes the same time wherever the two differ.
    """
    if not key:
        return True
    scheme, _, given = (header or "").partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(given.strip().encode(), key.encode())


class DecideService:
    """What the routes do, apart from HTTP: parse, run on the backend, and shape the replies."""

    def __init__(self, backend: Any):
        """Serve ``backend`` (an ``OnnxBackend`` or a ``TorchBackend``), which nothing has loaded yet."""
        self.backend = backend

    @property
    def spec(self) -> ModelSpec:
        return self.backend.spec

    def models(self) -> dict:
        """``GET /v1/models``: the model, its identity and runtime, its load status and this machine's timing."""
        profile = self.backend.profile
        return {"models": [{
            "name": self.spec.id,
            "description": "arc-decide decision model (docsgpt decide-server)",
            "release_date": "",
            "revision": files.revision(self.spec),
            "prompt_hash": PROMPT_HASH,
            "calibration": self.backend.calibration,
            "runtime": self.backend.runtime,
            "max_state_tokens": self.spec.max_state_tokens,
            "status": self.backend.status,
            "reason": self.backend.reason,
            "speed": profile.wire() if profile is not None else None,
        }]}

    def load(self) -> dict:
        """``POST /v1/load``: start loading in the background (downloading first if needed)."""
        self.backend.warm()
        return {"status": self.backend.status}

    def health(self) -> dict:
        """``GET /health``: the process answers; the model's own status is in the body."""
        return {"status": "ok", "model": self.backend.status}

    def decide(self, body: Any, lane: Lane, deadline: float) -> tuple[int, dict]:
        """``POST /v1/decide``: one state's answers, as ``(HTTP status, body)``.

        Args:
            body: ``{"state", "questions", "model"?}``.
            lane: ``hot`` or ``background``.
            deadline: Monotonic time by which the state must have been answered.
        """
        request = self._parse(body)
        if isinstance(request, str):
            return 422, {"error": request}
        (outcome,) = self._run([request], lane, deadline)
        if outcome == "queue_full":
            return 429, {"error": "queue_full"}
        return 200, self._reply(outcome)

    def batch(self, body: Any, lane: Lane, deadline: float) -> tuple[int, dict]:
        """``POST /v1/decide/batch``: answers in request order, an ``{"error"}`` item for each one without.

        Args:
            body: ``{"requests": [<decide body>, ...]}``, up to ``DECISION_MAX_BATCH_STATES`` of them.
            lane: ``hot`` or ``background``.
            deadline: Monotonic time by which the states must have been answered.
        """
        from docsgpt.core.settings import settings

        items = body.get("requests") if isinstance(body, dict) else None
        if not isinstance(items, list) or not items:
            return 422, {"error": "bad_request", "detail": "the body needs a non-empty list of requests"}
        if len(items) > settings.DECISION_MAX_BATCH_STATES:
            return 422, {"error": "bad_request",
                         "detail": f"at most {settings.DECISION_MAX_BATCH_STATES} requests per batch"}
        parsed = [self._parse(item) for item in items]
        todo = [i for i, request in enumerate(parsed) if isinstance(request, Request)]
        outcomes = self._run([parsed[i] for i in todo], lane, deadline) if todo else []
        if outcomes and all(outcome == "queue_full" for outcome in outcomes):
            return 429, {"error": "queue_full"}
        replies: list[dict] = [{"error": request} for request in parsed]
        for i, outcome in zip(todo, outcomes):
            replies[i] = self._reply(outcome)
        return 200, {"responses": replies}

    def _parse(self, body: Any) -> Request | str:
        """The request in ``body``, or why it cannot be answered (``bad_item``, ``wrong_model``)."""
        if not isinstance(body, dict) or "state" not in body:
            return "bad_item"
        try:
            questions.validate(body.get("questions"))
        except ValueError:
            return "bad_item"
        model = body.get("model")
        if model is not None and (not isinstance(model, str) or lookup(model) is not self.spec):
            return "wrong_model"
        return Request(body["state"], body["questions"])

    def _run(self, requests: list[Request], lane: Lane, deadline: float) -> list[Outcome | str]:
        started = time.monotonic()
        outcomes = self.backend.run(requests, lane, deadline)
        answered = sum(isinstance(outcome, Outcome) for outcome in outcomes)
        logger.debug("Decided %d of %d states in the %s lane in %.0f ms", answered, len(requests), lane,
                     (time.monotonic() - started) * 1000)
        return outcomes

    def _reply(self, outcome: Outcome | str) -> dict:
        if isinstance(outcome, str):
            return {"error": outcome}
        return {"model": self.spec.id, "answers": outcome.answers,
                "usage": {"input_tokens": outcome.input_tokens, "output_tokens": 0}}


def lane_of(value: Optional[str]) -> Lane:
    """The lane an ``X-Decision-Priority`` header asks for: ``background``, else ``hot``."""
    return "background" if (value or "").strip().lower() == "background" else "hot"


def deadline_of(value: Optional[str], lane: Lane, now: float) -> float:
    """The call's deadline: ``X-Decision-Deadline-Ms`` from now, else the lane's default timeout."""
    from docsgpt.core.settings import settings

    try:
        return now + max(0.0, float(value)) / 1000
    except (TypeError, ValueError):
        default = settings.DECISION_HOT_TIMEOUT if lane == "hot" else settings.DECISION_BACKGROUND_TIMEOUT
        return now + default


def create_app(service: DecideService, clock: Callable[[], float] = time.monotonic):
    """The Starlette app over ``service``.

    Each lane admits as many calls at once as its backend queue holds (``DECISION_LOCAL_QUEUE``,
    ``DECISION_BACKGROUND_QUEUE``); one more gets 429 with ``Retry-After`` instead of a thread.

    Args:
        service: What the routes call.
        clock: Monotonic clock the deadlines are on; the backend's.
    """
    from starlette.applications import Starlette
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request as HttpRequest
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from docsgpt.core.settings import settings

    inflight: dict[Lane, int] = {"hot": 0, "background": 0}

    def refused(request: HttpRequest) -> Optional[JSONResponse]:
        if authorized(request.headers.get("authorization"), settings.DECISION_KEY):
            return None
        return JSONResponse({"error": "auth"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})

    async def body_of(request: HttpRequest) -> Any:
        try:
            return await request.json()
        except ValueError:
            return None

    def call(work: Callable[[Any, Lane, float], tuple[int, dict]]):
        async def handler(request: HttpRequest) -> JSONResponse:
            denied = refused(request)
            if denied:
                return denied
            lane = lane_of(request.headers.get("x-decision-priority"))
            deadline = deadline_of(request.headers.get("x-decision-deadline-ms"), lane, clock())
            body = await body_of(request)
            if body is None:
                return JSONResponse({"error": "bad_request", "detail": "the body is not JSON"}, status_code=400)
            limit = settings.DECISION_LOCAL_QUEUE if lane == "hot" else settings.DECISION_BACKGROUND_QUEUE
            if inflight[lane] >= limit:
                return _busy()
            inflight[lane] += 1
            try:
                status, payload = await run_in_threadpool(work, body, lane, deadline)
            finally:
                inflight[lane] -= 1
            return _busy() if status == 429 else JSONResponse(payload, status_code=status)

        return handler

    async def models(request: HttpRequest) -> JSONResponse:
        return refused(request) or JSONResponse(service.models())

    async def load(request: HttpRequest) -> JSONResponse:
        return refused(request) or JSONResponse(service.load(), status_code=202)

    async def health(request: HttpRequest) -> JSONResponse:
        return JSONResponse(service.health())

    return Starlette(routes=[
        Route("/v1/decide", call(service.decide), methods=["POST"]),
        Route("/v1/decide/batch", call(service.batch), methods=["POST"]),
        Route("/v1/models", models, methods=["GET"]),
        Route("/v1/load", load, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ])


def _busy():
    from starlette.responses import JSONResponse

    return JSONResponse({"error": "queue_full"}, status_code=429, headers={"Retry-After": str(RETRY_AFTER_S)})


class StartError(Exception):
    """The server cannot start with these options; the message says why and what to change."""


def build_backend(device: str):
    """The idle backend for ``device``: ONNX on ``cpu``, PyTorch on ``mps`` or ``cuda``.

    Raises:
        StartError: When ``DECISION_MODEL`` is unknown, or the torch runtime or the device is missing.
    """
    runtime = "onnx" if device == "cpu" else "torch"
    spec = select(runtime)
    if spec is None:
        from docsgpt.core.settings import settings

        raise StartError(f"DECISION_MODEL ({settings.DECISION_MODEL}) is not a decision model this version knows")
    if runtime == "onnx":
        from docsgpt.decisions.backends.onnx import OnnxBackend

        return OnnxBackend(spec)
    from docsgpt.core.optional_deps import is_available, missing_message

    for module in ("torch", "transformers"):
        if not is_available(module):
            raise StartError(missing_message(module, f"--device {device}"))
    import torch

    present = torch.backends.mps.is_available() if device == "mps" else torch.cuda.is_available()
    if not present:
        raise StartError(f"PyTorch sees no {device} device here; run with --device cpu")
    from docsgpt.decisions.backends.torch import TorchBackend

    return TorchBackend(spec, device)


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, device: Optional[str] = None) -> int:
    """Run the server until it is stopped.

    Args:
        host: Interface to bind; anything but loopback needs ``DECISION_KEY``.
        port: TCP port.
        device: ``cpu``, ``mps`` or ``cuda``; ``DECISION_DEVICE`` when not given.

    Returns:
        The process exit code: 2 when it cannot start with these options.
    """
    import uvicorn

    from docsgpt.core.logging_config import setup_logging
    from docsgpt.core.settings import settings

    setup_logging()
    device = device or settings.DECISION_DEVICE
    if not settings.DECISION_KEY and not loopback(host):
        logger.error("Refusing to serve the decision model on %s without DECISION_KEY: set it here and on the API "
                     "and worker (the shipped stacks pass INTERNAL_KEY), or bind 127.0.0.1", host)
        return 2
    try:
        backend = build_backend(device)
    except StartError as exc:
        logger.error("The decide-server cannot start: %s", exc)
        return 2
    service = DecideService(backend)
    if settings.DECISION_PRELOAD or any(features.configured(spec) != "off" for spec in features.specs()):
        backend.warm()
    logger.info("Serving %s (%s) on %s:%d; it loads when a feature first calls", backend.spec.id, backend.runtime,
                host, port)
    uvicorn.run(create_app(service), host=host, port=port, access_log=False, log_config=None)
    return 0
