"""Source document management chunk management."""

import math
import re
from typing import Optional

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from docsgpt.api import api
from docsgpt.api.user.base import get_vector_store
from docsgpt.api.user.resource_access import AccessDenied
from docsgpt.api.user.sources.access import denied_response, load_source
from docsgpt.core.settings import settings
from docsgpt.guardrails import injection_scoring
from docsgpt.guardrails.checks.model_injection import FLAG_THRESHOLD, THRESHOLD
from docsgpt.storage.db.repositories.sources import AllowlistFull, SourcesRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.storage.db.source_config import SourceConfig
from docsgpt.utils import check_required_fields, num_tokens_from_string
from docsgpt.vectorstore.base import InvalidChunkMetadataError
from docsgpt.vectorstore.index_lock import SourceBusy, source_index_lock

sources_chunks_ns = Namespace(
    "sources", description="Source document management operations", path="/api"
)

#: Chunk texts one source's owner may mark safe from prompt-injection screening.
INJECTION_REVIEW_MAX = 1000
_CONTENT_HASH = re.compile(r"[0-9a-f]{64}")

#: How long a chunk edit waits for a sync or page change on the source to finish before a 409.
CHUNK_EDIT_LOCK_WAIT_SECONDS = 3.0
_BUSY_NOTE = " 409 (code source_busy) while a sync or page change on the source runs."


def _index_lock(source_id: str):
    """The source's index lock, as a chunk edit takes it: a few seconds' wait, then ``SourceBusy``.

    A sync or a Website page change loads a FAISS index once and saves the
    whole of it, so a chunk edit made meanwhile would be lost (or lose the
    job's chunks). The index is loaded under the lock, after the job's save.

    Args:
        source_id: The source.

    Returns:
        The lock's context manager.
    """
    return source_index_lock(source_id, wait_seconds=CHUNK_EDIT_LOCK_WAIT_SECONDS, poll_seconds=0.25)


def _busy_response():
    """The 409 for a chunk edit while another change to the source runs."""
    return make_response(
        jsonify({
            "success": False,
            "error": "Another change to this source is still running; try again when it finishes",
            "code": "source_busy",
        }),
        409,
    )


def _resolve_source(doc_id: str, user: str, action: str = "use") -> dict:
    """Resolve a source (UUID or legacy ObjectId) the caller may ``action`` on.

    ``use`` (browse chunks) is open to every role; ``edit`` (add / delete /
    update chunks) needs owner or team editor. The vector partition is keyed
    by source id, so a team editor's write needs no owner id.

    Args:
        doc_id: Source id from the request.
        user: The caller's ``sub``.
        action: ``use`` for reads, ``edit`` for chunk writes.

    Returns:
        dict: The source row (PG UUID in ``id``).

    Raises:
        AccessDenied: 404 when not visible, 403 when the role can't do it.
    """
    with db_readonly() as conn:
        doc, _ra = load_source(conn, doc_id, user, action)
    return doc


def _remap_graph_chunk(doc: dict, old_chunk_id: str, new_chunk_id: str) -> None:
    """Move a graphrag source's links from an edited chunk's old id to its new one.

    Only needed when the store's ``update_chunk`` fell back to re-adding the
    chunk under a new id (stores that update in place keep the id). Without
    this the graph keeps pointing at the deleted row: the entity loses the
    chunk and retrieval stops returning it. A failure is logged, not raised,
    because the edit itself has already been saved.

    Args:
        doc: The resolved source row.
        old_chunk_id: The edited chunk's previous id.
        new_chunk_id: The id the edit was saved under.
    """
    from docsgpt.storage.db.source_config import SourceConfig

    if SourceConfig.parse(doc.get("config")).kind != "graphrag":
        return
    try:
        from docsgpt.graphrag.store import GraphStore

        GraphStore().remap_chunk(str(doc["id"]), old_chunk_id, new_chunk_id)
    except Exception as e:
        current_app.logger.error(
            f"Failed to remap graph links from chunk {old_chunk_id} to {new_chunk_id}: {e}",
            exc_info=True,
        )


