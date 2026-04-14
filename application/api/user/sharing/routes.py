"""Conversation sharing routes."""

import uuid

from bson.binary import Binary, UuidRepresentation
from bson.dbref import DBRef
from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import fields, inputs, Namespace, Resource

from application.api import api
from application.api.user.base import (
    agents_collection,
    attachments_collection,
    conversations_collection,
    shared_conversations_collections,
)
from sqlalchemy import text as _sql_text

from application.storage.db.dual_write import dual_write
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.shared_conversations import (
    SharedConversationsRepository,
)
from application.utils import check_required_fields


def _dual_write_share(
    mongo_conv_id: str,
    share_uuid: str,
    user: str,
    *,
    is_promptable: bool,
    first_n_queries: int,
    api_key: str | None,
    prompt_id: str | None = None,
    chunks: int | None = None,
) -> None:
    """Mirror a Mongo share-record insert into Postgres.

    Preserves the Mongo-generated UUID so public ``/shared/{uuid}`` URLs
    resolve from both stores during cutover.
    """
    def _write(repo: SharedConversationsRepository) -> None:
        conv = ConversationsRepository(repo._conn).get_by_legacy_id(
            mongo_conv_id, user_id=user,
        )
        if conv is None:
            return
        # prompt_id / chunks are only meaningful for promptable shares;
        # prompt_id is often the string "default" or an ObjectId that
        # hasn't been migrated — pass as-is and let the repo drop
        # non-UUID values. Scope the prompt lookup by user_id so an
        # authenticated caller can't link another user's prompt into
        # their share record.
        resolved_prompt_id = None
        if prompt_id and len(str(prompt_id)) == 24:
            from sqlalchemy import text as _text
            row = repo._conn.execute(
                _text(
                    "SELECT id FROM prompts "
                    "WHERE legacy_mongo_id = :legacy_id AND user_id = :user_id"
                ),
                {"legacy_id": str(prompt_id), "user_id": user},
            ).fetchone()
            if row:
                resolved_prompt_id = str(row[0])
        # get_or_create is race-free on the PG side thanks to the
        # composite partial unique index on the dedup tuple
        # (migration 0008). It converges concurrent share requests to
        # a single row.
        repo.get_or_create(
            conv["id"],
            user,
            is_promptable=is_promptable,
            first_n_queries=first_n_queries,
            api_key=api_key,
            prompt_id=resolved_prompt_id,
            chunks=chunks,
            share_uuid=share_uuid,
        )

    dual_write(SharedConversationsRepository, _write)

