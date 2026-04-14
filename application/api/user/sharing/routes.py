"""Conversation sharing routes."""

import uuid

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, inputs, Namespace, Resource
from sqlalchemy import text as _sql_text

from application.api import api
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.attachments import AttachmentsRepository
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.shared_conversations import (
    SharedConversationsRepository,
)
from application.storage.db.session import db_readonly, db_session
from application.utils import check_required_fields


sharing_ns = Namespace(
    "sharing", description="Conversation sharing operations", path="/api"
)


def _resolve_prompt_pg_id(conn, prompt_id_raw, user_id):
    """Translate an incoming prompt id (UUID or legacy Mongo ObjectId) to a PG UUID.

    Scoped by ``user_id`` so a caller can't link another user's prompt
    into their share record. Returns ``None`` for sentinel values
    (``"default"``) or unresolved ids.
    """
    if not prompt_id_raw or prompt_id_raw == "default":
        return None
    value = str(prompt_id_raw)
    # Already UUID — trust it but still require ownership.
    if len(value) == 36 and "-" in value:
        row = conn.execute(
            _sql_text(
                "SELECT id FROM prompts WHERE id = CAST(:pid AS uuid) "
                "AND user_id = :uid"
            ),
            {"pid": value, "uid": user_id},
        ).fetchone()
        return str(row[0]) if row else None
    # Legacy Mongo ObjectId fallback.
    row = conn.execute(
        _sql_text(
            "SELECT id FROM prompts WHERE legacy_mongo_id = :pid "
            "AND user_id = :uid"
        ),
        {"pid": value, "uid": user_id},
    ).fetchone()
    return str(row[0]) if row else None


def _resolve_source_pg_id(conn, source_raw):
    """Translate a source id (UUID or legacy Mongo ObjectId) to a PG UUID."""
    if not source_raw:
        return None
    value = str(source_raw)
    if len(value) == 36 and "-" in value:
        row = conn.execute(
            _sql_text(
                "SELECT id FROM sources WHERE id = CAST(:sid AS uuid)"
            ),
            {"sid": value},
        ).fetchone()
        return str(row[0]) if row else None
    row = conn.execute(
        _sql_text("SELECT id FROM sources WHERE legacy_mongo_id = :sid"),
        {"sid": value},
    ).fetchone()
    return str(row[0]) if row else None


def _find_reusable_share_agent(
    conn, user_id, *, prompt_pg_id, chunks, source_pg_id, retriever,
):
    """Find an existing share-as-agent key row matching these parameters.

    Mirrors the legacy Mongo ``agents_collection.find_one`` pre-existence
    check. Used to reuse an api key across repeated shares of the same
    conversation with the same prompt/chunks/source/retriever.
    """
    clauses = ["user_id = :uid", "key IS NOT NULL"]
    params: dict = {"uid": user_id}
    if prompt_pg_id is None:
        clauses.append("prompt_id IS NULL")
    else:
        clauses.append("prompt_id = CAST(:pid AS uuid)")
        params["pid"] = prompt_pg_id
    if chunks is None:
        clauses.append("chunks IS NULL")
    else:
        clauses.append("chunks = :chunks")
        params["chunks"] = int(chunks)
    if source_pg_id is None:
        clauses.append("source_id IS NULL")
    else:
        clauses.append("source_id = CAST(:sid AS uuid)")
        params["sid"] = source_pg_id
    if retriever is None:
        clauses.append("retriever IS NULL")
    else:
        clauses.append("retriever = :retr")
        params["retr"] = retriever
    sql = (
        "SELECT * FROM agents WHERE "
        + " AND ".join(clauses)
        + " LIMIT 1"
    )
    row = conn.execute(_sql_text(sql), params).fetchone()
    if row is None:
        return None
    mapping = dict(row._mapping)
    mapping["id"] = str(mapping["id"]) if mapping.get("id") else None
    return mapping


