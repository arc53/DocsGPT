"""API mode: the decision model behind an HTTP server, reached with the ``decide`` protocol or stock vLLM.

``DECISION_BASE_URL`` points at the sidecar ``docsgpt decide-server``, a host server on a Mac's GPU, ``arcd serve``
or vLLM. This module holds what both protocols share, and the ``decide`` protocol itself (``backends.vllm`` has the
other):

- **One pooled HTTP client per process,** built on first use and again in a forked child, so no connection crosses
  a fork. Each lane sends through its own thread pool, sized by the lane's concurrency
  (``DECISION_API_CONCURRENCY``, ``DECISION_BACKGROUND_CONCURRENCY``), so background work never takes a hot slot.
- **Deadlines.** A request's timeout is the time its call has left, and parts not done by the deadline come back
  ``timeout``. One retry, after a connection error or a 502/503/504, only while 30% of the call's budget remains.
- **The breaker** (``decisions.breaker``) skips calls for a cooldown after consecutive transport failures.
- **The key.** ``Authorization: Bearer`` ``DECISION_KEY`` when it is set, and no header otherwise. There is no
  fallback to ``INTERNAL_KEY``: it guards DocsGPT's internal API and must never reach whatever server
  ``DECISION_BASE_URL`` names. A 401 or 403 is logged once and makes the backend ``unavailable`` (``auth``) until a
  later probe is let in.
- **The probe.** ``GET /v1/models`` before the first call and every ``DECISION_PROBE_SECONDS``: the server's model,
  status and, from ``docsgpt decide-server``, its timing profile, plus the round trip. A server that reports no
  profile (``arcd serve``, vLLM) is timed through the endpoint with the synthetic calls the local backend times, at
  first use and whenever the breaker closes again. After asking ``docsgpt decide-server`` to load, first use keeps
  probing (backing off to every 5 s) until the server is ready or gives up, so a cold server's profile arrives
  without waiting for a call.
- **The tokenizer alone** (``files.ensure_tokenizer``, 11 MB) loads in the background, so token counts and
  truncation are computed here exactly as the server cuts the state.

Request bodies are never logged.
"""

from __future__ import annotations

import itertools
import logging
import os
import statistics
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from docsgpt.decisions import files, tokens
from docsgpt.decisions.backends import Outcome
from docsgpt.decisions.breaker import Breaker
from docsgpt.decisions.latency import (
    ANALYTICS, GUARD, RELEVANCE, TIMING_SINGLE, TIMING_STATE, TIMING_TEXT, SpeedProfile,
)
from docsgpt.decisions.models import ModelSpec, lookup, select, version
from docsgpt.decisions.questions import Q
from docsgpt.decisions.types import BACKEND_REASONS, Lane, ModelInfo, Request, Shape
from docsgpt.decisions.vendor.arc_decide import PROMPT_HASH, prefix_text, suffix_text, to_text
from docsgpt.decisions.vendor.arc_decide import Decider as ReleaseDecider

logger = logging.getLogger(__name__)

#: Statuses worth one more try: the server, or a proxy in front of it, is restarting.
RETRY_STATUSES = frozenset({502, 503, 504})

#: Share of a call's budget that must remain for a retry.
RETRY_MIN_SHARE = 0.3

#: Timeout of a probe or a load request, which no call waits on longer than its own deadline.
PROBE_TIMEOUT_S = 10.0

#: Pauses between probes while the server loads its model after the load request (the last one repeats).
LOAD_POLL_S = (0.5, 1.0, 2.0, 5.0)

#: How long first use follows a loading server; past it the periodic probe and ``warm`` take over.
LOAD_WAIT_S = 900.0

#: Deadline of each synthetic call of the timing run.
TIMING_TIMEOUT_S = 60.0

#: Probe round trips the median is taken over.
ROUND_TRIPS = 5

#: Item errors a server may send in place of an answer that keep their meaning here.
ITEM_REASONS = BACKEND_REASONS | {"timeout", "bad_item"}



def without_userinfo(url: str) -> tuple[str, Optional[tuple[str, str]]]:
    """``url`` without the ``user:password@`` part, and that part as basic-auth credentials (``None`` if absent).

    The credentials then travel as an ``Authorization`` header only and never appear in a URL that logs, errors or
    tracebacks may print.
    """
    from urllib.parse import unquote, urlsplit, urlunsplit

    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url, None
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{parts.port}" if parts.port else host
    credentials = (unquote(parts.username or ""), unquote(parts.password or ""))
    return urlunsplit(parts._replace(netloc=netloc)), credentials


