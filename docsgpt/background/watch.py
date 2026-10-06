"""Job ``watch``: what a running job's output may do before the job ends.

A call that can become a job may carry::

    "watch": {"patterns": ["Traceback|Error|Killed"], "progress_regex": "PROGRESS (\\d+)%", "heartbeat_s": 0}

* ``patterns`` wake the agent while the job still runs (``wake_conversation``
  with the matching line): at most one wake per :data:`MIN_WAKE_GAP_SECONDS`;
  a match inside that gap is dropped and counts as a strike, and
  :data:`MAX_STRIKES` strikes or :data:`MAX_PATTERN_WAKES` wakes turn the
  patterns off, after which only completion wakes.
* ``progress_regex`` updates the job's ``progress`` (and ``job.updated``); it
  never wakes the model. With a numeric first group the group is the percent.
* ``heartbeat_s`` (0 = off, else at least 60) wakes the agent with the output
  printed since the last heartbeat (at most 2000 characters), skipped when
  there is none.

Completion and failure always wake, so silence is never taken for success.

Mid-run output exists only for detached sandbox runs (Daytona's command
logs, the Jupyter job's ``out.log``). A job running in-process or in a worker
has no output until it ends: there only ``progress_regex`` applies, to the
final result.

Patterns come from the model and run over sandbox output, so they are
bounded (count and length) and matched with a timeout.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import regex

from docsgpt.background.events import publish_job_updated
from docsgpt.background.results import tail_of
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.session import db_session

logger = logging.getLogger(__name__)

MAX_PATTERNS = 5
MAX_PATTERN_CHARS = 200
MIN_WAKE_GAP_SECONDS = 15
MAX_STRIKES = 3
MAX_PATTERN_WAKES = 8
MIN_HEARTBEAT_SECONDS = 60
HEARTBEAT_CHARS = 2_000
#: Characters of new output one poll scans.
SCAN_CHARS = 16_000
#: Seconds one regex search may take before it is abandoned.
REGEX_TIMEOUT_SECONDS = 0.05


def _compile(pattern: Any) -> Optional["regex.Pattern"]:
    if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN_CHARS:
        return None
    try:
        return regex.compile(pattern, regex.MULTILINE)
    except regex.error:
        return None


def normalize(spec: Any) -> Optional[Dict[str, Any]]:
    """Clean a model's ``watch`` spec: valid, bounded patterns; heartbeat 0 or at least 60 s.

    Args:
        spec: The ``watch`` argument as the model passed it.

    Returns:
        The spec to store, or None when nothing usable is left.
    """
    if not isinstance(spec, dict):
        return None
    raw = spec.get("patterns") or []
    if isinstance(raw, str):
        raw = [raw]
    patterns = [p for p in raw if _compile(p) is not None][:MAX_PATTERNS] if isinstance(raw, list) else []
    progress = spec.get("progress_regex")
    progress = progress if _compile(progress) is not None else None
    try:
        heartbeat = int(spec.get("heartbeat_s") or 0)
    except (TypeError, ValueError):
        heartbeat = 0
    heartbeat = max(heartbeat, MIN_HEARTBEAT_SECONDS) if heartbeat > 0 else 0
    cleaned: Dict[str, Any] = {}
    if patterns:
        cleaned["patterns"] = patterns
    if progress:
        cleaned["progress_regex"] = progress
    if heartbeat:
        cleaned["heartbeat_s"] = heartbeat
    return cleaned or None


def _search(pattern: str, text: str):
    compiled = _compile(pattern)
    if compiled is None:
        return None
    try:
        return compiled.search(text, timeout=REGEX_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.info("watch pattern timed out and was skipped")
        return None


def progress_from(spec: Optional[Dict[str, Any]], text: str) -> Optional[Dict[str, Any]]:
    """The last ``progress_regex`` match in ``text`` as a progress dict, or None.

    Args:
        spec: The job's watch spec.
        text: Output to read.

    Returns:
        ``{"last": line, "percent"?: int}``.
    """
    pattern = (spec or {}).get("progress_regex")
    if not pattern or not text:
        return None
    compiled = _compile(pattern)
    if compiled is None:
        return None
    last = None
    try:
        for match in compiled.finditer(text[-SCAN_CHARS:], timeout=REGEX_TIMEOUT_SECONDS):
            last = match
    except TimeoutError:
        return None
    if last is None:
        return None
    # The whole printed line ("PROGRESS 43% batch 3/7"), not just the part the regex matched.
    scanned = text[-SCAN_CHARS:]
    progress: Dict[str, Any] = {"last": _line_of(scanned, last.start()).strip()[:200]}
    percent = _percent(last.group(1)) if last.groups() else None
    if percent is not None:
        progress["percent"] = percent
    return progress


def _percent(value: Any) -> Optional[int]:
    """A progress group as a 0-100 percent, or None when it isn't a number (``step two``)."""
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return None


