import logging
from typing import Any, Dict, List

from flask import make_response, request
from flask_restx import fields, Resource

from application.api.answer.routes.base import answer_ns
from application.core.settings import settings
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.session import db_readonly
from application.vectorstore.vector_creator import VectorCreator

logger = logging.getLogger(__name__)


@answer_ns.route("/api/search")
class SearchResource(Resource):
    """Fast search endpoint for retrieving relevant documents"""

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

    def _get_sources_from_api_key(self, api_key: str) -> List[str]:
        """Get source IDs connected to the API key/agent."""
        with db_readonly() as conn:
            agent_data = AgentsRepository(conn).find_by_key(api_key)
        if not agent_data:
            return []

        source_ids: List[str] = []
        # extra_source_ids is a PG ARRAY(UUID) of source UUIDs.
        extra = agent_data.get("extra_source_ids") or []
        for src in extra:
            if src:
                source_ids.append(str(src))

        if not source_ids:
            single = agent_data.get("source_id")
            if single:
                source_ids.append(str(single))

        return source_ids

    def _search_vectorstores(
        self, query: str, source_ids: List[str], chunks: int
    ) -> List[Dict[str, Any]]:
        """Search across vectorstores and return results"""
        if not source_ids:
            return []

        results = []
        chunks_per_source = max(1, chunks // len(source_ids))
        seen_texts = set()

        for source_id in source_ids:
            if not source_id or not source_id.strip():
                continue

            try:
                docsearch = VectorCreator.create_vectorstore(
                    settings.VECTOR_STORE, source_id, settings.EMBEDDINGS_KEY
                )
                docs = docsearch.search(query, k=chunks_per_source * 2)

                for doc in docs:
                    if len(results) >= chunks:
                        break

                    if hasattr(doc, "page_content") and hasattr(doc, "metadata"):
                        page_content = doc.page_content
                        metadata = doc.metadata
                    else:
                        page_content = doc.get("text", doc.get("page_content", ""))
                        metadata = doc.get("metadata", {})

                    # Skip duplicates
                    text_hash = hash(page_content[:200])
                    if text_hash in seen_texts:
                        continue
                    seen_texts.add(text_hash)

                    title = metadata.get(
                        "title", metadata.get("post_title", "")
                    )
                    if not isinstance(title, str):
                        title = str(title) if title else ""

                    # Clean up title
                    if title:
                        title = title.split("/")[-1]
                    else:
                        # Use filename or first part of content as title
                        title = metadata.get("filename", page_content[:50] + "...")

                    source = metadata.get("source", source_id)

                    results.append({
                        "text": page_content,
                        "title": title,
                        "source": source,
                    })

                if len(results) >= chunks:
                    break

            except Exception as e:
                logger.error(
                    f"Error searching vectorstore {source_id}: {e}",
                    exc_info=True,
                )
                continue

        return results[:chunks]

    @answer_ns.expect(search_model)
    @answer_ns.doc(description="Search for relevant documents based on query")
    def post(self):
        data = request.get_json()

        question = data.get("question")
        api_key = data.get("api_key")
        chunks = data.get("chunks", 5)

        if not question:
            return make_response({"error": "question is required"}, 400)

        if not api_key:
            return make_response({"error": "api_key is required"}, 400)

        # Validate API key
        with db_readonly() as conn:
            agent = AgentsRepository(conn).find_by_key(api_key)
        if not agent:
            return make_response({"error": "Invalid API key"}, 401)

        try:
            # Get sources connected to this API key
            source_ids = self._get_sources_from_api_key(api_key)

            if not source_ids:
                return make_response([], 200)

            # Perform search
            results = self._search_vectorstores(question, source_ids, chunks)

            return make_response(results, 200)

        except Exception as e:
            logger.error(
                f"/api/search - error: {str(e)}",
                extra={"error": str(e)},
                exc_info=True,
            )
            return make_response({"error": "Search failed"}, 500)