sharing_ns = Namespace(
    "sharing", description="Conversation sharing operations", path="/api"
)


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
            conversation = conversations_collection.find_one(
                {"_id": ObjectId(conversation_id), "user": user}
            )
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
            current_n_queries = len(conversation["queries"])
            explicit_binary = Binary.from_uuid(
                uuid.uuid4(), UuidRepresentation.STANDARD
            )

            if is_promptable:
                prompt_id = data.get("prompt_id", "default")
                chunks = data.get("chunks", "2")

                name = conversation["name"] + "(shared)"
                new_api_key_data = {
                    "prompt_id": prompt_id,
                    "chunks": chunks,
                    "user": user,
                }

                if "source" in data and ObjectId.is_valid(data["source"]):
                    new_api_key_data["source"] = DBRef(
                        "sources", ObjectId(data["source"])
                    )
                if "retriever" in data:
                    new_api_key_data["retriever"] = data["retriever"]
                pre_existing_api_document = agents_collection.find_one(new_api_key_data)
                if pre_existing_api_document:
                    api_uuid = pre_existing_api_document["key"]
                    pre_existing = shared_conversations_collections.find_one(
                        {
                            "conversation_id": ObjectId(conversation_id),
                            "isPromptable": is_promptable,
                            "first_n_queries": current_n_queries,
                            "user": user,
                            "api_key": api_uuid,
                        }
                    )
                    if pre_existing is not None:
                        return make_response(
                            jsonify(
                                {
                                    "success": True,
                                    "identifier": str(pre_existing["uuid"].as_uuid()),
                                }
                            ),
                            200,
                        )
                    else:
                        shared_conversations_collections.insert_one(
                            {
                                "uuid": explicit_binary,
                                "conversation_id": ObjectId(conversation_id),
                                "isPromptable": is_promptable,
                                "first_n_queries": current_n_queries,
                                "user": user,
                                "api_key": api_uuid,
                            }
                        )
                        _dual_write_share(
                            conversation_id,
                            str(explicit_binary.as_uuid()),
                            user,
                            is_promptable=is_promptable,
                            first_n_queries=current_n_queries,
                            api_key=api_uuid,
                            prompt_id=prompt_id,
                            chunks=int(chunks) if chunks else None,
                        )
                        return make_response(
                            jsonify(
                                {
                                    "success": True,
                                    "identifier": str(explicit_binary.as_uuid()),
                                }
                            ),
                            201,
                        )
                else:
                    api_uuid = str(uuid.uuid4())
                    new_api_key_data["key"] = api_uuid
                    new_api_key_data["name"] = name

                    if "source" in data and ObjectId.is_valid(data["source"]):
                        new_api_key_data["source"] = DBRef(
                            "sources", ObjectId(data["source"])
                        )
                    if "retriever" in data:
                        new_api_key_data["retriever"] = data["retriever"]
                    share_agent_result = agents_collection.insert_one(new_api_key_data)
                    # Postgres mirror for the share-as-agent insert. The
                    # Mongo-side ``source`` is a DBRef; sources don't
                    # carry a ``legacy_mongo_id`` column yet (Phase 4),
                    # so source_id isn't mirrored here — the mirror row
                    # still captures name/key/retriever/chunks and the
                    # legacy id link.
                    def _mirror_share_agent(
                        repo: AgentsRepository,
                        data=new_api_key_data,
                        legacy_id=str(share_agent_result.inserted_id),
                        u=user,
                    ) -> None:
                        chunks_val = data.get("chunks")
                        try:
                            chunks_int = (
                                int(chunks_val) if chunks_val not in (None, "") else None
                            )
                        except (TypeError, ValueError):
                            chunks_int = None
                        prompt_val = data.get("prompt_id")
                        prompt_pg_id = None
                        if prompt_val and prompt_val != "default":
                            try:
                                row = repo._conn.execute(
                                    _sql_text(
                                        "SELECT id FROM prompts "
                                        "WHERE legacy_mongo_id = :lid "
                                        "AND user_id = :uid"
                                    ),
                                    {"lid": str(prompt_val), "uid": u},
                                ).fetchone()
                                if row:
                                    prompt_pg_id = str(row[0])
                            except Exception:
                                pass
                        repo.create(
                            u,
                            data.get("name", ""),
                            "published",
                            key=data.get("key"),
                            retriever=data.get("retriever"),
                            chunks=chunks_int,
                            prompt_id=prompt_pg_id,
                            legacy_mongo_id=legacy_id,
                        )
                    dual_write(AgentsRepository, _mirror_share_agent)
                    shared_conversations_collections.insert_one(
                        {
                            "uuid": explicit_binary,
                            "conversation_id": ObjectId(conversation_id),
                            "isPromptable": is_promptable,
                            "first_n_queries": current_n_queries,
                            "user": user,
                            "api_key": api_uuid,
                        }
                    )
                    _dual_write_share(
                        conversation_id,
                        str(explicit_binary.as_uuid()),
                        user,
                        is_promptable=is_promptable,
                        first_n_queries=current_n_queries,
                        api_key=api_uuid,
                        prompt_id=prompt_id,
                        chunks=int(chunks) if chunks else None,
                    )
                    return make_response(
                        jsonify(
                            {
                                "success": True,
                                "identifier": str(explicit_binary.as_uuid()),
                            }
                        ),
                        201,
                    )
            pre_existing = shared_conversations_collections.find_one(
                {
                    "conversation_id": ObjectId(conversation_id),
                    "isPromptable": is_promptable,
                    "first_n_queries": current_n_queries,
                    "user": user,
                }
            )
            if pre_existing is not None:
                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "identifier": str(pre_existing["uuid"].as_uuid()),
                        }
                    ),
                    200,
                )
            else:
                shared_conversations_collections.insert_one(
                    {
                        "uuid": explicit_binary,
                        "conversation_id": ObjectId(conversation_id),
                        "isPromptable": is_promptable,
                        "first_n_queries": current_n_queries,
                        "user": user,
                    }
                )
                _dual_write_share(
                    conversation_id,
                    str(explicit_binary.as_uuid()),
                    user,
                    is_promptable=is_promptable,
                    first_n_queries=current_n_queries,
                    api_key=None,
                )
                return make_response(
                    jsonify(
                        {"success": True, "identifier": str(explicit_binary.as_uuid())}
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
            query_uuid = Binary.from_uuid(
                uuid.UUID(identifier), UuidRepresentation.STANDARD
            )
            shared = shared_conversations_collections.find_one({"uuid": query_uuid})
            conversation_queries = []

            if (
                shared
                and "conversation_id" in shared
            ):
                # Handle DBRef (legacy), ObjectId, dict, and string formats for conversation_id
                conversation_id = shared["conversation_id"]
                if isinstance(conversation_id, DBRef):
                    conversation_id = conversation_id.id
                elif isinstance(conversation_id, dict):
                    # Handle dict representation of DBRef (e.g., {"$ref": "...", "$id": "..."})
                    if "$id" in conversation_id:
                        conv_id = conversation_id["$id"]
                        # $id might be a dict like {"$oid": "..."} or a string
                        if isinstance(conv_id, dict) and "$oid" in conv_id:
                            conversation_id = ObjectId(conv_id["$oid"])
                        else:
                            conversation_id = ObjectId(conv_id)
                    elif "_id" in conversation_id:
                        conversation_id = ObjectId(conversation_id["_id"])
                elif isinstance(conversation_id, str):
                    conversation_id = ObjectId(conversation_id)
                conversation = conversations_collection.find_one(
                    {"_id": conversation_id}
                )
                if conversation is None:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": "might have broken url or the conversation does not exist",
                            }
                        ),
                        404,
                    )
                conversation_queries = conversation["queries"][
                    : (shared["first_n_queries"])
                ]

                for query in conversation_queries:
                    if "attachments" in query and query["attachments"]:
                        attachment_details = []
                        for attachment_id in query["attachments"]:
                            try:
                                attachment = attachments_collection.find_one(
                                    {"_id": ObjectId(attachment_id)}
                                )
                                if attachment:
                                    attachment_details.append(
                                        {
                                            "id": str(attachment["_id"]),
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
            else:
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "error": "might have broken url or the conversation does not exist",
                        }
                    ),
                    404,
                )
            date = conversation["_id"].generation_time.isoformat()
            res = {
                "success": True,
                "queries": conversation_queries,
                "title": conversation["name"],
                "timestamp": date,
            }
            if shared["isPromptable"] and "api_key" in shared:
                res["api_key"] = shared["api_key"]
            return make_response(jsonify(res), 200)
        except Exception as err:
            current_app.logger.error(
                f"Error getting shared conversation: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