def _line_of(text: str, start: int) -> str:
    begin = text.rfind("\n", 0, start) + 1
    end = text.find("\n", start)
    return text[begin:end if end != -1 else len(text)][:500]


def observe_output(job: Dict[str, Any], output: str, output_size: int) -> None:
    """Apply a running job's watch to the output it printed since the last poll.

    Args:
        job: The ``background_jobs`` row (``watch``, ``external.watch_state``).
        output: The latest tail of the job's output.
        output_size: The output's total size so far (the cursor new output is measured by).
    """
    spec = job.get("watch") if isinstance(job.get("watch"), dict) else None
    if not spec:
        return
    external = job.get("external") or {}
    state: Dict[str, Any] = dict(external.get("watch_state") or {})
    offset = int(state.get("offset") or 0)
    size = max(int(output_size or 0), 0)
    if size <= offset:
        return
    fresh = output[-min(size - offset, len(output)):] if output else ""
    fresh = fresh[-SCAN_CHARS:]
    now = time.time()
    updates: Dict[str, Any] = {}

    progress = progress_from(spec, fresh)
    stored = job.get("progress") or {}
    if progress is not None and (
        progress.get("last") != stored.get("last") or progress.get("percent") != stored.get("percent")
    ):
        updates["progress"] = {**progress, "updated_at": now}

    wakes: List[Dict[str, Any]] = []
    if spec.get("patterns") and not state.get("patterns_off"):
        for pattern in spec["patterns"]:
            match = _search(pattern, fresh)
            if match is None:
                continue
            if now - float(state.get("last_wake_at") or 0) < MIN_WAKE_GAP_SECONDS:
                state["strikes"] = int(state.get("strikes") or 0) + 1
            else:
                state["wakes"] = int(state.get("wakes") or 0) + 1
                state["last_wake_at"] = now
                wakes.append({"pattern": pattern, "line": _line_of(fresh, match.start())})
            if int(state.get("strikes") or 0) >= MAX_STRIKES or int(state.get("wakes") or 0) >= MAX_PATTERN_WAKES:
                state["patterns_off"] = True
            break

    heartbeat = int(spec.get("heartbeat_s") or 0)
    heartbeat_text = ""
    if heartbeat and now - float(state.get("last_heartbeat_at") or job_start(job)) >= heartbeat:
        since = int(state.get("heartbeat_offset") or 0)
        if size > since:
            heartbeat_text = output[-min(size - since, len(output)):][-HEARTBEAT_CHARS:]
        state["last_heartbeat_at"] = now
        state["heartbeat_offset"] = size

    state["offset"] = size
    with db_session() as conn:
        repo = BackgroundJobsRepository(conn)
        repo.merge_external(str(job["id"]), {"watch_state": state})
        if updates or output:
            repo.update_progress(str(job["id"]), progress=updates.get("progress"), output_tail=tail_of(output))
    if updates:
        publish_job_updated({**job, "progress": {**stored, **updates["progress"]}})
    for hit in wakes:
        _wake(job, f"output matched {hit['pattern']!r}", hit["line"], fresh, f"watch:{size}:{hit['pattern']}")
    if heartbeat_text:
        _wake(job, "progress update", "", heartbeat_text, f"heartbeat:{size}")


def job_start(job: Dict[str, Any]) -> float:
    """The job's start as a Unix time (0 when unknown)."""
    from docsgpt.background.service import parse_time

    started = parse_time(job.get("started_at"))
    return started.timestamp() if started is not None else 0.0


def _wake(job: Dict[str, Any], what: str, line: str, output: str, key: str) -> None:
    from docsgpt.background.wake import wake_conversation

    if not job.get("conversation_id") or not job.get("auto_resume"):
        return
    tool = f"{job.get('tool_name')}.{job.get('action_name')}"
    body = (
        f"Background job {job['id']} ({tool}) is still running; its {what}. You get its final result when it "
        "ends; don't predict how it will end. If the user asked to hear about this, or it changes what they "
        "should do, tell them briefly what happened; if the run is failing and should stop, cancel it with "
        "check_job. Otherwise reply NO_REPLY."
    )
    payload: Dict[str, Any] = {"output": tail_of(output, HEARTBEAT_CHARS)}
    if line:
        payload["line"] = line
    wake_conversation(
        user_id=str(job["user_id"]),
        conversation_id=str(job["conversation_id"]),
        source="job",
        ref_id=str(job["id"]),
        title=f"{tool} {what} (job {job['id']})",
        body=body,
        payload=payload,
        dedupe_key=f"job:{job['id']}:{key}",
    )
