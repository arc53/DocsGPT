"""Retrieval test — preview the chunks a query actually retrieves from a source.

The chunk browser's ``search`` (``/api/get_chunks``) is a substring filter over
stored text; it says nothing about what a RAG query would retrieve. This
endpoint runs the *production* retrieval path against a single source so a user
can see the real ranked chunks for a query, and try retrieval settings without
saving them.

It deliberately builds a ``Dispatcher`` — the same object the answer pipeline
uses — so retriever selection, per-source ``chunks`` / ``score_threshold``, the
prescreen stage and the token budget all behave exactly as they do at answer
time, rather than drifting from them.
"""

import logging
import math
import time

from flask import jsonify, make_response, request
from flask_restx import fields, Namespace, Resource
from pydantic import ValidationError

from application.api import api
from application.api.user.sources.routes import _resolve_readable_source
from application.core.model_utils import get_default_model_id
from application.retriever.dispatcher import Dispatcher
from application.retriever.retriever_creator import RetrieverCreator
from application.storage.db.session import db_readonly
from application.storage.db.source_config import RetrievalConfig, SourceConfig
from application.utils import num_tokens_from_string

logger = logging.getLogger(__name__)

sources_search_ns = Namespace(
    "sources", description="Source retrieval testing", path="/api"
)

# A retrieval query is a search query, not a document.
MAX_QUERY_LENGTH = 2000

# The answer pipeline's default; keeps the preview's budgeting identical to it.
DOC_TOKEN_LIMIT = 50000

# Cost-attribution tag for any LLM call the preview makes (prescreen only —
# with no chat history the rephrase side-call is skipped entirely).
USAGE_SOURCE = "retrieval_test"

# Ceiling on the prescreen LLM calls a single test may trigger.
MAX_PRESCREEN_BATCHES = 20


