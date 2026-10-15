"""The decision model on onnxruntime, in this process: one session, a hot and a background KV buffer, one gate.

The vendored release client builds the session, the prompt and the answers; this module adds what DocsGPT needs
around it:

- **Lifecycle.** Nothing loads until ``warm()`` or the first call. The load (download, memory guard, session,
  timing run) runs on its own thread; hot calls meanwhile return ``loading`` and background calls wait. A failed
  load is retried after ``DECISION_LOAD_RETRY_SECONDS``.
- **Two buffers on one session.** A second release ``Decider`` would hold a second copy of the weights. The hot
  buffer is the client's own; the background one is made on first use and dropped after a minute idle. A buffer
  keeps the rows of the longest state it has held, so a hot call longer than ``HOT_KEEP_TOKENS`` leaves a fresh
  buffer behind: otherwise one long hot call plus a long background call hold two full-size buffers (~220 MB more
  than one at 2,048 tokens) for the life of the process.
- **Passes, not calls.** Each call runs the pass plan in ``speed.plan`` one pass at a time through the gate, so
  hot work waits at most one background pass, and every pass is timed into the latency model.
- **Temperatures by family.** ``tag:billing`` is answered with ``tag``'s fitted temperature; the release client
  only matches whole keys.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from docsgpt.decisions import files, memory, tokens
from docsgpt.decisions.gate import Gate, GateTimeout
from docsgpt.decisions.models import ModelSpec, calibration_hash
from docsgpt.decisions.questions import FIXED, Q, family
from docsgpt.decisions.latency import Pass, SpeedProfile, fit, plan
from docsgpt.decisions.types import Lane, Request
from docsgpt.decisions.vendor.arc_decide import PROMPT_HASH, prefix_text, suffix_text, to_text
from docsgpt.decisions.vendor.arc_decide_onnx import Decider as ReleaseDecider
from docsgpt.decisions.vendor.arc_decide_onnx import SharedKV

logger = logging.getLogger(__name__)

#: Seconds without background work after which the background buffer is freed.
BACKGROUND_IDLE_S = 60.0

#: Tokens of KV the hot buffer may keep after a call; longer calls get a fresh buffer afterwards. Guard and gate
#: calls fit, so they never reallocate; a long hot call pays a few milliseconds to map its rows again.
HOT_KEEP_TOKENS = 512

#: The timing run's state: constant text, never user data.
TIMING_TEXT = (
    "The service stores each document as a sequence of short passages. A search embeds the question, compares it "
    "with every passage of the selected sources and returns the closest ones, which the assistant reads before it "
    "answers. Passages keep their headings, so a result can be traced back to the section it came from. "
)
#: Tokens of the timing run's single-pass call and of its multi-pass state.
TIMING_SINGLE, TIMING_STATE = 200, 512


class LoadRefused(Exception):
    """The model cannot be loaded here (``memory``, ``wrong_model``)."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class Engine(ReleaseDecider):
    """The release ONNX client with family temperatures and extra KV buffers on its one session."""

    def __init__(self, path: str, threads: int):
        super().__init__(path, threads=threads)
        self.threads = threads

    def _temperature(self, kind: str, name: str) -> float:
        return super()._temperature(kind, family(name))

    def new_buffer(self) -> SharedKV:
        """Another low-memory KV buffer bound to this session, as the client's own ``kv`` is."""
        import onnxruntime as ort

        return SharedKV(self.session, self.past_names, self.present_names, self._kv_shape,
                        ort.OrtValue.ortvalue_from_numpy, self.kv.run_options)

    def answer(self, logits: Any, key: str, question: dict) -> dict:
        """The wire-shaped answer to one question from its label logits."""
        kind, p = self._probs(logits, key, question)
        return self._answer(question, kind, p)


