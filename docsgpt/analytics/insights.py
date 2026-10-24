"""The conversation-insights figures the Analytics page shows: rates with intervals, built from label aggregates.

Rates are sums of probabilities over label rows, never thresholded counts; each interval is ``derive.rate``'s
binomial interval widened by the label's calibration error (``calibration.interval``). Labels made by several
models take the widest model's error. Each label carries a tier (issue 004, Decision 1): ``dashboard`` labels are
headline rates, ``estimated`` ones are overconfident on real traffic and shown only with their range,
``experimental`` (topic) is a grouping to read trends from.
"""

from __future__ import annotations

import datetime
from typing import Iterable, Optional

from docsgpt.analytics import calibration, derive, schema

TIERS = {
    "answer_status": "dashboard", "sentiment": "dashboard", "frustrated": "dashboard", "asks_human": "dashboard",
    "goal_met": "dashboard", "gap_type": "estimated", "reaction": "estimated", "request_type": "estimated",
    "topic_effective": "experimental",
}
TAG_TIER = "dashboard"
#: Labels in ``totals`` (tags are added per agent), and those ``series`` carries per bucket.
TOTAL_LABELS = ("answer_status", "gap_type", "reaction", "request_type", "sentiment", "frustrated", "asks_human",
                "goal_met", "topic_effective")
SERIES_LABELS = ("answer_status", "reaction", "request_type", "sentiment", "topic_effective", "frustrated",
                 "asks_human", "goal_met")
#: The labels the page compares with the previous period of the same length.
PREVIOUS_LABELS = ("answer_status", "reaction", "sentiment")
#: Under this many items a figure is noise (the frontend's ``MIN_SAMPLE``); a series unit whose buckets average
#: fewer coarsens to the next.
MIN_SAMPLE = 10
#: Each series unit and the one it coarsens to. One step only: the last hour never reads as a day.
COARSER = {"minute": "hour", "hour": "day", "day": "week"}
#: Yes/no labels report the ``yes`` option only.
YES_NO = ("frustrated", "asks_human", "goal_met")
#: Stored as the score's level index.
SENTIMENT = {"0": "negative", "1": "neutral", "2": "positive"}
NOT_A_REQUEST = "not a request"

_OPTIONS = {
    "answer_status": tuple(schema.ANSWER_STATUS["criteria"]),
    "reaction": tuple(schema.REACTION["criteria"]),
    "request_type": tuple(schema.INTENT["criteria"]),
    "sentiment": tuple(SENTIMENT.values()),
    "gap_type": (*derive.GAP_TYPES, "none"),
}

#: The labels the language note can name, and the languages each is measurably weaker in (``other``: every
#: language outside en/es/zh/ru, which the model was not trained on). A label warns past ``LANGUAGE_WARNING``.
WEAK_LANGUAGES = {"answer_status": ("ru", "other"), "gap_type": ("ru", "other"),
                  "topic_effective": ("ru", "other"), "reaction": ("zh", "other")}
LANGUAGE_WARNING = 0.10
LANGUAGES = ("en", "es", "zh", "ru", "other")


def is_yes_no(label: str) -> bool:
    return label in YES_NO or label.startswith("tag:")


def option_name(label: str, option: str) -> str:
    """The option as the API names it: sentiment levels by name, the rest as stored."""
    return SENTIMENT.get(option, option) if label == "sentiment" else option


def widest_version(label: str, versions: Iterable[Optional[str]]) -> Optional[str]:
    """The model version among ``versions`` whose calibration error for ``label`` is largest."""
    return max(list(versions) or [None], key=lambda version: calibration.ece(label, version))


def _figure(label: str, expected: float, n: float, version: Optional[str]) -> dict:
    rate, low, high = calibration.interval(label, expected, n, version)
    return {"expected": round(expected, 2), "rate": round(rate, 4), "low": round(low, 4), "high": round(high, 4)}


