import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from bson.dbref import DBRef

from bson.objectid import ObjectId

from application.agents.agent_creator import AgentCreator
from application.api.answer.services.conversation_service import ConversationService
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.retriever.retriever_creator import RetrieverCreator
from application.utils import get_gpt_model, limit_chat_history

logger = logging.getLogger(__name__)


def get_prompt(prompt_id: str, prompts_collection=None) -> str:
    """
    Get a prompt by preset name or MongoDB ID
    """
    current_dir = Path(__file__).resolve().parents[3]
    prompts_dir = current_dir / "prompts"

    preset_mapping = {
        "default": "chat_combine_default.txt",
        "creative": "chat_combine_creative.txt",
        "strict": "chat_combine_strict.txt",
        "reduce": "chat_reduce_prompt.txt",
    }

    if prompt_id in preset_mapping:
        file_path = os.path.join(prompts_dir, preset_mapping[prompt_id])
        try:
            with open(file_path, "r") as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"Prompt file not found: {file_path}")
    try:
        if prompts_collection is None:
            mongo = MongoDB.get_client()
            db = mongo[settings.MONGO_DB_NAME]
            prompts_collection = db["prompts"]
        prompt_doc = prompts_collection.find_one({"_id": ObjectId(prompt_id)})
        if not prompt_doc:
            raise ValueError(f"Prompt with ID {prompt_id} not found")
        return prompt_doc["content"]
    except Exception as e:
        raise ValueError(f"Invalid prompt ID: {prompt_id}") from e


