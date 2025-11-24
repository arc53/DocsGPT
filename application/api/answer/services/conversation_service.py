import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from application.core.mongo_db import MongoDB

from application.core.settings import settings
from bson import ObjectId


logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(self):
        mongo = MongoDB.get_client()
        db = mongo[settings.MONGO_DB_NAME]
        self.conversations_collection = db["conversations"]
        self.agents_collection = db["agents"]

    def get_conversation(
        self, conversation_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a conversation with proper access control"""
        if not conversation_id or not user_id:
            return None
        try:
            conversation = self.conversations_collection.find_one(
                {
                    "_id": ObjectId(conversation_id),
                    "$or": [{"user": user_id}, {"shared_with": user_id}],
                }
            )

            if not conversation:
                logger.warning(
                    f"Conversation not found or unauthorized - ID: {conversation_id}, User: {user_id}"
                )
                return None
            conversation["_id"] = str(conversation["_id"])
            return conversation
        except Exception as e:
            logger.error(f"Error fetching conversation: {str(e)}", exc_info=True)
            return None

    def save_conversation(
        self,
        conversation_id: Optional[str],
        question: str,
        response: str,
        thought: str,
        sources: List[Dict[str, Any]],
        tool_calls: List[Dict[str, Any]],
        llm: Any,
        model_id: str,
        decoded_token: Dict[str, Any],
        index: Optional[int] = None,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        is_shared_usage: bool = False,
        shared_token: Optional[str] = None,
        attachment_ids: Optional[List[str]] = None,
    ) -> str:
        """Save or update a conversation in the database"""
        user_id = decoded_token.get("sub")
        if not user_id:
            raise ValueError("User ID not found in token")
        current_time = datetime.now(timezone.utc)

        # clean up in sources array such that we save max 1k characters for text part
        for source in sources:
            if "text" in source and isinstance(source["text"], str):
                source["text"] = source["text"][:1000]

        if conversation_id is not None and index is not None:
            # Update existing conversation with new query

            result = self.conversations_collection.update_one(
                {
                    "_id": ObjectId(conversation_id),
                    "user": user_id,
                    f"queries.{index}": {"$exists": True},
                },
                {
                    "$set": {
                        f"queries.{index}.prompt": question,
                        f"queries.{index}.response": response,
                        f"queries.{index}.thought": thought,
                        f"queries.{index}.sources": sources,
                        f"queries.{index}.tool_calls": tool_calls,
                        f"queries.{index}.timestamp": current_time,
                        f"queries.{index}.attachments": attachment_ids,
                        f"queries.{index}.model_id": model_id,
                    }
                },
            )

            if result.matched_count == 0:
                raise ValueError("Conversation not found or unauthorized")
            self.conversations_collection.update_one(
                {
                    "_id": ObjectId(conversation_id),
                    "user": user_id,
                    f"queries.{index}": {"$exists": True},
                },
                {"$push": {"queries": {"$each": [], "$slice": index + 1}}},
            )
            return conversation_id
        elif conversation_id:
            # Append new message to existing conversation

            result = self.conversations_collection.update_one(
                {"_id": ObjectId(conversation_id), "user": user_id},
                {
                    "$push": {
                        "queries": {
                            "prompt": question,
                            "response": response,
                            "thought": thought,
                            "sources": sources,
                            "tool_calls": tool_calls,
                            "timestamp": current_time,
                            "attachments": attachment_ids,
                            "model_id": model_id,
                        }
                    }
                },
            )

            if result.matched_count == 0:
                raise ValueError("Conversation not found or unauthorized")
            return conversation_id
        else:
            # Create new conversation

            messages_summary = [
                {
                    "role": "system",
                    "content": "You are a helpful assistant that creates concise conversation titles. "
                    "Summarize conversations in 3 words or less using the same language as the user.",
                },
                {
                    "role": "user",
                    "content": "Summarise following conversation in no more than 3 words, "
                    "respond ONLY with the summary, use the same language as the "
                    "user query \n\nUser: " + question + "\n\n" + "AI: " + response,
                },
            ]

            completion = llm.gen(
                model=model_id, messages=messages_summary, max_tokens=30
            )

            conversation_data = {
                "user": user_id,
                "date": current_time,
                "name": completion,
                "queries": [
                    {
                        "prompt": question,
                        "response": response,
                        "thought": thought,
                        "sources": sources,
                        "tool_calls": tool_calls,
                        "timestamp": current_time,
                        "attachments": attachment_ids,
                        "model_id": model_id,
                    }
                ],
            }

            if api_key:
                if agent_id:
                    conversation_data["agent_id"] = agent_id
                    if is_shared_usage:
                        conversation_data["is_shared_usage"] = is_shared_usage
                        conversation_data["shared_token"] = shared_token
                agent = self.agents_collection.find_one({"key": api_key})
                if agent:
                    conversation_data["api_key"] = agent["key"]
            result = self.conversations_collection.insert_one(conversation_data)
            return str(result.inserted_id)

    def update_compression_metadata(
        self, conversation_id: str, compression_metadata: Dict[str, Any]
    ) -> None:
        """
        Update conversation with compression metadata.

        Uses $push with $slice to keep only the most recent compression points,
        preventing unbounded array growth. Since each compression incorporates
        previous compressions, older points become redundant.

        Args:
            conversation_id: Conversation ID
            compression_metadata: Compression point data
        """
        try:
            self.conversations_collection.update_one(
                {"_id": ObjectId(conversation_id)},
                {
                    "$set": {
                        "compression_metadata.is_compressed": True,
                        "compression_metadata.last_compression_at": compression_metadata.get(
                            "timestamp"
                        ),
                    },
                    "$push": {
                        "compression_metadata.compression_points": {
                            "$each": [compression_metadata],
                            "$slice": -settings.COMPRESSION_MAX_HISTORY_POINTS,
                        }
                    },
                },
            )
            logger.info(
                f"Updated compression metadata for conversation {conversation_id}"
            )
        except Exception as e:
            logger.error(
                f"Error updating compression metadata: {str(e)}", exc_info=True
            )
            raise

    def append_compression_message(
        self, conversation_id: str, compression_metadata: Dict[str, Any]
    ) -> None:
        """
        Append a synthetic compression summary entry into the conversation history.
        This makes the summary visible in the DB alongside normal queries.
        """
        try:
            summary = compression_metadata.get("compressed_summary", "")
            if not summary:
                return
            timestamp = compression_metadata.get("timestamp", datetime.now(timezone.utc))

            self.conversations_collection.update_one(
                {"_id": ObjectId(conversation_id)},
                {
                    "$push": {
                        "queries": {
                            "prompt": "[Context Compression Summary]",
                            "response": summary,
                            "thought": "",
                            "sources": [],
                            "tool_calls": [],
                            "timestamp": timestamp,
                            "attachments": [],
                            "model_id": compression_metadata.get("model_used"),
                        }
                    }
                },
            )
            logger.info(f"Appended compression summary to conversation {conversation_id}")
        except Exception as e:
            logger.error(
                f"Error appending compression summary: {str(e)}", exc_info=True
            )

    def get_compression_metadata(
        self, conversation_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get compression metadata for a conversation.

        Args:
            conversation_id: Conversation ID

        Returns:
            Compression metadata dict or None
        """
        try:
            conversation = self.conversations_collection.find_one(
                {"_id": ObjectId(conversation_id)}, {"compression_metadata": 1}
            )
            return conversation.get("compression_metadata") if conversation else None
        except Exception as e:
            logger.error(
                f"Error getting compression metadata: {str(e)}", exc_info=True
            )
            return None
