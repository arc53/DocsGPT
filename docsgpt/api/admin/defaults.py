"""Admin > Defaults: the settings a new source (retrieval) and a new agent (guardrails) start with.

Behind ``@admin_required``. The defaults are copied into a source or an agent
when it is created (``docsgpt.storage.db.source_defaults``,
``docsgpt.storage.db.agent_defaults``); saving them never changes an existing
one. The GETs also say what the decision model costs on this server, from this
process's measured speed: nothing here loads, warms or times the model.
Members read the defaults themselves, without the cost, from
``GET /api/sources/defaults`` and ``GET /api/agents/defaults``.
"""

from __future__ import annotations

import logging

from flask import jsonify, make_response, request
from flask_restx import Resource
from pydantic import ValidationError

from docsgpt import decisions
from docsgpt.api.admin.guardrails import audit, injection_model, validation_error
from docsgpt.api.admin.routes import _actor, admin_ns
from docsgpt.api.user.authz import admin_required
from docsgpt.core.settings import settings
from docsgpt.decisions import features
from docsgpt.guardrails.config import GuardrailsConfig
from docsgpt.retriever.retriever_creator import RetrieverCreator
from docsgpt.storage.db import agent_defaults, source_defaults
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.storage.db.source_config import DEFAULT_CANDIDATE_K, RetrievalConfig, validation_message

logger = logging.getLogger(__name__)


def relevance_model() -> dict:
    """The relevance model as the Defaults panel shows it.

    ``predicted_s`` is the measured prediction for one relevance call over the
    default ``candidate_k`` chunks on this machine, in the shape the stage
    sends (best-window passages on a CPU runtime, whole chunks elsewhere), or
    ``None`` before the model has been measured. ``timeout_s`` is the deadline
    past which the call falls back to retriever order.
    """
    info = decisions.model_info()
    predicted = decisions.predict_s(features.shape_of(features.RAG_RERANK))
    return {
        "enabled": bool(settings.DECISION_RELEVANCE_ENABLED and decisions.available()),
        "predicted_s": None if predicted is None else round(predicted, 3),
        "timeout_s": float(settings.DECISION_RELEVANCE_TIMEOUT),
        "candidate_k": DEFAULT_CANDIDATE_K,
        "runtime": info.runtime if info else None,
    }


def _bad(message: str):
    return make_response(jsonify({"success": False, "message": message}), 400)


def _changes(before: dict, after: dict) -> dict:
    """``{field: [before, after]}`` for the fields of ``after`` that differ from ``before``."""
    return {key: [before.get(key), value] for key, value in after.items() if before.get(key) != value}


def _sources_body(retrieval: dict) -> dict:
    return {"success": True, "retrieval": retrieval, "relevance_model": relevance_model()}


@admin_ns.route("/admin/defaults/sources")
class AdminSourceDefaultsResource(Resource):
    @admin_required
    def get(self):
        """The default retrieval settings for new sources, and what relevance costs on this server."""
        with db_readonly() as conn:
            retrieval = source_defaults.load(conn)
        return make_response(jsonify(_sources_body(retrieval)), 200)

    @admin_required
    def put(self):
        """Store the body's `retrieval` object as the default for new sources; existing sources keep their own."""
        body = request.get_json(silent=True)
        raw = body.get("retrieval") if isinstance(body, dict) else None
        if not isinstance(raw, dict):
            return _bad("retrieval must be an object")
        try:
            retrieval = RetrievalConfig.model_validate(raw)
        except ValidationError as err:
            return _bad(validation_message(err, "Invalid retrieval config: one or more fields failed validation."))
        if retrieval.retriever not in RetrieverCreator.retrievers:
            return _bad(f"Unknown retriever '{retrieval.retriever}'.")
        with db_session() as conn:
            before = source_defaults.load(conn)
            after = source_defaults.save(conn, retrieval)
            changes = _changes(before, after)
            if changes:
                audit(conn, "source_defaults_set", changes)
        logger.info("source_defaults_updated", extra={"admin": _actor(), "fields": sorted(changes)})
        return make_response(jsonify(_sources_body(after)), 200)


def _agents_body(guardrails: dict) -> dict:
    return {"success": True, "guardrails": guardrails, "injection_model": injection_model()}


@admin_ns.route("/admin/defaults/agents")
class AdminAgentDefaultsResource(Resource):
    @admin_required
    def get(self):
        """The guardrails new agents start with, and what the injection model costs on this server."""
        with db_readonly() as conn:
            guardrails = agent_defaults.load(conn)
        return make_response(jsonify(_agents_body(guardrails)), 200)

    @admin_required
    def put(self):
        """Store the body's `guardrails` object as the default for new agents; existing agents keep their own."""
        body = request.get_json(silent=True)
        raw = body.get("guardrails") if isinstance(body, dict) else None
        if not isinstance(raw, dict):
            return _bad("guardrails must be an object")
        try:
            guardrails = GuardrailsConfig.model_validate(raw)
        except ValidationError as err:
            return _bad(validation_error("guardrails", err))
        with db_session() as conn:
            before = agent_defaults.load(conn)
            after = agent_defaults.save(conn, guardrails)
            changes = _changes(before, after)
            if changes:
                audit(conn, "agent_defaults_set", changes)
        logger.info("agent_defaults_updated", extra={"admin": _actor(), "fields": sorted(changes)})
        return make_response(jsonify(_agents_body(after)), 200)