def cleartext_public(url: str) -> bool:
    """Whether ``url`` is plain HTTP to a host that looks reachable beyond this machine and its private network.

    Loopback, private and link-local addresses, and single-label names (a compose or k8s service such as
    ``decider``) are taken as local; a dotted name or a public address is not.
    """
    import ipaddress
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "http" or not host or host == "localhost":
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." in host
    return not (address.is_loopback or address.is_private or address.is_link_local)

@dataclass
class Reply:
    """What one HTTP request came to.

    Attributes:
        data: The JSON body of a 200 that has the protocol's shape; ``None`` otherwise.
        reason: Why there is no ``data``: ``transport``, ``timeout``, ``auth``, ``queue_full``, or ``rejected`` (a
            4xx about the request itself).
        ms: Wall time, retries included.
    """

    data: Any = None
    reason: Optional[str] = None
    ms: float = 0.0


@dataclass
class RemoteProfile:
    """How long a call to the server takes, for ``auto`` and ``/api/admin/decisions``.

    A server that reports its own ``SpeedProfile`` (``docsgpt decide-server``) is predicted with it, plus the
    median probe round trip for each round of requests. Any other server is timed through the endpoint: ``c`` per
    round of requests (the round trip included) and ``a`` per token the server reads.

    Attributes:
        round_trip: Median probe round trip, in seconds.
        batch_size: States per request; vLLM sends one request per question instead (``per_question``).
        concurrency: Requests in flight at once, per lane.
        per_question: Whether every question of every state is its own request.
        server: The profile the server reported, if any.
        c: Seconds per round of requests, measured through the endpoint.
        a: Seconds per token read, measured through the endpoint.
        overhead: Tokens the prompt adds around a rendered state.
        measured_at: Unix time of the measurement.
    """

    round_trip: float
    batch_size: int
    concurrency: dict
    per_question: bool = False
    server: Optional[SpeedProfile] = None
    c: float = 0.0
    a: float = 0.0
    overhead: int = 0
    measured_at: float = field(default_factory=time.time)

    def rounds(self, shape: Shape) -> int:
        """Rounds of requests a call of this shape takes, one after another."""
        if self.per_question:
            requests = shape.states * len(shape.question_tokens)
        else:
            requests = -(-shape.states // self.batch_size)
        return -(-requests // self.concurrency[shape.lane])

    def predict_s(self, shape: Shape) -> float:
        """Seconds a call of this shape takes, transport included."""
        if self.server is not None:
            return self.server.predict_s(shape) + self.round_trip * self.rounds(shape)
        read = shape.states * (shape.state_tokens + self.overhead + sum(shape.question_tokens))
        return self.c * self.rounds(shape) + self.a * read

    def report(self) -> dict:
        """The local backend's fields, plus the round trip and who measured the profile."""
        measured_at = self.server.measured_at if self.server else self.measured_at
        return {
            "threads": self.server.threads if self.server else None,
            "measured_at": datetime.fromtimestamp(measured_at, timezone.utc).isoformat(timespec="seconds"),
            "drift": round(self.server.drift, 3) if self.server else 1.0,
            "guard_s": round(self.predict_s(GUARD), 3),
            "relevance_s": round(self.predict_s(RELEVANCE), 3),
            "analytics_s": round(self.predict_s(ANALYTICS), 3),
            "round_trip_ms": round(self.round_trip * 1000, 1),
            "measured_by": "server" if self.server else "client",
        }


class RemoteBackend:
    """What both protocols share: the client, lanes, deadlines, retries, the breaker, the probe and timing."""

    #: Key into ``models.DEFAULT_FOR_RUNTIME``: the model assumed until the server says otherwise.
    runtime_key = "remote"
    #: Whether calls need the tokenizer (vLLM builds the prompt on this side).
    needs_tokenizer = False
    #: Whether every question is its own request.
    per_question = False

    def __init__(self, transport: Any = None, clock: Callable[[], float] = time.monotonic):
        """Create an idle backend; nothing is sent or fetched.

        Args:
            transport: An ``httpx2`` transport (tests pass a ``MockTransport``).
            clock: Monotonic clock.
        """
        from docsgpt.core.settings import settings

        url, self._userinfo = without_userinfo((settings.DECISION_BASE_URL or "").rstrip("/"))
        self.base_url = url[: -len("/v1")] if url.endswith("/v1") else url
        self.spec: ModelSpec = select(self.runtime_key)
        self.calibration = self.spec.calibration
        self.revision = files.revision(self.spec)
        self.runtime = self.runtime_key
        self.profile: Optional[RemoteProfile] = None
        self._transport = transport
        self._clock = clock
        self._lock = threading.Condition()
        self._breaker = Breaker(settings.DECISION_BREAKER_FAILURES, settings.DECISION_BREAKER_COOLDOWN, clock)
        self._pid: Optional[int] = None
        self._client = None
        self._pools: dict[Lane, ThreadPoolExecutor] = {}
        self._round_trips: deque = deque(maxlen=ROUND_TRIPS)
        self._probing = False
        self._probed_at: Optional[float] = None  # last answered probe
        self._last_probe: Optional[float] = None  # last probe started
        self._refused: Optional[str] = None  # ``auth`` or ``wrong_model``, until a probe clears it
        self._server_status: Optional[str] = None
        self._server_reason: Optional[str] = None
        self._server_speed: Optional[SpeedProfile] = None
        self._client_timed = True  # the server reports no profile: time it through the endpoint
        self._tokenizer = None
        self._tokenizer_loading = False
        self._tokenizer_failed: Optional[tuple[str, float]] = None  # (reason, when)
        self._started = False
        self._timing = False
        self._timed_at: Optional[float] = None
        self._said: set[str] = set()

    def close(self) -> None:
        """Close the HTTP client and stop the lane pools (tests; a process keeps its backend for life)."""
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)
        if self._client is not None:
            self._client.close()
        self._pools, self._client, self._pid = {}, None, None

    # Identity and status

    def model_info(self, mode: str) -> ModelInfo:
        """The model the server runs, as last probed (as assumed before the first probe)."""
        return ModelInfo(id=self.spec.id, revision=self.revision, runtime=self.runtime, mode=mode,
                         prompt_hash=self.spec.prompt_hash, calibration=self.calibration,
                         version=version(self.spec, self.calibration))

    @property
    def status(self) -> str:
        """``idle``, ``loading``, ``ready``, ``degraded`` (the breaker is open) or ``unavailable``."""
        return self._state()[0]

    @property
    def reason(self) -> Optional[str]:
        """Why the backend is not ``ready``, when there is one."""
        return self._state()[1]

    def _state(self) -> tuple[str, Optional[str]]:
        if self._refused:
            return "unavailable", self._refused
        if self._breaker.open:
            return "degraded", "circuit_open"
        if self.needs_tokenizer and self._tokenizer is None and self._tokenizer_failed:
            return "unavailable", self._tokenizer_failed[0]
        if self._probed_at is None:
            return ("loading" if self._probing else "idle"), None
        if self.needs_tokenizer and self._tokenizer is None:
            return "loading", None
        if self._server_status in ("idle", "loading", "unavailable"):
            return self._server_status, self._server_reason
        return "ready", None

    # First use

    def warm(self) -> None:
        """Start the first-use work in the background (probe, load request, tokenizer, timing); never blocks.

        Later calls repeat only what failed, after ``DECISION_LOAD_RETRY_SECONDS``.
        """
        from docsgpt.core.settings import settings

        retry = settings.DECISION_LOAD_RETRY_SECONDS
        with self._lock:
            now = self._clock()
            first, self._started = not self._started, True
            tokenizer = (self._tokenizer_failed is not None and not self._tokenizer_loading
                         and now - self._tokenizer_failed[1] >= retry)
            retime = (self.profile is None and self._client_timed and self._probed_at is not None
                      and not self._timing and self._timed_at is not None and now - self._timed_at >= retry)
            follow = (not first and self._server_loading() and not self._probing and self._last_probe is not None
                      and now - self._last_probe >= retry)
        if first:
            self._spawn(self._first_use, "decision-api-start")
        elif follow:
            self._spawn(self._follow_load, "decision-api-load")
        elif tokenizer:
            self._spawn(self._load_tokenizer, "decision-tokenizer")
        elif retime:
            self._spawn(self._time, "decision-api-timing")

    def _first_use(self) -> None:
        self._probe()
        if self._probed_at is not None:
            self._load()
        self._load_tokenizer()
        if self._client_timed and self._probed_at is not None:
            self._time()
        self._follow_load()

    def _server_loading(self) -> bool:
        """Whether the server is still on its way to ready: loading, or idle without having given up."""
        return self._server_status == "loading" or (self._server_status == "idle" and self._server_reason is None)

    def _follow_load(self) -> None:
        """Probe until a server that was asked to load reports where it got.

        Without this the status stays at the first probe's ``idle`` until a call is let through, and features in
        ``auto`` mode, which wait for the server's profile, never make one.
        """
        end = self._clock() + LOAD_WAIT_S
        for i in itertools.count():
            if not self._server_loading() or self._refused or self._clock() >= end:
                return
            with self._lock:
                self._lock.wait(LOAD_POLL_S[min(i, len(LOAD_POLL_S) - 1)])
            if not self._probe():  # no answer: the periodic probe picks it up from here
                return

    def _load(self) -> None:
        """Ask the server to load its model now; only ``docsgpt decide-server`` has the route."""

    def _spawn(self, job: Callable[[], None], name: str) -> None:
        threading.Thread(target=job, name=name, daemon=True).start()

    def _load_tokenizer(self) -> None:
        with self._lock:
            if self._tokenizer is not None or self._tokenizer_loading:
                return
            self._tokenizer_loading = True
        tokenizer, failed = None, None
        try:
            from docsgpt.decisions.vendor.arc_decide_onnx import _Tokenizer

            tokenizer = _Tokenizer(files.ensure_tokenizer(self.spec))
        except files.FilesUnavailable as exc:
            failed = exc.reason
            self._log_once("tokenizer", logging.WARNING, "The decision model's tokenizer is unavailable (%s): %s",
                           exc.reason, exc)
        except Exception:  # noqa: BLE001 -- a broken file must not take the process down
            failed = "load_failed"
            logger.exception("Loading the decision model's tokenizer failed")
        if tokenizer is not None:
            tokens.use(tokenizer)
            self._said.discard("tokenizer")
        with self._lock:
            self._tokenizer, self._tokenizer_loading = tokenizer, False
            self._tokenizer_failed = (failed, self._clock()) if failed else None
            self._lock.notify_all()

    # Calls

    def run(self, requests: list[Request], lane: Lane, deadline: float) -> list[Outcome | str]:
        """Answer requests in order; each item is an ``Outcome`` or the reason it has none.

        Args:
            requests: Validated requests.
            lane: ``hot`` or ``background``.
            deadline: Clock time by which the call returns; items not answered by then come back ``timeout``.
        """
        start = self._clock()
        try:
            reason = self._admit(lane, deadline)
            return [reason] * len(requests) if reason else self._run(requests, lane, start, deadline)
        except Exception:  # noqa: BLE001 -- a decision never fails the request that asked for it
            logger.exception("A decision call to the server failed")
            return ["transport"] * len(requests)

    def _admit(self, lane: Lane, deadline: float) -> Optional[str]:
        """``None`` when a call may go out now; else the reason every item fails with."""
        self.warm()
        if self._probe_due():
            self._spawn(self._probe, "decision-api-probe")
        if self._refused:
            return self._refused
        if not self._breaker.allow():
            return "circuit_open"
        if self._probed_at is None:  # the first call's answers must carry the server's identity
            self._probe(max(0.0, min(PROBE_TIMEOUT_S, deadline - self._clock())))
            if self._refused:
                return self._refused
            if self._probed_at is None:
                return "transport"
        if self.needs_tokenizer:
            return self._wait_tokenizer(lane, deadline)
        return None

    def _probe_due(self) -> bool:
        """Whether a periodic probe should start now; only one starts per ``DECISION_PROBE_SECONDS``."""
        from docsgpt.core.settings import settings

        with self._lock:
            now = self._clock()
            if self._last_probe is None or now - self._last_probe < settings.DECISION_PROBE_SECONDS:
                return False
            self._last_probe = now
            return True

    def _wait_tokenizer(self, lane: Lane, deadline: float) -> Optional[str]:
        """Hot calls do not wait for the tokenizer; background calls do, until their deadline."""
        with self._lock:
            while self._tokenizer is None and self._tokenizer_failed is None and lane == "background":
                left = deadline - self._clock()
                if left <= 0:
                    return "timeout"
                self._lock.wait(left)
            if self._tokenizer is not None:
                return None
            return self._tokenizer_failed[0] if self._tokenizer_failed else "loading"

    def _run(self, requests: list[Request], lane: Lane, start: float, deadline: float) -> list[Outcome | str]:
        raise NotImplementedError

    def _gather(self, jobs: list[tuple[Callable[[], Any], Any]], lane: Lane, deadline: float) -> list[tuple[Any, Any]]:
        """Run jobs on the lane's pool: ``(tag, result)`` per job, in order, ``timeout`` for one not done in time."""
        self._ensure_process()
        pool = self._pools[lane]
        futures = [(pool.submit(job), tag) for job, tag in jobs]
        wait([f for f, _ in futures], timeout=max(0.0, deadline - self._clock()))
        out = []
        for future, tag in futures:
            if future.done() and not future.cancelled():
                try:
                    out.append((tag, future.result()))
                except Exception:  # noqa: BLE001 -- one failed request never fails the batch
                    logger.exception("A decision request failed")
                    out.append((tag, "transport"))
            else:
                future.cancel()  # one that has not started never sends
                out.append((tag, "timeout"))
        return out

    # HTTP

    def _ensure_process(self) -> None:
        """Build the HTTP client and the lane pools in this process; a forked child builds its own."""
        from docsgpt.core.settings import settings

        pid = os.getpid()
        if self._pid == pid:
            return
        import httpx2

        with self._lock:
            if self._pid == pid:
                return
            hot, background = settings.DECISION_API_CONCURRENCY, settings.DECISION_BACKGROUND_CONCURRENCY
            slots = hot + background + 1  # and the probe
            self._client = httpx2.Client(transport=self._transport,
                                         limits=httpx2.Limits(max_connections=slots, max_keepalive_connections=slots))
            self._pools = {
                "hot": ThreadPoolExecutor(hot, thread_name_prefix="decision-hot"),
                "background": ThreadPoolExecutor(background, thread_name_prefix="decision-background"),
            }
            self._pid = pid

    def _headers(self, lane: Optional[Lane], deadline: float) -> dict:
        from docsgpt.core.settings import settings

        if not settings.DECISION_KEY:
            return {}
        if cleartext_public(self.base_url):
            from urllib.parse import urlsplit

            self._log_once("cleartext", logging.WARNING,
                           "DECISION_KEY and the decided text go to %s over plain HTTP; use https for a decision "
                           "server outside this machine or its private network", urlsplit(self.base_url).hostname)
        return {"Authorization": f"Bearer {settings.DECISION_KEY}"}

    def _send(self, method: str, path: str, body: Any, *, lane: Optional[Lane], deadline: float, budget: float,
              check: Optional[Callable[[Any], bool]], optional: bool = False) -> Reply:
        """One request, retried once after a connection error or a 502/503/504 while the budget allows.

        Args:
            method: ``GET`` or ``POST``.
            path: Path under ``DECISION_BASE_URL``.
            body: JSON body, or ``None``.
            lane: The calling lane; ``None`` for the probe and the load request.
            deadline: Clock time the request must end by; the time left is its timeout.
            budget: Seconds the whole call was given, for the retry rule.
            check: Whether a 200's JSON has the protocol's shape; one that does not is a transport failure.
                ``None`` takes any 2xx, body or not.
            optional: A 404 or 405 means the server lacks the route, which is fine (``rejected``).
        """
        import httpx2

        from docsgpt.core.settings import settings

        self._ensure_process()
        started = self._clock()
        for attempt in range(1 + settings.DECISION_API_RETRIES):
            if attempt and deadline - self._clock() < RETRY_MIN_SHARE * budget:
                break
            left = deadline - self._clock()
            if left <= 0:
                return Reply(reason="timeout", ms=(self._clock() - started) * 1000)
            try:
                response = self._client.request(method, self.base_url + path, json=body, timeout=left,
                                                headers=self._headers(lane, deadline), auth=self._userinfo)
            except httpx2.TimeoutException:
                return self._failed("timeout", started)
            except httpx2.HTTPError as exc:
                self._log_once("unreachable", logging.WARNING, "The decision server is unreachable (%s)",
                               type(exc).__name__)
                continue
            if response.status_code in RETRY_STATUSES:
                self._log_once(f"http-{response.status_code}", logging.WARNING,
                               "The decision server answered HTTP %s", response.status_code)
                continue
            reply = self._read(response, started, check, optional)
            if lane is not None and reply.data is not None and "auth" in self._said:
                self._said.discard("auth")  # a probe proves nothing: /v1/models may not check the key
                logger.info("The decision server accepts this process's key again")
            return reply
        return self._failed("transport", started)

    def _read(self, response: Any, started: float, check: Optional[Callable[[Any], bool]], optional: bool) -> Reply:
        status = response.status_code
        ms = (self._clock() - started) * 1000
        if status in (401, 403):
            with self._lock:
                self._refused = "auth"
            self._log_once("auth", logging.WARNING, "The decision server refused this process's key (HTTP %s): set "
                           "DECISION_KEY to the key the server expects. Decisions fail open meanwhile.", status)
            return Reply(reason="auth", ms=ms)
        if status in (404, 405) and optional:
            self._succeeded()
            return Reply(reason="rejected", ms=ms)
        if status in (404, 405) or status >= 500:  # not a decision server at this address, or a broken one
            self._log_once(f"http-{status}", logging.WARNING, "The decision server answered HTTP %s", status)
            return self._failed("transport", started)
        if status == 429:
            self._succeeded()
            return Reply(reason="queue_full", ms=ms)
        if status >= 400:
            self._log_once(f"http-{status}", logging.WARNING, "The decision server refused a request (HTTP %s)", status)
            self._succeeded()
            return Reply(reason="rejected", ms=ms)
        if check is None:
            self._succeeded()
            return Reply(data=True, ms=ms)
        try:
            data = response.json()
            usable = bool(check(data))
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            usable = False
        if not usable:
            self._log_once("shape", logging.WARNING, "The decision server's reply is not in the expected shape")
            return self._failed("transport", started)
        self._succeeded()
        return Reply(data=data, ms=ms)

    def _succeeded(self) -> None:
        if self._breaker.success():
            self._said -= {key for key in self._said if key in ("breaker", "unreachable", "shape")
                           or key.startswith("http-5")}
            logger.info("The decision server answers again")
            if self._client_timed:
                self._spawn(self._time, "decision-api-timing")

    def _failed(self, reason: str, started: float) -> Reply:
        if self._breaker.failure():
            self._log_once("breaker", logging.WARNING, "The decision server failed %d times in a row; decisions are "
                           "skipped for %ss at a time until it answers", self._breaker.failures,
                           self._breaker.cooldown)
        return Reply(reason=reason, ms=(self._clock() - started) * 1000)

    def _log_once(self, key: str, level: int, message: str, *args: Any) -> None:
        if key not in self._said:
            self._said.add(key)
            logger.log(level, message, *args)

    # Probe

    def _probe(self, timeout: float = PROBE_TIMEOUT_S) -> bool:
        """``GET /v1/models``: the server's identity, status and profile, and the round trip.

        If a probe is already running, wait for it (up to ``timeout``) instead of sending another.

        Returns:
            Whether the server answered (a probe this one waited on counts as answered).
        """
        with self._lock:
            if self._probing:
                end = self._clock() + timeout
                while self._probing and self._clock() < end:
                    self._lock.wait(max(0.0, end - self._clock()))
                return True
            self._probing, self._last_probe = True, self._clock()
        try:
            started = self._clock()
            reply = self._send("GET", "/v1/models", None, lane=None, deadline=started + timeout, budget=timeout,
                               check=self._models_shape)
            if reply.data is None:
                return False
            self._round_trips.append(reply.ms / 1000)
            refused = self._identify(reply.data)
            with self._lock:
                self._refused, self._probed_at = refused, self._clock()
            if self._server_speed is not None:
                self.profile = self._profile(server=self._server_speed)
            elif self.profile is not None:
                self.profile.round_trip = statistics.median(self._round_trips)
            return True
        finally:
            with self._lock:
                self._probing = False
                self._lock.notify_all()

    def _models_shape(self, data: Any) -> bool:
        raise NotImplementedError

    def _identify(self, data: Any) -> Optional[str]:
        """Take the server's identity from its ``/v1/models``; returns ``wrong_model`` to refuse it."""
        raise NotImplementedError

    def _profile(self, **values: Any) -> RemoteProfile:
        from docsgpt.core.settings import settings

        return RemoteProfile(
            round_trip=statistics.median(self._round_trips) if self._round_trips else 0.0,
            batch_size=settings.DECISION_BATCH_SIZE,
            concurrency={"hot": settings.DECISION_API_CONCURRENCY,
                         "background": settings.DECISION_BACKGROUND_CONCURRENCY},
            per_question=self.per_question,
            **values,
        )

    # Timing through the endpoint

    def _time(self) -> None:
        """Time the server through the endpoint, for one that reports no profile of its own.

        The calls are the local backend's: a warm-up, the ~200-token guard twice and a 768-token state with two
        questions, in constant text. The guards' median and the long state give ``c`` and ``a``.
        """
        with self._lock:
            if self._timing or self._tokenizer is None:
                return
            self._timing = True
        try:
            samples = self._timing_samples()
            if samples is None:
                logger.info("Timing the decision server failed; features set to auto stay off until it is timed")
                return
            (n_guard, t_guard), (n_state, t_state) = samples
            a = max(0.0, (t_state - t_guard) / (n_state - n_guard)) if n_state > n_guard else 0.0
            c = max(0.0, t_guard - a * n_guard)
            self.profile = self._profile(c=c, a=a, overhead=len(self._tokenizer.encode(prefix_text(""))))
            report = self.profile.report()
            logger.info("Decision server timed: guard %.3fs, relevance chunk %.3fs, analytics turn %.3fs",
                        report["guard_s"], report["relevance_s"], report["analytics_s"])
        finally:
            with self._lock:
                self._timing, self._timed_at = False, self._clock()

    def _timing_samples(self) -> Optional[tuple[tuple[int, float], tuple[int, float]]]:
        """``(tokens read, seconds)`` of the guard (median of two) and of the long state; ``None`` on a failure."""
        enc, dec = self._tokenizer.encode, self._tokenizer.decode
        text = enc(TIMING_TEXT)
        filler = (text * (TIMING_STATE // len(text) + 1))[:TIMING_STATE]
        around = len(enc(prefix_text(""))) + len(enc(suffix_text(Q.RELEVANT)))
        guard = Request(dec(filler[: max(1, TIMING_SINGLE - around)]), {"relevant": Q.RELEVANT})
        state = Request(dec(filler), {"relevant": Q.RELEVANT, "relevant:again": Q.RELEVANT})
        times = []
        for request in (guard, guard, guard, state):
            began = self._clock()
            (outcome,) = self._run([request], "hot", began, began + TIMING_TIMEOUT_S)
            if not isinstance(outcome, Outcome):
                return None
            times.append((outcome.input_tokens, self._clock() - began))
        _, first, second, long_state = times  # the first call warms up and is not used
        return (first[0], statistics.median([first[1], second[1]])), long_state

    # Tokens

    def encode(self, request: Request) -> Optional[tuple[list[int], list[list[int]], bool]]:
        """The prompt's token ids as the release client builds them: the state cut to ``max_state_tokens`` inside
        the prefix, and each question's suffix encoded on its own.

        Returns:
            ``(prefix, suffixes, truncated)``, or ``None`` before the tokenizer has loaded.

        Raises:
            TypeError, ValueError: When the state does not render.
        """
        tokenizer = self._tokenizer
        if tokenizer is None:
            return None
        text = to_text(request.state)
        ids = tokenizer.encode(text)
        truncated = len(ids) > self.spec.max_state_tokens
        if truncated:  # as the release client's state_text, which this needs the flag from
            text = tokenizer.decode(ids[: self.spec.max_state_tokens]) + " ...[truncated]"
        suffixes = [tokenizer.encode(suffix_text(q)) for q in request.questions.values()]
        return tokenizer.encode(prefix_text(text)), suffixes, truncated


class DecideBackend(RemoteBackend):
    """The ``decide`` protocol: ``POST /v1/decide`` and ``/v1/decide/batch`` on ``docsgpt decide-server`` or
    ``arcd serve``.

    The server renders, truncates and calibrates. This side checks every answer against the question asked and
    rebuilds it from its probabilities with the release client's answer code, so both modes return the same
    shapes. ``arcd serve`` fails a whole batch on one bad item, so a part refused with a 4xx is sent again one item
    at a time.
    """

    def _headers(self, lane: Optional[Lane], deadline: float) -> dict:
        headers = super()._headers(lane, deadline)
        if lane is not None:  # DocsGPT's server queues by them; arcd serve ignores them
            headers["X-Decision-Priority"] = lane
            headers["X-Decision-Deadline-Ms"] = str(max(0, int((deadline - self._clock()) * 1000)))
        return headers

    def _load(self) -> None:
        if self._client_timed:  # a server that reports nothing about itself has no load route either
            return
        started = self._clock()
        self._send("POST", "/v1/load", None, lane=None, deadline=started + PROBE_TIMEOUT_S, budget=PROBE_TIMEOUT_S,
                   check=None, optional=True)

    def _run(self, requests: list[Request], lane: Lane, start: float, deadline: float) -> list[Outcome | str]:
        from docsgpt.core.settings import settings

        budget = max(0.0, deadline - start)
        out: list[Outcome | str] = ["bad_item"] * len(requests)
        todo = []
        for i, request in enumerate(requests):
            try:
                to_text(request.state)
            except (TypeError, ValueError):  # the state does not render, so it cannot be sent either
                continue
            todo.append(i)
        size = settings.DECISION_BATCH_SIZE
        parts = [todo[k : k + size] for k in range(0, len(todo), size)]
        submitted = self._clock()
        jobs = [(lambda part=part: self._part([requests[i] for i in part], lane, deadline, budget, submitted), part)
                for part in parts]
        for part, results in self._gather(jobs, lane, deadline):
            for i, result in zip(part, results if isinstance(results, list) else [results] * len(part)):
                out[i] = result
        return out

    def _part(self, requests: list[Request], lane: Lane, deadline: float, budget: float,
              submitted: float) -> list[Outcome | str]:
        """One request for a part of a batch; a part the server refuses is sent again item by item."""
        queue_ms = (self._clock() - submitted) * 1000
        bodies = [self._body(r) for r in requests]
        if len(bodies) == 1:
            reply = self._send("POST", "/v1/decide", bodies[0], lane=lane, deadline=deadline, budget=budget,
                               check=lambda data: isinstance(data, dict))
            items = [reply.data]
        else:
            reply = self._send("POST", "/v1/decide/batch", {"requests": bodies}, lane=lane, deadline=deadline,
                               budget=budget, check=lambda data: len(data["responses"]) == len(bodies))
            items = reply.data["responses"] if reply.data is not None else None
        if reply.reason == "rejected":
            if len(requests) == 1:
                return ["bad_item"]
            return [self._part([r], lane, deadline, budget, self._clock())[0] for r in requests]
        if reply.data is None:
            return [reply.reason] * len(requests)
        return [self._outcome(r, item, reply.ms, queue_ms) for r, item in zip(requests, items)]

    def _body(self, request: Request) -> dict:
        from docsgpt.core.settings import settings

        body = {"state": request.state, "questions": request.questions}
        if settings.DECISION_MODEL:
            body["model"] = settings.DECISION_MODEL
        return body

    def _outcome(self, request: Request, item: Any, ms: float, queue_ms: float) -> Outcome | str:
        if not isinstance(item, dict):
            return "bad_item"
        if "error" in item:
            return item["error"] if item["error"] in ITEM_REASONS else "bad_item"
        answers = _checked(item.get("answers"), request.questions)
        if answers is None:
            self._log_once("answers", logging.WARNING, "The decision server answered with the wrong question types")
            return "bad_item"
        counted = self.encode(request)
        if counted is None:  # the tokenizer is still loading: take the server's count
            usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
            truncated, input_tokens = False, int(usage.get("input_tokens") or 0)
        else:
            prefix, suffixes, truncated = counted
            input_tokens = len(prefix) + sum(map(len, suffixes))
        return Outcome(answers, ms, queue_ms, truncated, input_tokens)

    # Identity

    def _models_shape(self, data: Any) -> bool:
        entries = data["models"]
        return isinstance(entries, list) and bool(entries) and all(isinstance(e, dict) for e in entries)

    def _identify(self, data: Any) -> Optional[str]:
        from docsgpt.core.settings import settings

        wanted = settings.DECISION_MODEL
        entries = data["models"]
        entry = next((e for e in entries if wanted and str(e.get("name", "")).lower() == wanted.lower()), entries[0])
        prompt = entry.get("prompt_hash")
        if prompt is None:  # arcd serve: nothing to check, so the registry's identity stands
            spec = select("remote")
            self._log_once("identity", logging.INFO, "The decision server does not report its model; its answers "
                           "are taken as %s's (set DECISION_MODEL if it serves another)", spec.id)
            self._adopt(spec, spec.calibration, files.revision(spec), "remote", {})
            self._client_timed = True
            return None
        named = lookup(str(entry.get("name", "")))
        if prompt != PROMPT_HASH or named is None or (wanted and lookup(wanted) is not named):
            self._log_once("wrong_model", logging.WARNING, "The decision server runs %s (prompt %s), which this "
                           "client cannot use%s; decisions fail open", entry.get("name"), prompt,
                           f" (DECISION_MODEL is {wanted})" if wanted else "")
            return "wrong_model"
        self._said.discard("wrong_model")
        calibration = str(entry.get("calibration") or named.calibration)
        if calibration != named.calibration:
            self._log_once("calibration", logging.WARNING, "The decision server's %s has calibration %s, not the "
                           "pinned %s; answers are keyed by %s", named.id, calibration, named.calibration,
                           version(named, calibration))
        self._adopt(named, calibration, str(entry.get("revision") or files.revision(named)),
                    str(entry.get("runtime") or "remote"), entry)
        self._client_timed = False
        return None

    def _adopt(self, spec: ModelSpec, calibration: str, revision: str, runtime: str, entry: dict) -> None:
        speed = entry.get("speed")
        try:
            self._server_speed = SpeedProfile.from_wire(speed) if isinstance(speed, dict) else None
        except (KeyError, TypeError, ValueError):
            self._server_speed = None
        status, reason = entry.get("status"), entry.get("reason")
        self._server_status = status if isinstance(status, str) else None
        self._server_reason = reason if isinstance(reason, str) else None
        self.spec, self.calibration, self.revision, self.runtime = spec, calibration, revision, runtime


def _checked(answers: Any, questions: dict[str, dict]) -> Optional[dict[str, dict]]:
    """Every answer rebuilt from its probabilities, in the question's option order; ``None`` if any is not an
    answer to the question asked."""
    if not isinstance(answers, dict):
        return None
    out = {}
    for key, question in questions.items():
        answer, kind = answers.get(key), question.get("type", "noul")
        if not isinstance(answer, dict) or answer.get("type") != kind:
            return None
        if kind == "noul":
            p = answer.get("noul")
            probs = [p, 1.0 - p] if _number(p) else None
        else:
            criteria = question["criteria"]
            names = list(criteria) if kind == "choice" else [str(i) for i in range(len(criteria))]
            given = answer.get("probabilities")
            probs = [given[n] for n in names] if isinstance(given, dict) and set(given) == set(names) else None
            if kind == "choice" and answer.get("choice") not in names:
                probs = None
        if not probs or not all(_number(p) and 0.0 <= p <= 1.0 for p in probs) or abs(sum(probs) - 1.0) > 1e-3:
            return None
        out[key] = ReleaseDecider._answer(question, kind, [float(p) for p in probs])
    return out


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
