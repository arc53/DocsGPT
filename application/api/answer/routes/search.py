import logging
from typing import Any, Dict, List, Optional

from flask import make_response, request
from flask_restx import fields, Resource

from bson.dbref import DBRef

from application.api.answer.routes.base import answer_ns
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.vectorstore.vector_creator import VectorCreator

logger = logging.getLogger(__name__)


@answer_ns.route("/api/search")
class SearchResource(Resource):
    """Fast search endpoint for retrieving relevant documents"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        mongo = MongoDB.get_client()
        self.db = mongo[settings.MONGO_DB_NAME]
        self.agents_collection = self.db["agents"]

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
        """Get source IDs connected to the API key/agent.

        """
        agent_data = self.agents_collection.find_one({"key": api_key})
        if not agent_data:
            return []

        source_ids = []

        # Handle multiple sources (only if non-empty)
        sources = agent_data.get("sources", [])
        if sources and isinstance(sources, list) and len(sources) > 0:
            for source_ref in sources:
                # Skip "default" - it's a placeholder, not an actual vectorstore
                if source_ref == "default":
                    continue
                elif isinstance(source_ref, DBRef):
                    source_doc = self.db.dereference(source_ref)
                    if source_doc:
                        source_ids.append(str(source_doc["_id"]))

        # Handle single source (legacy) - check if sources was empty or didn't yield results
        if not source_ids:
            source = agent_data.get("source")
            if isinstance(source, DBRef):
                source_doc = self.db.dereference(source)
                if source_doc:
                    source_ids.append(str(source_doc["_id"]))
            # Skip "default" - it's a placeholder, not an actual vectorstore
            elif source and source != "default":
                source_ids.append(source)

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
        agent = self.agents_collection.find_one({"key": api_key})
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
