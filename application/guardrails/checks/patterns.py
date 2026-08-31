"""Deterministic pattern checks: PII, secrets, denylist, URLs."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Pattern
from urllib.parse import urlsplit

from application.guardrails.base import GuardrailCheck, ScanContext
from application.guardrails.types import CheckOutcome, Span, Stage

_ALL_TEXT_STAGES = {
    Stage.INPUT,
    Stage.RETRIEVAL,
    Stage.OUTPUT,
    Stage.TOOL_RESULT,
}


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for char in reversed(digits):
        value = ord(char) - 48
        if alt:
            value *= 2
            if value > 9:
                value -= 9
        total += value
        alt = not alt
    return total % 10 == 0


PII_PATTERNS: Dict[str, Pattern[str]] = {
    "EMAIL": re.compile(r"\b[\w.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "PHONE": re.compile(
        r"(?<![\w-])(?:\+?\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?![\w-])"
    ),
    "US_SSN": re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)"),
    "CREDIT_CARD": re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])"),
    "IPV4": re.compile(
        r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\d.])"
    ),
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
}

DEFAULT_PII_ENTITIES = ["EMAIL", "PHONE", "US_SSN", "CREDIT_CARD"]

SECRET_PATTERNS: Dict[str, Pattern[str]] = {
    "AWS_ACCESS_KEY": re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b"),
    "GITHUB_TOKEN": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "OPENAI_KEY": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "ANTHROPIC_KEY": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    "SLACK_TOKEN": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "GOOGLE_API_KEY": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    # Spans the whole armored block, not just the header: redacting the BEGIN
    # line alone would release the key material. Falls back to the header when
    # the block is unterminated or longer than the cap.
    "PRIVATE_KEY": re.compile(
        r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"
        r"(?:[\s\S]{0,8192}?-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----)?"
    ),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    "GENERIC_SECRET": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|passwd|password|token)\b\s*[:=]\s*"
        r"[\"']?([A-Za-z0-9_\-/+]{16,})[\"']?"
    ),
}


class PIICheck(GuardrailCheck):
    name = "pii"
    label = "Personal information"
    description = (
        "Detects emails, phone numbers, national IDs, card numbers and IPs by pattern. "
        "Pattern matching is reliable for structured identifiers; it does not find names."
    )
    supported_stages = _ALL_TEXT_STAGES
    supports_redaction = True
    latency_hint_ms = 2
    max_match_chars = 256

    @classmethod
    def validate_settings(cls, settings: Dict[str, Any]) -> Dict[str, Any]:
        entities = settings.get("entities") or DEFAULT_PII_ENTITIES
        if not isinstance(entities, list) or not entities:
            raise ValueError("entities must be a non-empty list")
        unknown = [e for e in entities if e not in PII_PATTERNS]
        if unknown:
            raise ValueError(f"unknown PII entities: {', '.join(map(str, unknown))}")
        return {"entities": list(dict.fromkeys(entities))}

    def scan(self, text: str, stage: Stage, context: ScanContext) -> CheckOutcome:
        entities = self.settings.get("entities") or DEFAULT_PII_ENTITIES
        spans: List[Span] = []
        categories: List[str] = []
        for entity in entities:
            pattern = PII_PATTERNS.get(entity)
            if pattern is None:
                continue
            for match in pattern.finditer(text):
                if entity == "CREDIT_CARD":
                    digits = re.sub(r"\D", "", match.group(0))
                    if not (13 <= len(digits) <= 19) or not _luhn(digits):
                        continue
                spans.append(Span(match.start(), match.end(), entity))
                if entity not in categories:
                    categories.append(entity)
        if not spans:
            return CheckOutcome.clean()
        return CheckOutcome.hit(
            categories=categories,
            spans=spans,
            detail=f"{len(spans)} match(es): {', '.join(categories)}",
        )


class SecretsCheck(GuardrailCheck):
    name = "secrets"
    label = "Credentials and secrets"
    description = "Detects API keys, access tokens and private keys by known formats."
    supported_stages = _ALL_TEXT_STAGES
    supports_redaction = True
    latency_hint_ms = 2
    # Must cover the longest match PRIVATE_KEY can produce, or the streaming
    # guard would release the tail of a PEM block before scanning it.
    max_match_chars = 8192

    def scan(self, text: str, stage: Stage, context: ScanContext) -> CheckOutcome:
        spans: List[Span] = []
        categories: List[str] = []
        for label, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                # Group 1 exists only on the generic assignment pattern, where
                # the value is the secret and the key name is not.
                start, end = (
                    (match.start(1), match.end(1))
                    if pattern.groups and match.group(1)
                    else (match.start(), match.end())
                )
                spans.append(Span(start, end, label, replacement="[REDACTED]"))
                if label not in categories:
                    categories.append(label)
        if not spans:
            return CheckOutcome.clean()
        return CheckOutcome.hit(
            categories=categories,
            spans=spans,
            detail=f"{len(spans)} secret-like value(s): {', '.join(categories)}",
        )


class DenylistCheck(GuardrailCheck):
    name = "denylist"
    label = "Banned terms"
    description = "Blocks or masks a list of terms. Whole-word by default."
    supported_stages = _ALL_TEXT_STAGES
    supports_redaction = True
    latency_hint_ms = 1

    @classmethod
    def validate_settings(cls, settings: Dict[str, Any]) -> Dict[str, Any]:
        terms = settings.get("terms") or []
        if not isinstance(terms, list) or not terms:
            raise ValueError("terms must be a non-empty list")
        cleaned = [str(t).strip() for t in terms if str(t).strip()]
        if not cleaned:
            raise ValueError("terms must contain at least one non-empty value")
        if len(cleaned) > 500:
            raise ValueError("at most 500 terms")
        for term in cleaned:
            if len(term) > 128:
                raise ValueError("each term must be <= 128 characters")
        match_type = str(settings.get("match", "word")).lower()
        if match_type not in ("word", "substring"):
            raise ValueError("match must be 'word' or 'substring'")
        return {
            "terms": list(dict.fromkeys(cleaned)),
            "match": match_type,
            "case_sensitive": bool(settings.get("case_sensitive", False)),
        }

    @classmethod
    def window_for(cls, settings: Optional[Dict[str, Any]] = None) -> int:
        terms = (settings or {}).get("terms") or []
        longest = max((len(str(t)) for t in terms), default=0)
        return max(cls.max_match_chars, longest + 2)

    def _compiled(self) -> Optional[Pattern[str]]:
        terms = self.settings.get("terms") or []
        if not terms:
            return None
        alternation = "|".join(re.escape(t) for t in terms)
        if self.settings.get("match", "word") == "word":
            alternation = rf"(?<!\w)(?:{alternation})(?!\w)"
        flags = 0 if self.settings.get("case_sensitive") else re.IGNORECASE
        return re.compile(alternation, flags)

    def scan(self, text: str, stage: Stage, context: ScanContext) -> CheckOutcome:
        pattern = self._compiled()
        if pattern is None:
            return CheckOutcome.clean()
        spans = [
            Span(m.start(), m.end(), "BANNED_TERM", replacement="***")
            for m in pattern.finditer(text)
        ]
        if not spans:
            return CheckOutcome.clean()
        return CheckOutcome.hit(
            categories=["BANNED_TERM"],
            spans=spans,
            detail=f"{len(spans)} banned term match(es)",
        )


class URLCheck(GuardrailCheck):
    name = "url"
    label = "Link policy"
    description = "Flags links whose host is outside the allowed list, or on the blocked list."
    supported_stages = _ALL_TEXT_STAGES
    supports_redaction = True
    latency_hint_ms = 2
    max_match_chars = 2048

    # Matches the whole URL; the host is taken from the parsed authority rather
    # than from a capture group, so ``https://allowed.com@evil.tld`` cannot pass
    # its userinfo off as the host.
    _URL = re.compile(r"\bhttps?://[^\s<>\"')]+", re.IGNORECASE)

    @classmethod
    def validate_settings(cls, settings: Dict[str, Any]) -> Dict[str, Any]:
        allow = settings.get("allow_hosts") or []
        block = settings.get("block_hosts") or []
        for name, value in (("allow_hosts", allow), ("block_hosts", block)):
            if not isinstance(value, list):
                raise ValueError(f"{name} must be a list")
            if len(value) > 200:
                raise ValueError(f"{name} accepts at most 200 hosts")
        if not allow and not block:
            raise ValueError("provide allow_hosts or block_hosts")
        return {
            "allow_hosts": [str(h).strip().lower().lstrip(".") for h in allow if str(h).strip()],
            "block_hosts": [str(h).strip().lower().lstrip(".") for h in block if str(h).strip()],
        }

    @staticmethod
    def _host_matches(host: str, entry: str) -> bool:
        return host == entry or host.endswith("." + entry)

    @staticmethod
    def _host_of(url: str) -> Optional[str]:
        """The authority's host, or None when the URL will not parse."""
        try:
            return urlsplit(url).hostname
        except ValueError:
            return None

    def scan(self, text: str, stage: Stage, context: ScanContext) -> CheckOutcome:
        allow = self.settings.get("allow_hosts") or []
        block = self.settings.get("block_hosts") or []
        spans: List[Span] = []
        for match in self._URL.finditer(text):
            host = self._host_of(match.group(0))
            if host is None:
                # A URL we cannot resolve is one we cannot vouch for.
                spans.append(
                    Span(match.start(), match.end(), "URL", replacement="<url redacted>")
                )
                continue
            denied = any(self._host_matches(host, b) for b in block)
            if not denied and allow:
                denied = not any(self._host_matches(host, a) for a in allow)
            if denied:
                spans.append(
                    Span(match.start(), match.end(), "URL", replacement="<url redacted>")
                )
        if not spans:
            return CheckOutcome.clean()
        return CheckOutcome.hit(
            categories=["URL"], spans=spans, detail=f"{len(spans)} disallowed link(s)"
        )