def _has_usable_token_count(metadata: dict) -> bool:
    """Whether ``metadata`` already carries a count worth showing.

    Stores round-trip metadata differently -- pgvector keeps JSON types, the
    Mongo backend can hand back strings -- so a numeric string counts as
    recorded. Anything else (missing, empty, non-numeric, zero, negative, or
    non-finite) does not: ``float("inf")`` is greater than zero but is not a
    number of tokens, and it reaches ``toLocaleString`` in the UI as "∞".

    Args:
        metadata: A chunk's metadata mapping.

    Returns:
        True when ``token_count`` holds a finite positive number.
    """
    raw = metadata.get("token_count")
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return False
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value > 0


def _with_token_counts(chunks: list) -> list:
    """Fill in ``metadata.token_count`` for chunks that were stored without one.

    Ingestion records a per-chunk count in the embedding model's tokenizer,
    but chunks indexed before that was written -- and any path that rebuilt a
    chunk's metadata from scratch -- reach the UI without the key, which then
    renders a bare "-". The count recomputed here is cl100k rather than the
    embedding model's tokenizer: it is a display fallback, and loading the
    model's tokenizer would put a Hugging Face download in the request path.

    Only the page being returned is counted, so the cost is bounded by
    ``per_page`` rather than by the size of the index.

    Args:
        chunks: The chunk dicts about to be serialised.

    Returns:
        The same list, with each chunk's metadata normalised to a dict that
        carries a ``token_count``.
    """
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        if not _has_usable_token_count(metadata):
            metadata["token_count"] = num_tokens_from_string(chunk.get("text") or "")
        chunk["metadata"] = metadata
    return chunks


def _path_ends_with(value: str, path: str) -> bool:
    """Return whether ``value`` is ``path`` or ends with it at a ``/`` boundary.

    A bare ``endswith`` let a root ``setup.md`` also claim the chunks of
    ``guides/setup.md`` (and ``a.md`` those of ``data.md``).
    """
    return bool(value) and (value == path or value.endswith(f"/{path}"))


def _chunk_matches_path(metadata: dict, path: str) -> bool:
    """Return whether a chunk belongs to the tree file at ``path``.

    Args:
        metadata: The chunk's stored metadata.
        path: The file's key path in the source's ``directory_structure``.

    Returns:
        True when the chunk's ``source`` or ``file_path`` names that file, or
        when the worker could only have keyed it by title: a remote ingest
        (web page, Reddit post) whose chunks carry no ``file_path`` or ``key``
        (see ``remote_worker``). Sources ingested that way stay browsable
        without a re-ingest.
    """
    source = metadata.get("source") or ""
    file_path = metadata.get("file_path") or ""
    if _path_ends_with(source, path) or _path_ends_with(file_path, path):
        return True
    if "://" in source and not file_path and not metadata.get("key"):
        return metadata.get("title") == path
    return False


def _injection_level(p) -> str | None:
    """``high`` from the threshold a blocking control acts at, ``suspected`` from the flag threshold."""
    if p is None:
        return None
    if p >= THRESHOLD:
        return "high"
    return "suspected" if p >= FLAG_THRESHOLD else None


def _with_injection(chunks: list, doc: dict) -> list:
    """Attach each chunk's prompt-injection score as ``injection``, from the score cache in one query.

    ``{content_hash, p, level, allowed}``: the sha256 of the text (what
    ``injection_review`` takes), the cached probability (``None`` before the
    chunk was scored), ``high`` or ``suspected`` or ``None``, and whether the
    owner marked it safe. ``None`` instead while the operator has not enabled
    the model (``DECISION_INJECTION_ENABLED``).

    Args:
        chunks: The chunk dicts.
        doc: The source row, for its owner allowlist.

    Returns:
        The same list.
    """
    if not settings.DECISION_INJECTION_ENABLED:
        for chunk in chunks:
            chunk["injection"] = None
        return chunks
    review = ((doc.get("metadata") or {}).get("injection_review") or {})
    allowed = set(review.get("allowed") or []) if isinstance(review, dict) else set()
    texts = [chunk.get("text") or "" for chunk in chunks]
    for chunk, text, score in zip(chunks, texts, injection_scoring.lookup(texts)):
        p = round(score.p, 4) if score is not None else None
        digest = injection_scoring.content_hash(text)
        chunk["injection"] = {
            "content_hash": digest, "p": p, "level": _injection_level(p), "allowed": digest in allowed,
        }
    return chunks


