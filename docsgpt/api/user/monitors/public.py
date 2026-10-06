"""Public link routes: webhook trigger links and human approval links.

No session: the token in the URL is the credential (``authenticate_request``
skips these paths, so a sender's own ``Authorization`` header can't get a
delivery refused). The rules live in :mod:`docsgpt.monitors.triggers`; these
handlers only read the request and shape the response.
"""

from __future__ import annotations

import logging

from flask import Response, jsonify, make_response, request
from flask_restx import Namespace, Resource

from docsgpt.api import api
from docsgpt.core.settings import settings
from docsgpt.monitors import triggers

logger = logging.getLogger(__name__)

triggers_ns = Namespace("triggers", description="Public webhook trigger links of monitors", path="/api")

#: What a GET on a POST-only link gets.
_GET_TEXT = (
    "This is a webhook trigger link: it accepts POST requests only. Opening it in a browser does nothing.\n"
)


def _reply(status: int, body: dict):
    response = make_response(jsonify(body), status)
    if status == 429:
        response.headers["Retry-After"] = "60"
    response.headers["Cache-Control"] = "no-store"
    return response


@triggers_ns.route("/triggers/<string:token>")
class TriggerLink(Resource):
    @api.doc(
        description=(
            "Deliver an event to a monitor's webhook trigger link. Public: the token is the credential. "
            "Accepts JSON, form or text up to TRIGGER_MAX_PAYLOAD_BYTES. Signed links verify Standard Webhooks "
            "(webhook-id/webhook-timestamp/webhook-signature, 5 minute tolerance), GitHub X-Hub-Signature-256, "
            "or X-Signature: sha256=<hex>. Deduplicated on Idempotency-Key, webhook-id or X-GitHub-Delivery, "
            "else the body hash. 202 when accepted; 404 for an unknown, expired, revoked or used-up link; 401 "
            "for a bad signature; 413 for a large body; 429 past TRIGGER_RATE_PER_MINUTE."
        ),
        params={"token": "The link's token."},
        security=[],
    )
    def post(self, token: str):
        limit = int(settings.TRIGGER_MAX_PAYLOAD_BYTES)
        if request.content_length is not None and request.content_length > limit:
            return _reply(413, {"error": f"the body is larger than {limit} bytes"})
        body = request.stream.read(limit + 1)
        if len(body) > limit:
            return _reply(413, {"error": f"the body is larger than {limit} bytes"})
        try:
            status, payload = triggers.accept_delivery(
                token, body=body, headers=dict(request.headers), content_type=request.content_type or ""
            )
        except Exception:
            logger.exception("trigger delivery failed")
            return _reply(500, {"error": "the delivery could not be stored; retry later"})
        return _reply(status, payload)

    @api.doc(
        description=(
            "A GET call, taken only by a link created with methods [\"POST\", \"GET\"]: the query parameters are "
            "the delivery (a dotted key nests). A HEAD, a prefetch (Purpose / Sec-Purpose: prefetch) or a known "
            "link-preview or crawler User-Agent gets 200 {ignored} and changes nothing. 202 when accepted, 405 "
            "for a POST-only link, 404 for an unknown, expired, revoked or used-up one, 429 when rate limited."
        ),
        params={"token": "The link's token."},
        security=[],
    )
    def get(self, token: str):
        limit = int(settings.TRIGGER_MAX_PAYLOAD_BYTES)
        if len(request.query_string or b"") > limit:
            return _reply(413, {"error": f"the query is longer than {limit} bytes"})
        try:
            status, payload = triggers.accept_delivery(
                token,
                body=b"",
                headers=dict(request.headers),
                content_type="",
                method=request.method,
                query=request.args.items(multi=True),
            )
        except Exception:
            logger.exception("trigger GET delivery failed")
            return _reply(500, {"error": "the delivery could not be stored; retry later"})
        if status == 405:
            return Response(_GET_TEXT, status=405, mimetype="text/plain", headers={"Allow": "POST"})
        return _reply(status, payload)


approvals_ns = Namespace("approvals", description="Public human approval links of monitors", path="/api")

#: Largest decision body accepted (a decision and a comment).
_MAX_DECISION_BYTES = 16 * 1024


@approvals_ns.route("/approvals/<string:token>")
class ApprovalLink(Resource):
    @api.doc(
        description=(
            "What an approval link asks: its title, question, details, options and whether it was decided. "
            "Public (the token is the credential); reading it changes nothing."
        ),
        params={"token": "The link's token."},
        security=[],
    )
    def get(self, token: str):
        status, body = triggers.approval_view(token)
        return _reply(status, body)

    @api.doc(
        description=(
            "Decide an approval link: {decision, comment?}, where decision is one of its options. The first "
            "decision wins and resumes the conversation that asked; later ones get 409. 404 for an unknown, "
            "expired or revoked link, 400 for an option it doesn't offer, 429 when rate limited."
        ),
        params={"token": "The link's token."},
        security=[],
    )
    def post(self, token: str):
        if request.content_length is not None and request.content_length > _MAX_DECISION_BYTES:
            return _reply(413, {"error": "the decision is too large"})
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            data = request.form.to_dict() if request.form else {}
        try:
            status, body = triggers.decide(
                token, decision=data.get("decision"), comment=data.get("comment"), headers=dict(request.headers)
            )
        except Exception:
            logger.exception("approval decision failed")
            return _reply(500, {"error": "the decision could not be recorded; try again"})
        return _reply(status, body)