class StreamProcessor:
    def __init__(
        self, request_data: Dict[str, Any], decoded_token: Optional[Dict[str, Any]]
    ):
        mongo = MongoDB.get_client()
        self.db = mongo[settings.MONGO_DB_NAME]
        self.agents_collection = self.db["agents"]
        self.attachments_collection = self.db["attachments"]
        self.prompts_collection = self.db["prompts"]

        self.data = request_data
        self.decoded_token = decoded_token
        self.initial_user_id = (
            self.decoded_token.get("sub") if self.decoded_token is not None else None
        )
        self.conversation_id = self.data.get("conversation_id")
        self.source = (
            {"active_docs": self.data["active_docs"]}
            if "active_docs" in self.data
            else {}
        )
        self.attachments = []
        self.history = []
        self.agent_config = {}
        self.retriever_config = {}
        self.is_shared_usage = False
        self.shared_token = None
        self.gpt_model = get_gpt_model()
        self.conversation_service = ConversationService()

    def initialize(self):
        """Initialize all required components for processing"""
        self._configure_agent()
        self._configure_retriever()
        self._load_conversation_history()
        self._process_attachments()

    def _load_conversation_history(self):
        """Load conversation history either from DB or request"""
        if self.conversation_id and self.initial_user_id:
            conversation = self.conversation_service.get_conversation(
                self.conversation_id, self.initial_user_id
            )
            if not conversation:
                raise ValueError("Conversation not found or unauthorized")
            self.history = [
                {"prompt": query["prompt"], "response": query["response"]}
                for query in conversation.get("queries", [])
            ]
        else:
            self.history = limit_chat_history(
                json.loads(self.data.get("history", "[]")), gpt_model=self.gpt_model
            )

    def _process_attachments(self):
        """Process any attachments in the request"""
        attachment_ids = self.data.get("attachments", [])
        self.attachments = self._get_attachments_content(
            attachment_ids, self.initial_user_id
        )

    def _get_attachments_content(self, attachment_ids, user_id):
        """
        Retrieve content from attachment documents based on their IDs.
        """
        if not attachment_ids:
            return []
        attachments = []
        for attachment_id in attachment_ids:
            try:
                attachment_doc = self.attachments_collection.find_one(
                    {"_id": ObjectId(attachment_id), "user": user_id}
                )

                if attachment_doc:
                    attachments.append(attachment_doc)
            except Exception as e:
                logger.error(
                    f"Error retrieving attachment {attachment_id}: {e}", exc_info=True
                )
        return attachments

    def _get_agent_key(self, agent_id: Optional[str], user_id: Optional[str]) -> tuple:
        """Get API key for agent with access control"""
        if not agent_id:
            return None, False, None
        try:
            agent = self.agents_collection.find_one({"_id": ObjectId(agent_id)})
            if agent is None:
                raise Exception("Agent not found")
            is_owner = agent.get("user") == user_id
            is_shared_with_user = agent.get(
                "shared_publicly", False
            ) or user_id in agent.get("shared_with", [])

            if not (is_owner or is_shared_with_user):
                raise Exception("Unauthorized access to the agent")
            if is_owner:
                self.agents_collection.update_one(
                    {"_id": ObjectId(agent_id)},
                    {
                        "$set": {
                            "lastUsedAt": datetime.datetime.now(datetime.timezone.utc)
                        }
                    },
                )
            return str(agent["key"]), not is_owner, agent.get("shared_token")
        except Exception as e:
            logger.error(f"Error in get_agent_key: {str(e)}", exc_info=True)
            raise

    def _get_data_from_api_key(self, api_key: str) -> Dict[str, Any]:
        data = self.agents_collection.find_one({"key": api_key})
        if not data:
            raise Exception("Invalid API Key, please generate a new key", 401)
        source = data.get("source")
        if isinstance(source, DBRef):
            source_doc = self.db.dereference(source)
            data["source"] = str(source_doc["_id"])
            data["retriever"] = source_doc.get("retriever", data.get("retriever"))
        else:
            data["source"] = {}
        return data

    def _configure_agent(self):
        """Configure the agent based on request data"""
        agent_id = self.data.get("agent_id")
        self.agent_key, self.is_shared_usage, self.shared_token = self._get_agent_key(
            agent_id, self.initial_user_id
        )

        api_key = self.data.get("api_key")
        if api_key:
            data_key = self._get_data_from_api_key(api_key)
            self.agent_config.update(
                {
                    "prompt_id": data_key.get("prompt_id", "default"),
                    "agent_type": data_key.get("agent_type", settings.AGENT_NAME),
                    "user_api_key": api_key,
                }
            )
            self.initial_user_id = data_key.get("user")
            self.decoded_token = {"sub": data_key.get("user")}
        elif self.agent_key:
            data_key = self._get_data_from_api_key(self.agent_key)
            self.agent_config.update(
                {
                    "prompt_id": data_key.get("prompt_id", "default"),
                    "agent_type": data_key.get("agent_type", settings.AGENT_NAME),
                    "user_api_key": self.agent_key,
                }
            )
            self.decoded_token = (
                self.decoded_token
                if self.is_shared_usage
                else {"sub": data_key.get("user")}
            )
        else:
            self.agent_config.update(
                {
                    "prompt_id": self.data.get("prompt_id", "default"),
                    "agent_type": settings.AGENT_NAME,
                    "user_api_key": None,
                }
            )

    def _configure_retriever(self):
        """Configure the retriever based on request data"""
        self.retriever_config = {
            "retriever_name": self.data.get("retriever", "classic"),
            "chunks": int(self.data.get("chunks", 2)),
            "token_limit": self.data.get("token_limit", settings.DEFAULT_MAX_HISTORY),
        }

        if "isNoneDoc" in self.data and self.data["isNoneDoc"]:
            self.retriever_config["chunks"] = 0

    def create_agent(self):
        """Create and return the configured agent"""
        return AgentCreator.create_agent(
            self.agent_config["agent_type"],
            endpoint="stream",
            llm_name=settings.LLM_PROVIDER,
            gpt_model=self.gpt_model,
            api_key=settings.API_KEY,
            user_api_key=self.agent_config["user_api_key"],
            prompt=get_prompt(self.agent_config["prompt_id"], self.prompts_collection),
            chat_history=self.history,
            decoded_token=self.decoded_token,
            attachments=self.attachments,
        )

    def create_retriever(self):
        """Create and return the configured retriever"""
        return RetrieverCreator.create_retriever(
            self.retriever_config["retriever_name"],
            source=self.source,
            chat_history=self.history,
            prompt=get_prompt(self.agent_config["prompt_id"], self.prompts_collection),
            chunks=self.retriever_config["chunks"],
            token_limit=self.retriever_config["token_limit"],
            gpt_model=self.gpt_model,
            user_api_key=self.agent_config["user_api_key"],
            decoded_token=self.decoded_token,
        )