def _sums_by_label(sums: Iterable[dict]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in sums:
        options = out.setdefault(row["label"], {})
        option = option_name(row["label"], row["option"])
        options[option] = options.get(option, 0.0) + float(row["expected"] or 0)
    return out


def _options(label: str, seen: dict[str, float]) -> tuple[str, ...]:
    if is_yes_no(label):
        return ("yes",)
    known = _OPTIONS.get(label, ())
    return (*known, *sorted(o for o in seen if o not in known))


def totals(labels: Iterable[str], counts: dict[str, dict], sums: Iterable[dict]) -> dict:
    """``totals`` per label: its tier, rows and, per option, the expected count and the rate with its interval.

    ``answer_status`` rates are over requests: its ``n`` is the labelled turns minus their ``not a request``
    mass (``n_requests`` unrounded, ``n_turns`` every labelled turn), and ``not a request`` itself is over every
    turn. The effective topic and tags appear only once they have rows.

    Args:
        labels: The labels to report, in order.
        counts: ``ConversationLabelsRepository.label_counts``.
        sums: ``ConversationLabelsRepository.label_sums`` rows.
    """
    by_label = _sums_by_label(sums)
    out = {}
    for label in labels:
        count = counts.get(label) or {}
        n = int(count.get("n") or 0)
        if n == 0 and (label == "topic_effective" or label.startswith("tag:")):
            continue
        version = widest_version(label, count.get("versions") or [])
        seen = by_label.get(label, {})
        entry: dict = {"tier": TIERS.get(label, TAG_TIER), "n": n}
        base = float(n)
        if label == "answer_status":
            requests = max(0.0, n - float(count.get("not_request") or 0))
            entry.update(n=round(requests), n_requests=round(requests, 2), n_turns=n)
            base = requests
        entry["options"] = {
            option: _figure(label, seen.get(option, 0.0), n if option == NOT_A_REQUEST else base, version)
            for option in _options(label, seen)
        }
        out[label] = entry
    return out


def bucket_unit(unit: str, buckets: list[str], items: int) -> str:
    """The series' unit: the filter's own while its buckets average ``MIN_SAMPLE`` items, else the next coarser.

    A day with two answers drawn as its own column reads as a finding; a week of them is a sample.

    Args:
        unit: The filter's unit (``minute``, ``hour`` or ``day``).
        buckets: Every bucket of the window in that unit.
        items: The labelled items the series draws (the window's ``answer_status`` rows).
    """
    coarser = COARSER.get(unit)
    if coarser is None or not buckets or items >= MIN_SAMPLE * len(buckets):
        return unit
    return coarser


def coarse_key(key: str, unit: str) -> str:
    """A bucket key of the next finer unit as its key in ``unit``; a week is keyed by its Monday."""
    if unit == "hour":
        return f"{key[:13]}:00"
    if unit == "day":
        return key[:10]
    if unit == "week":
        day = datetime.date.fromisoformat(key[:10])
        return (day - datetime.timedelta(days=day.weekday())).isoformat()
    return key


def rebucket(buckets: list[str], counts: Iterable[dict], sums: Iterable[dict],
             unit: str) -> tuple[list[str], dict[str, str], list[dict], list[dict]]:
    """Fine buckets merged into ``unit``'s, with their rows and expected counts summed.

    A week is clipped to the window: it is named by its first day in the window and ends on its last, so the
    window's first and last weeks may be short.

    Args:
        buckets: Every bucket of the window in the next finer unit, in order.
        counts: ``bucket_counts`` rows in that unit.
        sums: ``label_sums`` rows in that unit.
        unit: The unit to merge into (``hour``, ``day`` or ``week``).

    Returns:
        The merged buckets in order, each week's last day by its name (empty for other units), and the counts
        and sums re-keyed and summed.
    """
    name: dict[str, str] = {}
    first: dict[str, str] = {}
    ends: dict[str, str] = {}
    for key in buckets:
        coarse = coarse_key(key, unit)
        if unit == "week":
            first.setdefault(coarse, key)
            ends[first[coarse]] = key
            name[key] = first[coarse]
        else:
            name[key] = coarse
    n: dict[tuple[str, str], int] = {}
    for row in counts:
        at = (name.get(row["bucket"], coarse_key(row["bucket"], unit)), row["label"])
        n[at] = n.get(at, 0) + int(row["n"])
    expected: dict[tuple[str, str, str], float] = {}
    for row in sums:
        at = (name.get(row["bucket"], coarse_key(row["bucket"], unit)), row["label"], row["option"])
        expected[at] = expected.get(at, 0.0) + float(row["expected"] or 0)
    return (
        list(dict.fromkeys(name[key] for key in buckets)),
        ends,
        [{"bucket": bucket, "label": label, "n": value} for (bucket, label), value in n.items()],
        [{"bucket": bucket, "label": label, "option": option, "expected": value}
         for (bucket, label, option), value in expected.items()],
    )


def series(buckets: Iterable[str], labels: Iterable[str], counts: Iterable[dict], sums: Iterable[dict],
           options: dict[str, Iterable[str]], ends: Optional[dict[str, str]] = None) -> list[dict]:
    """``series``: per bucket, each label's rows and expected count per option, zeros filled in.

    Args:
        buckets: Every bucket of the window, in order (``_intervals_for_filter``, or ``rebucket``'s).
        labels: The labels to carry.
        counts: ``ConversationLabelsRepository.bucket_counts`` rows.
        sums: ``ConversationLabelsRepository.label_sums`` rows with a bucket.
        options: Each label's options (from ``totals``), so every bucket names the same ones.
        ends: A week's last day by its name (``rebucket``), sent as its ``bucket_end``.
    """
    n = {(row["bucket"], row["label"]): int(row["n"]) for row in counts}
    expected: dict[tuple[str, str], dict[str, float]] = {}
    for row in sums:
        values = expected.setdefault((row["bucket"], row["label"]), {})
        option = option_name(row["label"], row["option"])
        values[option] = values.get(option, 0.0) + float(row["expected"] or 0)
    labels = [label for label in labels if label in options]
    ends = ends or {}
    return [
        {"bucket": bucket, **({"bucket_end": ends[bucket]} if bucket in ends else {}), "labels": {
            label: {"n": n.get((bucket, label), 0),
                    "options": {o: round(expected.get((bucket, label), {}).get(o, 0.0), 3) for o in options[label]}}
            for label in labels
        }}
        for bucket in buckets
    ]


def languages(counts: dict[str, dict]) -> dict[str, int]:
    """The language mix of labelled user messages (their ``request_type`` rows), languages with none left out."""
    count = counts.get("request_type") or {}
    return {lang: int(count[lang]) for lang in LANGUAGES if count.get(lang)}


def language_warnings(counts: dict[str, dict]) -> list[str]:
    """The labels whose rows are over ``LANGUAGE_WARNING`` in languages the model reads them less accurately in."""
    out = []
    for label, weak in WEAK_LANGUAGES.items():
        count = counts.get(label) or {}
        n = int(count.get("n") or 0)
        if n and sum(int(count.get(lang) or 0) for lang in weak) / n > LANGUAGE_WARNING:
            out.append(label)
    return out


def gap_row(group: dict, examples: list[dict], name: Optional[str], source: Optional[str] = None) -> dict:
    """One docs-gap table row from ``ConversationLabelsRepository.gap_groups`` and its examples.

    Args:
        group: The group's ``gap_groups`` row.
        examples: Its example questions, as the route sends them.
        name: The group's display name.
        source: The name of the source a page group came from; ``None`` for other groupings or an unknown source.

    Returns:
        The row as the API sends it.
    """
    turns = float(group["turns"] or 0)
    expected = float(group["expected"] or 0)
    version = widest_version("gap_type", group.get("versions") or [])
    rate, low, high = calibration.interval("gap_type", expected, turns, version)
    return {
        "key": group["key"], "name": name, "source": source, "expected_gaps": round(expected, 2),
        "turns": round(turns),
        "rate": round(rate, 4), "low": round(low, 4), "high": round(high, 4),
        "previous_expected": round(float(group["previous"] or 0), 2),
        "examples": examples,
    }