@dataclass
class Outcome:
    """One answered request, before it becomes a ``Decision``."""

    answers: dict[str, dict]
    ms: float
    queue_ms: float
    truncated: bool
    input_tokens: int


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def cpu_budget(root: Path = Path("/"), cpus: Optional[list[int]] = None) -> int:
    """Threads worth running: the CPUs this process may use, capped by its cgroup quota and by physical cores.

    onnxruntime's own default counts the host's cores (5.8x slower in a 4-CPU container on a 48-CPU host), and
    hyperthreads do not help: 6 threads beat 12 on a 6-core machine.

    Args:
        root: Filesystem root to read ``/sys`` under (tests point it at a fake tree).
        cpus: The CPUs this process may run on; its affinity by default.
    """
    if cpus is None:
        cpus = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else list(range(os.cpu_count() or 1))
    budget = len(cpus)
    v2 = (_read(root / "sys/fs/cgroup/cpu.max") or "").split()
    v1 = (_read(root / "sys/fs/cgroup/cpu/cpu.cfs_quota_us"), _read(root / "sys/fs/cgroup/cpu/cpu.cfs_period_us"))
    if len(v2) == 2 and v2[0].isdigit() and v2[1].isdigit():
        budget = min(budget, max(1, int(v2[0]) // int(v2[1])))
    elif v1[0] and v1[1] and v1[0].isdigit() and v1[1].isdigit():  # "-1" is no quota
        budget = min(budget, max(1, int(v1[0]) // int(v1[1])))
    cores = set()
    for cpu in cpus:
        topology = root / f"sys/devices/system/cpu/cpu{cpu}/topology"
        core, package = _read(topology / "core_id"), _read(topology / "physical_package_id")
        if core is None or package is None:
            return max(1, budget)
        cores.add((package, core))
    return max(1, min(budget, len(cores)))


def _check_questions(folder: Path) -> None:
    """Warn when the model's own question wording differs from the registry: a newer model needs both updated."""
    for candidate in (folder.parent / "questions.json", folder / "questions.json"):
        if candidate.is_file():
            shipped = json.loads(candidate.read_text(encoding="utf-8"))
            for key, question in FIXED.items():
                if shipped.get(key) != question:
                    logger.warning("The decision model's question %r differs from docsgpt.decisions.questions", key)
            return


class OnnxBackend:
    """The decision model in this process, loaded on first use."""

    def __init__(self, spec: ModelSpec, open_engine: Optional[Callable[["OnnxBackend"], Engine]] = None,
                 clock: Callable[[], float] = time.monotonic):
        """Create an idle backend; nothing is read or loaded.

        Args:
            spec: The model to load.
            open_engine: Builds the engine (tests pass a fake); the default downloads and loads the files.
            clock: Monotonic clock (tests pass a fake one).
        """
        from docsgpt.core.settings import settings

        self.spec = spec
        self.calibration = spec.calibration
        self.status = "idle"
        self.reason: Optional[str] = None
        self.profile: Optional[SpeedProfile] = None
        self._open_engine = open_engine or OnnxBackend._open
        self._clock = clock
        self._engine: Optional[Engine] = None
        self._cond = threading.Condition()
        self._failed_at = 0.0
        self._gate = Gate(settings.DECISION_BACKGROUND_SHARE, clock)
        self._limits: dict[Lane, int] = {
            "hot": settings.DECISION_LOCAL_QUEUE, "background": settings.DECISION_BACKGROUND_QUEUE,
        }
        self._inside: dict[Lane, int] = {"hot": 0, "background": 0}
        self._buffer_locks: dict[Lane, threading.Lock] = {"hot": threading.Lock(), "background": threading.Lock()}
        self._background: Optional[SharedKV] = None
        self._background_used = 0.0
        self._idle_timer: Optional[threading.Timer] = None

    # Loading

    def warm(self) -> None:
        """Start loading in the background unless loaded, loading, or inside the retry window of a failure."""
        from docsgpt.core.settings import settings

        with self._cond:
            if self.status in ("loading", "ready"):
                return
            if self.status == "unavailable" and self._clock() - self._failed_at < settings.DECISION_LOAD_RETRY_SECONDS:
                return
            self.status, self.reason = "loading", None
        threading.Thread(target=self._load, name="decision-model-load", daemon=True).start()

    def _open(self) -> Engine:
        from docsgpt.core.settings import settings

        folder = files.ensure_onnx(self.spec)
        need = settings.DECISION_MIN_FREE_MB if settings.DECISION_MIN_FREE_MB is not None else self.spec.min_free_mb
        free = memory.headroom_mb()
        if free is None:
            logger.info("Memory headroom is unknown here; loading the decision model without the memory guard")
        elif free < need:
            raise LoadRefused("memory", f"{free:.0f} MB free, the decision model needs {need} MB (DECISION_MIN_FREE_MB)")
        serving = json.loads((folder / "arcd_serving.json").read_text(encoding="utf-8"))
        if serving.get("prompt_hash") != PROMPT_HASH:
            raise LoadRefused("wrong_model", f"the model was trained on prompt {serving.get('prompt_hash')}, "
                                             f"this client builds {PROMPT_HASH}")
        if not serving.get("max_state_tokens"):  # the release client would fall back to 1,400 tokens
            raise LoadRefused("wrong_model", "the model's arcd_serving.json has no max_state_tokens")
        _check_questions(folder)
        return Engine(str(folder), threads=settings.DECISION_THREADS or cpu_budget())

    def _load(self) -> None:
        start = self._clock()
        try:
            engine = self._open_engine(self)
            calibration = calibration_hash(engine.meta)
            if calibration != self.spec.calibration:
                logger.warning("Decision model %s has calibration %s, not the pinned %s; answers are keyed by it",
                               self.spec.id, calibration, self.spec.calibration)
            profile = self._time(engine)
        except (files.FilesUnavailable, LoadRefused) as exc:
            self._fail(exc.reason, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 -- a broken file or runtime must not take the process down
            logger.exception("Loading the decision model failed")
            self._fail("load_failed", str(exc))
            return
        tokens.use(engine.tokenizer)
        with self._cond:
            self._engine, self.profile, self.calibration = engine, profile, calibration
            self.status, self.reason = "ready", None
            self._cond.notify_all()
        report = profile.report()
        logger.info("Decision model %s ready in %.1fs on %d threads; predicted guard %.2fs, relevance chunk %.2fs",
                    self.spec.id, self._clock() - start, profile.threads, report["guard_s"], report["relevance_s"])

    def _fail(self, reason: str, message: str) -> None:
        from docsgpt.core.settings import settings

        logger.warning("Decision model unavailable (%s): %s. Decision features fail open; retrying in %ss.",
                       reason, message, settings.DECISION_LOAD_RETRY_SECONDS)
        with self._cond:
            self.status, self.reason, self._failed_at = "unavailable", reason, self._clock()
            self._cond.notify_all()

    def _time(self, engine: Engine) -> SpeedProfile:
        """The timing run: fixed synthetic calls through the real pass plan, fitted into a ``SpeedProfile``."""
        enc = engine.tokenizer.encode
        text = enc(TIMING_TEXT)
        filler = (text * (TIMING_STATE // len(text) + 1))[:TIMING_STATE]
        question = enc(suffix_text(Q.RELEVANT))
        guard = (filler[: TIMING_SINGLE - len(question)], [question])
        state = (filler, [question, question])
        buf = engine.new_buffer()  # dropped afterwards: the timing state is longer than HOT_KEEP_TOKENS
        buf.reserve(TIMING_STATE + len(question))
        samples = []
        for i, (prefix, suffixes) in enumerate([guard, guard, guard, state]):
            for step in plan(len(prefix), [len(s) for s in suffixes], "hot"):
                start = self._clock()
                _run_pass(buf, prefix, suffixes, step)
                if i:  # the first call warms up and is not timed
                    samples.append((step.tokens, step.cached, self._clock() - start))
        c, a, b = fit(samples)
        return SpeedProfile(c, a, b, overhead=len(enc(prefix_text(""))), threads=engine.threads)

    def _wait_ready(self, lane: Lane, deadline: float) -> Optional[str]:
        """``None`` once loaded; else the reason to give up. Hot calls never wait for a load."""
        self.warm()
        with self._cond:
            while self.status == "loading" and lane == "background":
                left = deadline - self._clock()
                if left <= 0:
                    return "timeout"
                self._cond.wait(left)
            if self.status == "ready":
                return None
            return "loading" if self.status == "loading" else self.reason

    # Calls

    def run(self, requests: list[Request], lane: Lane, deadline: float) -> list[Outcome | str]:
        """Answer requests in order; each item is an ``Outcome`` or the reason it has none.

        Args:
            requests: Validated requests.
            lane: ``hot`` or ``background``.
            deadline: Clock time by which the call returns; items not reached come back ``timeout``.
        """
        reason = self._wait_ready(lane, deadline)
        if reason:
            return [reason] * len(requests)
        with self._cond:
            if self._inside[lane] >= self._limits[lane]:
                return ["queue_full"] * len(requests)
            self._inside[lane] += 1
        try:
            out: list[Outcome | str] = []
            for request in requests:
                out.append("timeout" if out and out[-1] == "timeout" else self._run_one(request, lane, deadline))
            return out
        finally:
            with self._cond:
                self._inside[lane] -= 1

    def _predict(self, step: Pass) -> float:
        profile = self.profile
        return profile.drift * profile.pass_s(step.tokens, step.cached) if profile else 0.0

    def _run_one(self, request: Request, lane: Lane, deadline: float) -> Outcome | str:
        engine = self._engine
        enc = engine.tokenizer.encode
        try:
            text = to_text(request.state)
        except (TypeError, ValueError):
            return "bad_item"
        ids = enc(text)
        truncated = len(ids) > engine.max_state_tokens
        if truncated:  # as the release client's state_text, which this needs the flag from
            text = engine.tokenizer.decode(ids[: engine.max_state_tokens]) + " ...[truncated]"
        prefix = enc(prefix_text(text))
        suffixes = [enc(suffix_text(q)) for q in request.questions.values()]
        passes = plan(len(prefix), [len(s) for s in suffixes], lane)
        needed = len(prefix) + max(map(len, suffixes))

        start = self._clock()
        lock = self._buffer_locks[lane]
        if not lock.acquire(timeout=max(0.0, deadline - start - self._predict(passes[0]))):
            return "timeout"
        compute = 0.0
        try:
            buf = self._buffer(engine, lane)
            buf.reserve(needed)
            logits: dict[int, Any] = {}
            for step in passes:
                try:
                    self._gate.acquire(lane, deadline, self._predict(step))
                except GateTimeout:
                    return "timeout"
                began = self._clock()
                try:
                    out = _run_pass(buf, prefix, suffixes, step)
                finally:
                    elapsed = self._clock() - began
                    self._gate.release(lane, elapsed)
                compute += elapsed
                if self.profile:
                    self.profile.observe(step, elapsed)
                logits[max(step.segment, 0)] = out
            answers = {key: engine.answer(logits[i], key, q) for i, (key, q) in enumerate(request.questions.items())}
        except Exception:  # noqa: BLE001 -- one bad item never fails the batch
            logger.exception("A decision-model pass failed")
            return "bad_item"
        finally:
            if lane == "background":
                self._background_used = self._clock()
            elif needed > HOT_KEEP_TOKENS:
                engine.kv = engine.new_buffer()
            lock.release()
            if lane == "background":
                self._schedule_drop()
        total = self._clock() - start
        return Outcome(answers, compute * 1000, (total - compute) * 1000, truncated,
                       len(prefix) + sum(map(len, suffixes)))

    # The background buffer

    def _buffer(self, engine: Engine, lane: Lane) -> SharedKV:
        if lane == "hot":
            return engine.kv
        if self._background is None:
            self._background = engine.new_buffer()
        return self._background

    def _schedule_drop(self, delay: float = BACKGROUND_IDLE_S) -> None:
        if self._idle_timer is None or not self._idle_timer.is_alive():
            self._idle_timer = threading.Timer(delay, self._drop_background)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _drop_background(self) -> None:
        """Free the background buffer once it has been idle for ``BACKGROUND_IDLE_S``; check again later if not."""
        self._idle_timer = None
        lock = self._buffer_locks["background"]
        if not lock.acquire(blocking=False):
            self._schedule_drop()
            return
        try:
            idle = self._clock() - self._background_used
            if idle >= BACKGROUND_IDLE_S:
                self._background = None
            else:
                self._schedule_drop(BACKGROUND_IDLE_S - idle)
        finally:
            lock.release()


def _run_pass(buf: SharedKV, prefix: list[int], suffixes: list[list[int]], step: Pass) -> Any:
    """Run one pass of the plan on ``buf``; the label logits at its last position."""
    if step.single:
        ids, io = prefix + suffixes[0], buf.io_single
    else:
        ids, io = (prefix if step.segment < 0 else suffixes[step.segment]), buf.io
    return buf.extend(ids[step.begin : step.end], step.cached, io, 0)
