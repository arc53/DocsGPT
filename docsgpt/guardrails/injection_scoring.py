"""Prompt-injection scores for texts: from a cache keyed by content, else from the decision model.

Every surface that scores text for prompt injection goes through here: the ``injection_model`` guardrail check at
chat time, background scoring of the texts a turn could not score in time, and chat attachments once uploaded. A
score is a function of the text alone, so it is cached in ``content_scores`` by the text's sha256 and the scorer
that produced it (``scorer_id``: the model version, the question and the windowing). A new model revision, question
wording or window size is a new scorer, so every lookup misses and text is scored again.

A long text is split into windows of ``WINDOW_TOKENS`` model tokens with a ``WINDOW_OVERLAP`` overlap, scored in
the order most likely to matter: the last window (where an appended payload sits), the first, then the rest from
the end backwards. The decision model answers a call's states in order and returns those it finished when the
deadline cuts it short, so on a slow machine the windows that matter most are the ones read. A text's ``p`` is the
highest probability over its windows.

Scores, not verdicts, are stored: thresholds are applied when a score is read, so a threshold change never needs a
rescore. A text is cached only when every window sent for it was answered. Nothing here raises: a text that could
not be scored is ``None`` with a reason, and a cache that cannot be read is a miss.

The model runs only where the harness puts it (``docsgpt.decisions``); a Celery worker reaches it over HTTP.
Nothing calls it while ``DECISION_INJECTION_ENABLED`` is false.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from docsgpt import decisions
from docsgpt.core.settings import settings
from docsgpt.decisions import Budget, Q, Request, states, tokens, usage
from docsgpt.decisions.features import INJECTION_LAZY
from docsgpt.decisions.types import BACKEND_REASONS, ModelInfo

logger = logging.getLogger(__name__)

#: Model tokens per window of a long text, and the overlap between windows, so a payload on a boundary is read whole
#: in one of them. A short window is about 0.7 s on 4 vCPU, so two or three fit the default 2 s stage deadline
#: (one 1,600-token window did not), it is close to the length of the texts the model was trained on, and a short
#: payload is not diluted by a long benign window around it.
WINDOW_TOKENS = 512
WINDOW_OVERLAP = 50
#: The question asked about every window. ``severity`` is not asked: it would be a second pass per window.
QUESTIONS = {"injection": Q.INJECTION}
#: Texts one call of ``enqueue_lazy`` queues, so one turn (or one tenant) cannot flood the worker.
LAZY_MAX_TEXTS = 16
#: Why a text was not scored because the caller's ``live`` limit was reached.
DEFERRED = "deferred"
#: Why the model could not answer one text, which asking again would not change: the text does not render, or the
#: backend failed on it (``backend_error``: its pass raised, or a server refused it). Neither stops the other texts,
#: and neither is queued for background scoring.
ITEM_FAILURES = frozenset({"bad_item", "backend_error"})
#: Why the model could not answer at all: the rest of the windows are not sent.
DOWN = BACKEND_REASONS - ITEM_FAILURES


@dataclass(frozen=True)
class InjectionScore:
    """How likely a text is a prompt injection.

    Attributes:
        p: The highest probability over the windows scored.
        windows_scored: Windows answered.
        windows_total: Windows the whole text spans; more than ``windows_scored`` when some went unanswered or
            past the window cap.
        cached: Read from ``content_scores`` (or a score stored with the item), not computed now.
        truncated: A window was cut to the model's token limit (its start was still read).
    """

    p: float
    windows_scored: int
    windows_total: int
    cached: bool = False
    truncated: bool = False

    @property
    def complete(self) -> bool:
        """Every window of the text was scored."""
        return self.windows_scored >= self.windows_total


class Scores(list):
    """One ``InjectionScore`` or ``None`` per text, in order, with what happened.

    Attributes:
        reasons: Per text, ``None`` when every window sent was answered, else why not: ``deferred`` (past the
            caller's ``live`` limit), ``timeout``, a backend reason (``loading``, ``off``, ...) or ``bad_item``.
            A text with some windows answered has a score and a reason.
        totals: Per text, the windows it spans once it was windowed for the model, else ``None``.
        cache_hits: Texts answered from the cache.
        live: Texts sent to the model.
        ms: Time spent waiting for the model.
        model: The model that answered, when one did.
    """

    def __init__(self, scores: List[Optional[InjectionScore]], reasons: List[Optional[str]], *,
                 totals: Optional[List[Optional[int]]] = None, cache_hits: int = 0, live: int = 0, ms: float = 0.0,
                 model: Optional[ModelInfo] = None):
        super().__init__(scores)
        self.reasons = reasons
        self.totals = totals if totals is not None else [None] * len(scores)
        self.cache_hits = cache_hits
        self.live = live
        self.ms = ms
        self.model = model


def content_hash(text: str) -> str:
    """The sha256 hex digest of ``text`` as UTF-8: the cache key, and what an owner's allowlist holds.

    Not the chunk's MD5 ``chunk_key``: MD5 collisions are practical, and a crafted chunk must not inherit a benign
    twin's score.
    """
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def scorer_id() -> Optional[str]:
    """``injection:<model_version>:q<question hash>:w<window>o<overlap>``, or ``None`` with no model configured.

    Needs no model load or network, so lookups work while the model is loading or down.
    """
    version = decisions.model_version()
    if version is None:
        return None
    questions = hashlib.sha256(json.dumps(QUESTIONS, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return f"injection:{version}:q{questions}:w{WINDOW_TOKENS}o{WINDOW_OVERLAP}"


def windows(text: str, max_windows: Optional[int] = None) -> tuple[list[str], int]:
    """The windows of ``text`` to score, in the order to score them, and how many it has in all.

    The order is the last window, the first, then the rest from the end backwards. Windows are counted in model
    tokens; before the tokenizer has loaded they are counted in characters, one per token at worst, which gives
    more and shorter windows and still reads every part of the text. Either way the windows hold the text as
    ``tokens.clean`` leaves it: a lone surrogate, which the tokenizer refuses, is read as U+FFFD.

    Args:
        text: The text to score.
        max_windows: The most windows to return; ``GUARDRAILS_INJECTION_MAX_WINDOWS`` when omitted.

    Returns:
        The windows to score and the number of windows the whole text spans.
    """
    if max_windows is None:
        max_windows = settings.GUARDRAILS_INJECTION_MAX_WINDOWS
    text = tokens.clean(text)
    ids = tokens.encode(text)
    units: Any = ids if ids is not None else text
    starts = [0]
    while starts[-1] + WINDOW_TOKENS < len(units):
        starts.append(starts[-1] + WINDOW_TOKENS - WINDOW_OVERLAP)
    total = len(starts)
    order = [starts[-1]] + starts[:1] + starts[-2:0:-1] if total > 1 else starts
    pieces = [units[start : start + WINDOW_TOKENS] for start in order[: max(1, max_windows)]]
    if ids is not None:
        pieces = [tokens.decode(piece) for piece in pieces]
    return pieces, total


def from_metadata(stored: Any) -> Optional[InjectionScore]:
    """A score stored with an item (``metadata.injection``), when the current scorer produced it.

    Args:
        stored: ``{p, scorer, windows_scored, windows_total}``, as ``as_metadata`` writes it.
    """
    if not isinstance(stored, dict) or stored.get("scorer") is None or stored.get("scorer") != scorer_id():
        return None
    try:
        return InjectionScore(float(stored["p"]), int(stored["windows_scored"]), int(stored["windows_total"]),
                              cached=True)
    except (KeyError, TypeError, ValueError):
        return None


def as_metadata(score: InjectionScore) -> Dict[str, Any]:
    """The shape an item stores its score in (``metadata.injection``): ``{p, scorer, windows_scored, windows_total}``."""
    return {"p": round(score.p, 4), "scorer": scorer_id(), "windows_scored": score.windows_scored,
            "windows_total": score.windows_total}


def lookup(texts: Sequence[str]) -> List[Optional[InjectionScore]]:
    """The cached score of each text, in one query; ``None`` for a miss, and for every text when the cache fails."""
    scorer = scorer_id()
    if scorer is None or not texts:
        return [None] * len(texts)
    return _cached(texts, scorer)[0]


def _cached(texts: Sequence[str], scorer: str) -> tuple[List[Optional[InjectionScore]], set[str]]:
    """The cached score of each text, and the hashes of the rows found that were not seen today."""
    hashes = [content_hash(t) for t in texts]
    rows = _load(hashes, scorer)
    stale = {h for h, row in rows.items() if row.get("stale")}
    return [
        InjectionScore(row["p"], row["windows_scored"], row["windows_total"], cached=True) if row else None
        for row in (rows.get(h) for h in hashes)
    ], stale


def score(texts: Sequence[str], *, feature: str, budget: Budget, max_windows: Optional[int] = None,
          live: Optional[int] = None, cache: bool = True) -> Scores:
    """Score texts: from the cache, else with the decision model.

    In the hot lane the windows go out in calls of at most ``DECISION_MAX_BATCH_STATES`` within ``budget``; in the
    background lane in calls of at most ``GUARDRAILS_INJECTION_BATCH_STATES``, each with ``budget``. A call whose
    status is ``unavailable`` for a reason in ``DOWN`` stops the rest; one the backend failed on item by item
    (``backend_error``) does not. Cache hits are counted in ``decision_usage`` under status
    ``cached``, so checked texts per feature need no table of their own.

    Args:
        texts: The texts.
        feature: The caller's label (``docsgpt.decisions.features``): it names the ``decision`` spans and keys the
            usage counts.
        budget: Lane and deadline.
        max_windows: Windows read per text (see ``windows``).
        live: The most cache misses sent to the model; the rest come back ``None``, ``deferred``. ``None`` sends
            every miss.
        cache: Read and write ``content_scores``; a one-off text (a user's message, a tool result) passes False.

    Returns:
        One score or ``None`` per text, with reasons and counts. Whitespace-only text scores 0 without a call.
    """
    n = len(texts)
    scores: List[Optional[InjectionScore]] = [None] * n
    reasons: List[Optional[str]] = [None] * n
    if not settings.DECISION_INJECTION_ENABLED:
        return Scores(scores, ["off"] * n)
    todo = []
    for i, text in enumerate(texts):
        if text.strip():
            todo.append(i)
        else:
            scores[i] = InjectionScore(0.0, 0, 0)
    cap = settings.GUARDRAILS_INJECTION_MAX_WINDOWS if max_windows is None else max_windows
    hits = 0
    scorer = scorer_id() if cache else None
    if scorer is not None and todo:
        found, stale = _cached([texts[i] for i in todo], scorer)
        misses = []
        for i, hit in zip(todo, found):
            # A row scored with fewer windows than this call reads (a cap since raised) is scored again.
            if hit is not None and hit.windows_scored >= min(hit.windows_total, cap):
                scores[i] = hit
                hits += 1
            else:
                misses.append(i)
        todo = misses
        if hits:
            _count_cached(feature, hits)
        # Hits on rows not seen today are marked seen, so retention keeps text still in use: in the background
        # lane right away, from a chat turn by the worker, so the turn never waits on the write.
        seen = sorted({content_hash(texts[i]) for i, s in enumerate(scores) if s is not None and s.cached} & stale)
        if seen:
            (_touch if budget.lane == "background" else _touch_later)(seen, scorer)
    if live is not None:
        for i in todo[max(live, 0):]:
            reasons[i] = DEFERRED
        todo = todo[: max(live, 0)]
    if not todo:
        return Scores(scores, reasons, cache_hits=hits)

    plan = []  # (text index, window) in the order the windows are sent
    totals: List[Optional[int]] = [None] * n
    for i in todo:
        try:
            pieces, totals[i] = windows(texts[i], cap)
        except Exception:  # noqa: BLE001 - a text the tokenizer fails on is that text's failure, not the call's
            logger.warning("Could not window a text for injection scoring", exc_info=True)
            reasons[i] = "bad_item"
            continue
        plan.extend((i, piece) for piece in pieces)
    answers, why, ms = _ask(plan, feature, budget)
    model = next((d.model for d in answers if d is not None), None)
    sent: Dict[int, List[int]] = {}
    for k, (owner, _) in enumerate(plan):
        sent.setdefault(owner, []).append(k)
    rows = []
    for i in todo:
        if i not in sent:  # never windowed
            continue
        mine = sent[i]
        answered = [answers[k] for k in mine if answers[k] is not None]
        reasons[i] = next((why[k] for k in mine if why[k]), None)
        if not answered:
            continue
        scores[i] = InjectionScore(
            max(d.p("injection") for d in answered), len(answered), totals[i],
            cached=all(d.cached for d in answered), truncated=any(d.truncated for d in answered),
        )
        if scorer is not None and reasons[i] is None:
            rows.append({"content_hash": content_hash(texts[i]), "scorer": scorer, "p": scores[i].p,
                         "windows_scored": scores[i].windows_scored, "windows_total": scores[i].windows_total})
    _store(rows)
    return Scores(scores, reasons, totals=totals, cache_hits=hits, live=len(todo), ms=ms, model=model)


def _ask(plan: List[tuple], feature: str, budget: Budget) -> tuple[list, list, float]:
    """Send the planned windows to the model; per window its ``Decision`` or ``None`` and why, and the time taken."""
    background = budget.lane == "background"
    size = settings.GUARDRAILS_INJECTION_BATCH_STATES if background else settings.DECISION_MAX_BATCH_STATES
    deadline = None if background else time.monotonic() + budget.timeout()
    answers: list = [None] * len(plan)
    why: List[Optional[str]] = [None] * len(plan)
    started = time.monotonic()
    for start in range(0, len(plan), size):
        part = range(start, min(start + size, len(plan)))
        left = None if deadline is None else deadline - time.monotonic()
        if left is not None and left <= 0:
            for k in part:
                why[k] = "timeout"
            continue
        batch = decisions.decide_batch(
            [Request(states.text(plan[k][1]), QUESTIONS) for k in part],
            feature=feature,
            budget=budget if left is None else Budget.hot(left),
        )
        for k, decision, reason in zip(part, batch, batch.reasons):
            answers[k], why[k] = decision, reason
        down = next((r for r in batch.reasons if r in DOWN), None) if batch.status == "unavailable" else None
        if down is not None:
            # The backend is down or loading: asking again item by item would only wait on it.
            for k in range(part.stop, len(plan)):
                why[k] = down
            break
    return answers, why, (time.monotonic() - started) * 1000


def enqueue_lazy(texts: Iterable[str]) -> int:
    """Queue texts to be scored in the background (``injection_lazy``), so the next turn that uses them hits the cache.

    At most ``LAZY_MAX_TEXTS`` distinct non-blank texts are queued per call; the task looks each up again before
    scoring, so a repeat costs one query. A no-op while the switch, ``GUARDRAILS_INJECTION_LAZY`` or the model is off.

    Returns:
        How many texts were queued.
    """
    if not (settings.DECISION_INJECTION_ENABLED and settings.GUARDRAILS_INJECTION_LAZY) or scorer_id() is None:
        return 0
    queued = list(dict.fromkeys(t for t in texts if isinstance(t, str) and t.strip()))[:LAZY_MAX_TEXTS]
    if not queued:
        return 0
    try:
        _queue(queued)
    except Exception:  # noqa: BLE001 - a turn never fails because background scoring could not be queued
        logger.warning("Could not queue %d text(s) for background injection scoring", len(queued), exc_info=True)
        return 0
    return len(queued)


def _queue(texts: List[str]) -> None:
    from docsgpt.api.user.tasks import score_injection_texts

    score_injection_texts.delay(texts)


def score_lazy(texts: Sequence[str]) -> Dict[str, int]:
    """The background task's work: score the queued texts not cached yet, in the background lane.

    Returns:
        ``{"texts", "cached", "scored"}``: texts received, already cached, and newly stored.
    """
    texts = [t for t in texts if isinstance(t, str)][:LAZY_MAX_TEXTS]
    result = score(texts, feature=INJECTION_LAZY, budget=Budget.BACKGROUND)
    scored = sum(1 for s, r in zip(result, result.reasons) if s is not None and not s.cached and r is None)
    return {"texts": len(texts), "cached": result.cache_hits, "scored": scored}


def allowed_hashes(source_ids: Iterable[str]) -> Dict[str, set[str]]:
    """Per source, the text hashes its owner marked safe (``sources.metadata.injection_review.allowed``), in one query.

    Empty when the sources cannot be read.
    """
    ids = sorted({str(s) for s in source_ids if s})
    if not ids:
        return {}
    try:
        from docsgpt.storage.db.repositories.sources import SourcesRepository
        from docsgpt.storage.db.session import db_readonly

        with db_readonly() as conn:
            return SourcesRepository(conn).injection_allowed(ids)
    except Exception:  # noqa: BLE001 - an unreadable allowlist is an empty one
        logger.warning("Could not read the owners' injection allowlists", exc_info=True)
        return {}


def _load(hashes: List[str], scorer: str) -> Dict[str, Dict[str, Any]]:
    try:
        from docsgpt.storage.db.repositories.content_scores import ContentScoresRepository
        from docsgpt.storage.db.session import db_readonly

        with db_readonly() as conn:
            return ContentScoresRepository(conn).get_many(hashes, scorer)
    except Exception:  # noqa: BLE001 - a cache that cannot be read is a miss
        logger.warning("Could not read cached injection scores", exc_info=True)
        return {}


def _store(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    try:
        from docsgpt.storage.db.repositories.content_scores import ContentScoresRepository
        from docsgpt.storage.db.session import db_session

        with db_session() as conn:
            ContentScoresRepository(conn).upsert_many(rows)
    except Exception:  # noqa: BLE001 - an unwritten score is scored again next time
        logger.warning("Could not cache %d injection score(s)", len(rows), exc_info=True)


def _touch(hashes: List[str], scorer: str) -> None:
    try:
        from docsgpt.storage.db.repositories.content_scores import ContentScoresRepository
        from docsgpt.storage.db.session import db_session

        with db_session() as conn:
            ContentScoresRepository(conn).touch(hashes, scorer)
    except Exception:  # noqa: BLE001 - retention only
        logger.debug("Could not mark cached injection scores as seen", exc_info=True)


def _touch_later(hashes: List[str], scorer: str) -> None:
    try:
        from docsgpt.api.user.tasks import touch_content_scores

        touch_content_scores.delay(hashes, scorer)
    except Exception:  # noqa: BLE001 - retention only
        logger.debug("Could not queue marking cached injection scores as seen", exc_info=True)


def _count_cached(feature: str, hits: int) -> None:
    decider = decisions.get_decider()
    usage.count(feature, getattr(decider, "mode", ""), decisions.model_version(), "cached",
                states=hits, answered=hits, ms=0.0, queue_ms=0.0)