@sources_chunks_ns.route("/get_chunks")
class GetChunks(Resource):
    @api.doc(
        description="Retrieves chunks from a document, optionally filtered by file path and search term",
        params={
            "id": "The document ID",
            "page": "Page number for pagination",
            "per_page": "Number of chunks per page",
            "path": "Optional: Filter chunks by relative file path",
            "search": "Optional: Search term to filter chunks by title or content",
            "injection": (
                "Optional: `flagged` keeps the chunks whose cached prompt-injection score is suspected or high "
                "(marked safe ones included)"
            ),
        },
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        doc_id = request.args.get("id")
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 10))
        path = request.args.get("path")
        search_term = request.args.get("search", "").strip().lower()
        flagged_only = request.args.get("injection") == "flagged"

        if not doc_id:
            return make_response(jsonify({"error": "Invalid doc_id"}), 400)
        try:
            doc = _resolve_source(doc_id, user)
        except AccessDenied as err:
            return denied_response(err)
        except Exception as e:
            current_app.logger.error(f"Error resolving source: {e}", exc_info=True)
            return make_response(jsonify({"error": "Invalid doc_id"}), 400)
        resolved_id = str(doc["id"])
        try:
            store = get_vector_store(resolved_id)
            chunks = store.get_chunks()

            filtered_chunks = []
            for chunk in chunks:
                metadata = chunk.get("metadata", {})

                if path and not _chunk_matches_path(metadata, path):
                    continue
                if search_term:
                    text_match = search_term in chunk.get("text", "").lower()
                    title_match = search_term in metadata.get("title", "").lower()

                    if not (text_match or title_match):
                        continue
                filtered_chunks.append(chunk)
            chunks = filtered_chunks
            if flagged_only:
                # Every chunk is scored up front so the page and the total
                # count only the flagged ones.
                chunks = [
                    c for c in _with_injection(chunks, doc)
                    if c["injection"] is not None and c["injection"]["level"] is not None
                ]

            total_chunks = len(chunks)
            start = (page - 1) * per_page
            end = start + per_page
            paginated_chunks = _with_token_counts(chunks[start:end])
            if not flagged_only:
                _with_injection(paginated_chunks, doc)

            return make_response(
                jsonify(
                    {
                        "page": page,
                        "per_page": per_page,
                        "total": total_chunks,
                        "chunks": paginated_chunks,
                        "path": path if path else None,
                        "search": search_term if search_term else None,
                        "injection": "flagged" if flagged_only else None,
                    }
                ),
                200,
            )
        except Exception as e:
            current_app.logger.error(f"Error getting chunks: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)


_CHUNK_KEY = re.compile(r"[0-9a-f]{32}")
# The start of a passage is enough to find it; a cap keeps the scan's needle small.
_EXCERPT_MAX = 200


def _citation_source(doc: dict, access: dict) -> dict:
    """What a citation reader needs about the chunk's source.

    Enough to name it, pick its view in Knowledge (``kind``, ``isNested``)
    and gate its actions, without the behaviour config a viewer may not see.

    Args:
        doc: The source row.
        access: ``ResourceAccess.payload()`` for the caller.

    Returns:
        dict: ``id``, ``name``, ``type``, ``kind``, ``date``, ``retriever``,
        ``isNested``, ``access`` and ``allowed_actions``.
    """
    kind = "wiki" if doc.get("type") == "wiki" else SourceConfig.parse(doc.get("config")).kind
    return {
        "id": str(doc["id"]),
        "name": doc.get("name", ""),
        "type": doc.get("type") or "file",
        "kind": kind,
        "date": doc.get("date", ""),
        "retriever": doc.get("retriever") or "classic",
        "isNested": bool(doc.get("directory_structure")),
        **access,
    }


@sources_chunks_ns.route("/sources/<string:source_id>/chunk")
class ChunkByKey(Resource):
    @api.doc(
        description=(
            "The chunk behind a citation, found by its content key, else by its "
            "excerpt, with what the reader needs about its source. 404 when the "
            "caller cannot see the source, or with reason chunk_missing when "
            "neither finds the chunk (the source was edited); 501 with reason "
            "unsupported when the vector store cannot look chunks up."
        ),
        params={
            "chunk_key": "The citation's ``chunk_key``: the MD5 of the chunk text",
            "excerpt": "Optional: the start of the cited passage, searched when the key misses",
        },
    )
    def get(self, source_id: str):
        """Return the cited chunk and its source.

        Args:
            source_id: The source the citation names.

        Returns:
            Response: ``{"success", "chunk", "source", "page_path"}``, or an
            error with ``reason`` ``chunk_missing`` (404) or ``unsupported``
            (501) the reader tells apart from a source out of reach.
        """
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        key = (request.args.get("chunk_key") or "").strip().lower()
        if not _CHUNK_KEY.fullmatch(key):
            return make_response(
                jsonify({"success": False, "message": "chunk_key must be 32 hex characters"}), 400
            )
        excerpt = (request.args.get("excerpt") or "").strip()[:_EXCERPT_MAX] or None
        try:
            with db_readonly() as conn:
                doc, ra = load_source(conn, source_id, user, "use")
        except AccessDenied as err:
            return denied_response(err)
        except Exception as e:
            current_app.logger.error(f"Error resolving source: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        try:
            chunk = get_vector_store(str(doc["id"])).get_chunk_by_key(key, excerpt=excerpt)
        except NotImplementedError:
            return make_response(
                jsonify({"success": False, "message": "Chunk lookup not supported", "reason": "unsupported"}),
                501,
            )
        except Exception as e:
            current_app.logger.error(f"Error finding chunk {key} in {doc['id']}: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        if chunk is None:
            return make_response(
                jsonify({"success": False, "message": "Chunk not found", "reason": "chunk_missing"}), 404
            )
        source = _citation_source(doc, ra.payload())
        metadata = chunk.get("metadata") or {}
        return make_response(
            jsonify(
                {
                    "success": True,
                    "chunk": _with_token_counts([chunk])[0],
                    "source": source,
                    # A wiki chunk is cut from a page, and its ``source`` is that
                    # page's path, which the wiki viewer opens directly.
                    "page_path": metadata.get("source") if source["kind"] == "wiki" else None,
                }
            ),
            200,
        )


@sources_chunks_ns.route("/add_chunk")
class AddChunk(Resource):
    @api.expect(
        api.model(
            "AddChunkModel",
            {
                "id": fields.String(required=True, description="Document ID"),
                "text": fields.String(required=True, description="Text of the chunk"),
                "metadata": fields.Raw(
                    required=False,
                    description="Metadata associated with the chunk",
                ),
            },
        )
    )
    @api.doc(
        description="Adds a new chunk to the document." + _BUSY_NOTE,
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "text"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        doc_id = data.get("id")
        text = data.get("text")
        metadata = data.get("metadata", {})
        token_count = num_tokens_from_string(text)
        metadata["token_count"] = token_count

        try:
            doc = _resolve_source(doc_id, user, "edit")
        except AccessDenied as err:
            return denied_response(err)
        except Exception as e:
            current_app.logger.error(f"Error resolving source: {e}", exc_info=True)
            return make_response(jsonify({"error": "Invalid doc_id"}), 400)
        try:
            with _index_lock(str(doc["id"])):
                store = get_vector_store(str(doc["id"]))
                chunk_id = store.add_chunk(text, metadata)
            return make_response(
                jsonify({"message": "Chunk added successfully", "chunk_id": chunk_id}),
                201,
            )
        except SourceBusy:
            return _busy_response()
        except Exception as e:
            current_app.logger.error(f"Error adding chunk: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)


@sources_chunks_ns.route("/delete_chunk")
class DeleteChunk(Resource):
    @api.doc(
        description="Deletes a specific chunk from the document." + _BUSY_NOTE,
        params={"id": "The document ID", "chunk_id": "The ID of the chunk to delete"},
    )
    def delete(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        doc_id = request.args.get("id")
        chunk_id = request.args.get("chunk_id")

        try:
            doc = _resolve_source(doc_id, user, "edit")
        except AccessDenied as err:
            return denied_response(err)
        except Exception as e:
            current_app.logger.error(f"Error resolving source: {e}", exc_info=True)
            return make_response(jsonify({"error": "Invalid doc_id"}), 400)
        try:
            with _index_lock(str(doc["id"])):
                store = get_vector_store(str(doc["id"]))
                # Only a chunk this source lists is deleted, as an update
                # checks: a store whose delete isn't scoped to the source
                # would otherwise remove another source's chunk by its id.
                listed = any(c.get("doc_id") == chunk_id for c in store.get_chunks() or [])
                deleted = listed and store.delete_chunk(chunk_id)
            if deleted:
                return make_response(
                    jsonify({"message": "Chunk deleted successfully"}), 200
                )
            else:
                return make_response(
                    jsonify({"message": "Chunk not found or could not be deleted"}),
                    404,
                )
        except SourceBusy:
            return _busy_response()
        except Exception as e:
            current_app.logger.error(f"Error deleting chunk: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)


@sources_chunks_ns.route("/update_chunk")
class UpdateChunk(Resource):
    @api.expect(
        api.model(
            "UpdateChunkModel",
            {
                "id": fields.String(required=True, description="Document ID"),
                "chunk_id": fields.String(
                    required=True, description="Chunk ID to update"
                ),
                "text": fields.String(
                    required=False, description="New text of the chunk"
                ),
                "metadata": fields.Raw(
                    required=False,
                    description="Updated metadata associated with the chunk",
                ),
            },
        )
    )
    @api.doc(
        description="Updates an existing chunk in the document." + _BUSY_NOTE,
    )
    def put(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "chunk_id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        doc_id = data.get("id")
        chunk_id = data.get("chunk_id")
        text = data.get("text")
        metadata = data.get("metadata")

        if text is not None:
            token_count = num_tokens_from_string(text)
            if metadata is None:
                metadata = {}
            metadata["token_count"] = token_count
        try:
            doc = _resolve_source(doc_id, user, "edit")
        except AccessDenied as err:
            return denied_response(err)
        except Exception as e:
            current_app.logger.error(f"Error resolving source: {e}", exc_info=True)
            return make_response(jsonify({"error": "Invalid doc_id"}), 400)
        try:
            with _index_lock(str(doc["id"])):
                return _update_chunk(doc, chunk_id, text, metadata)
        except SourceBusy:
            return _busy_response()
        except Exception as e:
            current_app.logger.error(f"Error updating chunk: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)


def _update_chunk(doc: dict, chunk_id: str, text: Optional[str], metadata: Optional[dict]):
    """Change one chunk's text and metadata; the caller holds the source's index lock.

    Args:
        doc: The source row.
        chunk_id: The chunk.
        text: Its new text, or ``None`` to keep it.
        metadata: Fields merged into its metadata, or ``None``.

    Returns:
        Response: 200 with the chunk's (possibly new) id, 404 when it is
        gone, 400 for metadata the store refuses, 500 when the store fails.
    """
    store = get_vector_store(str(doc["id"]))

    chunks = store.get_chunks()
    existing_chunk = next((c for c in chunks if c["doc_id"] == chunk_id), None)
    if not existing_chunk:
        return make_response(jsonify({"error": "Chunk not found"}), 404)
    new_text = text if text is not None else existing_chunk["text"]

    if metadata is not None:
        new_metadata = existing_chunk["metadata"].copy()
        new_metadata.update(metadata)
    else:
        new_metadata = existing_chunk["metadata"].copy()
    if text is not None:
        new_metadata["token_count"] = num_tokens_from_string(new_text)
    try:
        # In place where the store supports it (same id, same list
        # position); the base fallback re-adds under a new id.
        new_chunk_id = store.update_chunk(chunk_id, new_text, new_metadata)
        if new_chunk_id != chunk_id:
            _remap_graph_chunk(doc, chunk_id, new_chunk_id)
        return make_response(
            jsonify(
                {
                    "message": "Chunk updated successfully",
                    "chunk_id": new_chunk_id,
                    "original_chunk_id": chunk_id,
                }
            ),
            200,
        )
    except InvalidChunkMetadataError as meta_error:
        current_app.logger.warning(
            f"Rejected metadata for chunk {chunk_id}: {meta_error}"
        )
        return make_response(jsonify({"error": "Invalid metadata"}), 400)
    except Exception as add_error:
        current_app.logger.error(f"Failed to update chunk {chunk_id}: {add_error}")
        return make_response(
            jsonify({"error": "Failed to update chunk - addition failed"}), 500
        )


@sources_chunks_ns.route("/sources/<string:source_id>/injection_review")
class InjectionReview(Resource):
    @api.expect(
        api.model(
            "InjectionReviewModel",
            {
                "content_hash": fields.String(
                    required=True, description="The chunk's `injection.content_hash` (sha256 of its text)"
                ),
                "decision": fields.String(
                    required=True, enum=["allow", "clear"],
                    description="`allow` marks the chunk safe from prompt-injection screening; `clear` undoes it",
                ),
            },
        )
    )
    @api.doc(
        description=(
            "Mark a flagged chunk safe from prompt-injection screening for agents using this source, or undo "
            "that. Needs chunk-edit access. Keyed by the chunk text, so editing the chunk drops the mark. At most "
            f"{INJECTION_REVIEW_MAX} chunks per source. Returns `{{success, content_hash, allowed, count}}`."
        )
    )
    def post(self, source_id: str):
        """Add a chunk text's hash to the source's owner allowlist, or remove it.

        Args:
            source_id: The source.

        Returns:
            Response: ``{"success", "content_hash", "allowed", "count"}``, a
            400 for a bad body or a full allowlist, or the access error.
        """
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json(silent=True) or {}
        digest = data.get("content_hash")
        decision = data.get("decision")
        if not isinstance(digest, str) or not _CONTENT_HASH.fullmatch(digest):
            return make_response(
                jsonify({"success": False, "message": "content_hash must be 64 lowercase hex characters"}), 400
            )
        if decision not in ("allow", "clear"):
            return make_response(jsonify({"success": False, "message": "decision must be allow or clear"}), 400)
        try:
            with db_session() as conn:
                doc, _ra = load_source(conn, source_id, user, "edit")
                allowed = SourcesRepository(conn).review_injection(
                    str(doc["id"]), digest, decision == "allow", INJECTION_REVIEW_MAX
                )
        except AccessDenied as err:
            return denied_response(err)
        except AllowlistFull:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": f"At most {INJECTION_REVIEW_MAX} chunks of a source can be marked safe",
                    }
                ),
                400,
            )
        except Exception as e:
            current_app.logger.error(f"Error reviewing a chunk of source {source_id}: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        return make_response(
            jsonify(
                {
                    "success": True,
                    "content_hash": digest,
                    "allowed": decision == "allow",
                    "count": len(allowed or []),
                }
            ),
            200,
        )
