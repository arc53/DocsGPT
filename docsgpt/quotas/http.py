"""HTTP rendering of a quota refusal."""

from __future__ import annotations

from flask import Response, jsonify, make_response

from docsgpt.quotas.service import QuotaExceeded


def quota_exceeded_response(exceeded: QuotaExceeded) -> Response:
    """Return the 429 for an exhausted quota, with ``Retry-After`` set to the reset."""
    response = make_response(jsonify(exceeded.to_payload()), 429)
    response.headers["Retry-After"] = str(exceeded.retry_after_seconds)
    # The reset can be weeks away; the OpenAI SDKs would otherwise retry with backoff.
    response.headers["x-should-retry"] = "false"
    return response
