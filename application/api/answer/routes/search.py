import logging

from flask import make_response, request
from flask_restx import fields, Resource

from application.api.answer.routes.base import answer_ns
from application.services.search_service import (
    InvalidAPIKey,
    SearchFailed,
    search,
)

logger = logging.getLogger(__name__)


@answer_ns.route("/api/search")
class SearchResource(Resource):
    """Fast search endpoint for retrieving relevant documents."""

    search_model = answer_ns.model(
        "SearchModel",
        {
            "question": fields.String(
                required=True, description="Search query"
            ),
            "api_key": fields.String(
                required=True, description="API key for authentication"
            ),
            "chunks": fields.Integer(
                required=False, default=5, description="Number of results to return"
            ),
        },
    )

    @answer_ns.expect(search_model)
    @answer_ns.doc(description="Search for relevant documents based on query")
    def post(self):
        data = request.get_json() or {}

        question = data.get("question")
        api_key = data.get("api_key")
        chunks = data.get("chunks", 5)

        if not question:
            return make_response({"error": "question is required"}, 400)
        if not api_key:
            return make_response({"error": "api_key is required"}, 400)

        try:
            return make_response(search(api_key, question, chunks), 200)
        except InvalidAPIKey:
            return make_response({"error": "Invalid API key"}, 401)
        except SearchFailed:
            logger.exception("/api/search failed")
            return make_response({"error": "Search failed"}, 500)