@sources_search_ns.route("/sources/<string:source_id>/search")
class SourceSearch(Resource):
    search_model = api.model(
        "SourceSearchModel",
        {
            "query": fields.String(
                required=True, description="The query to retrieve for"
            ),
            "retrieval": fields.Raw(
                required=False,
                description="Ad-hoc retrieval config to test with. Omit to use "
                "the source's saved config. Never persisted.",
            ),
        },
    )

    @api.expect(search_model)
    @api.doc(
        description="Run the real retrieval pipeline against one source and "
        "return the ranked chunks it produces, optionally under an ad-hoc "
        "retrieval config. Read-only: nothing is saved."
    )
    def post(self, source_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return make_response(
                jsonify({"success": False, "message": "Invalid request body"}), 400
            )
        query = (body.get("query") or "").strip()
        if not query:
            return make_response(
                jsonify({"success": False, "message": "Query is required"}), 400
            )
        if len(query) > MAX_QUERY_LENGTH:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": f"Query must be at most {MAX_QUERY_LENGTH} characters",
                    }
                ),
                400,
            )

        try:
            # Read access = owner or any team grant (viewer included), matching
            # the other source read endpoints (wiki pages, graph).
            with db_readonly() as conn:
                doc = _resolve_readable_source(conn, source_id, user)
        except Exception as e:
            # An unresolvable id yields None (→ 404); reaching here means the
            # lookup itself failed, which is ours, not the caller's.
            logger.error(f"Error resolving source: {e}", exc_info=True)
            return make_response(
                jsonify({"success": False, "message": "Could not resolve source"}), 500
            )
        if not doc:
            return make_response(
                jsonify(
                    {"success": False, "message": "Source not found or access denied"}
                ),
                404,
            )
        resolved_id = str(doc["id"])

        # A supplied config is validated exactly as strictly as a saved one (D7
        # strict-on-write), with the same static message so validation internals
        # aren't echoed back. Absent → the source's saved config.
        saved = SourceConfig.parse(doc.get("config")).retrieval
        if body.get("retrieval") is not None:
            try:
                retrieval = RetrievalConfig.model_validate(body["retrieval"])
            except ValidationError:
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Invalid retrieval config: one or more "
                            "fields failed validation.",
                        }
                    ),
                    400,
                )
        else:
            retrieval = saved

        # "Ad-hoc" means the caller is testing something the source is NOT
        # already configured to do. The client always sends the config it has on
        # screen — including an untouched one — so compare by value rather than
        # trusting the body's presence, or a source whose saved config is
        # expensive could never be tested at all (see the ceiling below).
        ad_hoc = retrieval != saved

        # RetrievalConfig.retriever is a free string, so an unknown key would
        # only blow up inside RetrieverCreator — a caller's typo must be a 400,
        # not a 500.
        if retrieval.retriever not in RetrieverCreator.retrievers:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": f"Unknown retriever '{retrieval.retriever}'.",
                    }
                ),
                400,
            )

        # Prescreen screens candidate_k candidates in batches of batch_size, one
        # synchronous LLM call each, so candidate_k=500 / batch_size=1 is 500
        # provider calls in one request; RetrievalConfig bounds each field but
        # not their ratio. Only an ad-hoc config is capped: a config already
        # saved on the source runs at answer time anyway, so refusing to test it
        # would defeat the endpoint.
        if ad_hoc:
            ps = retrieval.prescreen_config()
            if ps is not None:
                batches = math.ceil(ps.candidate_k / ps.batch_size)
                if batches > MAX_PRESCREEN_BATCHES:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": (
                                    f"This prescreen config needs {batches} LLM "
                                    f"calls to test (limit "
                                    f"{MAX_PRESCREEN_BATCHES}). Raise batch_size "
                                    "or lower candidate_k."
                                ),
                            }
                        ),
                        400,
                    )

        # A test has no chat behind it, so no model was requested. Resolve the
        # same instance default the answer path falls back to: with a bogus id
        # the prescreen stage would call the provider, fail, and silently keep
        # every candidate. On an instance with no models configured this is
        # None — leave the retriever's own default in place rather than
        # forwarding it.
        dispatcher_kwargs = {}
        default_model_id = get_default_model_id()
        if default_model_id:
            dispatcher_kwargs["model_id"] = default_model_id

        try:
            started = time.monotonic()
            # Dispatcher directly, NOT build_dispatcher: the
            # PER_SOURCE_RETRIEVAL_ENABLED kill-switch would fall back to a
            # stock classic retriever and ignore the config under test.
            retriever = Dispatcher(
                source={"active_docs": [resolved_id], "question": query},
                chat_history=[],  # no history ⇒ no rephrase side-call
                chunks=retrieval.chunks,
                doc_token_limit=DOC_TOKEN_LIMIT,
                decoded_token=decoded_token,
                sources=[{"id": resolved_id, "retrieval": retrieval}],
                include_scores=True,
                usage_source=USAGE_SOURCE,
                **dispatcher_kwargs,
            )
            docs = retriever.search(query) or []
            latency_ms = int((time.monotonic() - started) * 1000)
        except Exception as e:
            logger.error(f"Retrieval test failed: {e}", exc_info=True)
            return make_response(
                jsonify({"success": False, "message": "Retrieval failed"}), 500
            )

        chunks = [
            {
                "rank": idx,
                "text": d.get("text", ""),
                "title": d.get("title"),
                "filename": d.get("filename"),
                "source": d.get("source"),
                "tokens": num_tokens_from_string(d.get("text", "")),
                # None for retrievers/stores that produce no comparable score
                # (graphrag's PPR ranking, stores without a score seam).
                "score": d.get("score"),
                "score_kind": d.get("score_kind"),
            }
            for idx, d in enumerate(docs, start=1)
        ]

        return make_response(
            jsonify(
                {
                    "success": True,
                    "query": query,
                    "retriever": retrieval.retriever,
                    "retrieval": retrieval.model_dump(),
                    "total": len(chunks),
                    "latency_ms": latency_ms,
                    "chunks": chunks,
                }
            ),
            200,
        )
