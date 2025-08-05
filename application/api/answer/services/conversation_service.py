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
        gpt_model: str,
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
                    "role": "assistant",
                    "content": "Summarise following conversation in no more than 3 "
                    "words, respond ONLY with the summary, use the same "
                    "language as the user query",
                },
                {
                    "role": "user",
                    "content": "Summarise following conversation in no more than 3 words, "
                    "respond ONLY with the summary, use the same language as the "
                    "user query \n\nUser: " + question + "\n\n" + "AI: " + response,
                },
            ]

            completion = llm.gen(
                model=gpt_model, messages=messages_summary, max_tokens=30
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