@sharing_ns.route("/share")
class ShareConversation(Resource):
    share_conversation_model = api.model(
        "ShareConversationModel",
        {
            "conversation_id": fields.String(
                required=True, description="Conversation ID"
            ),
            "user": fields.String(description="User ID (optional)"),
            "prompt_id": fields.String(description="Prompt ID (optional)"),
            "chunks": fields.Integer(description="Chunks count (optional)"),
        },
    )

    @api.expect(share_conversation_model)
    @api.doc(description="Share a conversation")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["conversation_id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        is_promptable = request.args.get("isPromptable", type=inputs.boolean)
        if is_promptable is None:
            return make_response(
                jsonify({"success": False, "message": "isPromptable is required"}), 400
            )
        conversation_id = data["conversation_id"]

        try:
            with db_session() as conn:
                conv_repo = ConversationsRepository(conn)
                shared_repo = SharedConversationsRepository(conn)
                agents_repo = AgentsRepository(conn)

                conversation = conv_repo.get_any(conversation_id, user)
                if conversation is None:
                    return make_response(
                        jsonify(
                            {
                                "status": "error",
                                "message": "Conversation does not exist",
                            }
                        ),
                        404,
                    )
                conv_pg_id = str(conversation["id"])
                current_n_queries = conv_repo.message_count(conv_pg_id)

                if is_promptable:
                    prompt_id_raw = data.get("prompt_id", "default")
                    chunks_raw = data.get("chunks", "2")
                    try:
                        chunks_int = int(chunks_raw) if chunks_raw not in (None, "") else None
                    except (TypeError, ValueError):
                        chunks_int = None

                    prompt_pg_id = _resolve_prompt_pg_id(conn, prompt_id_raw, user)
                    source_pg_id = _resolve_source_pg_id(conn, data.get("source"))
                    retriever = data.get("retriever")

                    reusable = _find_reusable_share_agent(
                        conn, user,
                        prompt_pg_id=prompt_pg_id,
                        chunks=chunks_int,
                        source_pg_id=source_pg_id,
                        retriever=retriever,
                    )
                    if reusable:
                        api_uuid = reusable.get("key")
                    else:
                        api_uuid = str(uuid.uuid4())
                        name = (conversation.get("name") or "") + "(shared)"
                        agents_repo.create(
                            user,
                            name,
                            "published",
                            key=api_uuid,
                            retriever=retriever,
                            chunks=chunks_int,
                            prompt_id=prompt_pg_id,
                            source_id=source_pg_id,
                        )

                    share = shared_repo.get_or_create(
                        conv_pg_id,
                        user,
                        is_promptable=True,
                        first_n_queries=current_n_queries,
                        api_key=api_uuid,
                        prompt_id=prompt_pg_id,
                        chunks=chunks_int,
                    )
                    return make_response(
                        jsonify(
                            {
                                "success": True,
                                "identifier": str(share["uuid"]),
                            }
                        ),
                        201 if reusable is None else 200,
                    )

                # Non-promptable share path.
                share = shared_repo.get_or_create(
                    conv_pg_id,
                    user,
                    is_promptable=False,
                    first_n_queries=current_n_queries,
                    api_key=None,
                )
                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "identifier": str(share["uuid"]),
                        }
                    ),
                    201,
                )
        except Exception as err:
            current_app.logger.error(
                f"Error sharing conversation: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)


@sharing_ns.route("/shared_conversation/<string:identifier>")
class GetPubliclySharedConversations(Resource):
    @api.doc(description="Get publicly shared conversations by identifier")
    def get(self, identifier: str):
        try:
            with db_readonly() as conn:
                shared_repo = SharedConversationsRepository(conn)
                conv_repo = ConversationsRepository(conn)
                attach_repo = AttachmentsRepository(conn)

                shared = shared_repo.find_by_uuid(identifier)
                if not shared or not shared.get("conversation_id"):
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": "might have broken url or the conversation does not exist",
                            }
                        ),
                        404,
                    )
                conv_pg_id = str(shared["conversation_id"])
                owner_user = shared.get("user_id")

                conversation = conv_repo.get_owned(conv_pg_id, owner_user) if owner_user else None
                if conversation is None:
                    # Fall back to any-user lookup in case shared row's
                    # user_id is missing — still keyed by PG UUID.
                    row = conn.execute(
                        _sql_text(
                            "SELECT * FROM conversations WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": conv_pg_id},
                    ).fetchone()
                    if row is None:
                        return make_response(
                            jsonify(
                                {
                                    "success": False,
                                    "error": "might have broken url or the conversation does not exist",
                                }
                            ),
                            404,
                        )
                    conversation = dict(row._mapping)

                messages = conv_repo.get_messages(conv_pg_id)
                first_n = shared.get("first_n_queries") or 0
                conversation_queries = []
                for msg in messages[:first_n]:
                    query = {
                        "prompt": msg.get("prompt"),
                        "response": msg.get("response"),
                        "thought": msg.get("thought"),
                        "sources": msg.get("sources") or [],
                        "tool_calls": msg.get("tool_calls") or [],
                        "timestamp": (
                            msg["timestamp"].isoformat()
                            if hasattr(msg.get("timestamp"), "isoformat")
                            else msg.get("timestamp")
                        ),
                        "feedback": msg.get("feedback"),
                    }
                    attachments = msg.get("attachments") or []
                    if attachments:
                        attachment_details = []
                        for attachment_id in attachments:
                            try:
                                attachment = attach_repo.get_any(
                                    str(attachment_id), owner_user,
                                ) if owner_user else None
                                if attachment:
                                    attachment_details.append(
                                        {
                                            "id": str(attachment["id"]),
                                            "fileName": attachment.get(
                                                "filename", "Unknown file"
                                            ),
                                        }
                                    )
                            except Exception as e:
                                current_app.logger.error(
                                    f"Error retrieving attachment {attachment_id}: {e}",
                                    exc_info=True,
                                )
                        query["attachments"] = attachment_details
                    conversation_queries.append(query)

                created = conversation.get("created_at") or conversation.get("date")
                date_iso = (
                    created.isoformat()
                    if hasattr(created, "isoformat")
                    else (str(created) if created is not None else None)
                )
                res = {
                    "success": True,
                    "queries": conversation_queries,
                    "title": conversation.get("name"),
                    "timestamp": date_iso,
                }
                if shared.get("is_promptable") and shared.get("api_key"):
                    res["api_key"] = shared["api_key"]
                return make_response(jsonify(res), 200)
        except Exception as err:
            current_app.logger.error(
                f"Error getting shared conversation: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
