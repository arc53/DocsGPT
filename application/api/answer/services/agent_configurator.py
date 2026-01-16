import datetime
import logging
from typing import Any, Dict, Optional

from bson.dbref import DBRef
from bson.objectid import ObjectId

from application.core.model_utils import validate_model_id, get_default_model_id
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.utils import calculate_doc_token_budget

logger = logging.getLogger(__name__)


class AgentConfigurator:
    def __init__(
        self, request_data: Dict[str, Any], decoded_token: Optional[Dict[str, Any]]
    ):
        mongo = MongoDB.get_client()
        self.db = mongo[settings.MONGO_DB_NAME]
        self.agents_collection = self.db["agents"]
        self.data = request_data
        self.decoded_token = decoded_token
        self.initial_user_id = (
            self.decoded_token.get("sub") if self.decoded_token is not None else None
        )
        self.agent_config = {}
        self.retriever_config = {}
        self.agent_key = None
        self.is_shared_usage = False
        self.shared_token = None
        self.source = {}
        self.model_id: Optional[str] = None

    def get_config(self) -> Dict[str, Any]:
        """Orchestrate the configuration process and return a dictionary."""
        self._configure_agent()
        self._validate_and_set_model()
        self._configure_source()
        self._configure_retriever()
        return {
            "agent_config": self.agent_config,
            "retriever_config": self.retriever_config,
            "agent_key": self.agent_key,
            "is_shared_usage": self.is_shared_usage,
            "shared_token": self.shared_token,
            "source": self.source,
            "model_id": self.model_id,
            "initial_user_id": self.initial_user_id,
            "decoded_token": self.decoded_token,
        }

    def _validate_and_set_model(self):
        """Validate and set model_id from request"""
        from application.core.model_settings import ModelRegistry

        requested_model = self.data.get("model_id")

        if requested_model:
            if not validate_model_id(requested_model):
                registry = ModelRegistry.get_instance()
                available_models = [m.id for m in registry.get_enabled_models()]
                raise ValueError(
                    f"Invalid model_id '{requested_model}'. "
                    f"Available models: {', '.join(available_models[:5])}"
                    + (
                        f" and {len(available_models) - 5} more"
                        if len(available_models) > 5
                        else ""
                    )
                )
            self.model_id = requested_model
        else:
            # Check if agent has a default model configured
            agent_default_model = self.agent_config.get("default_model_id", "")
            if agent_default_model and validate_model_id(agent_default_model):
                self.model_id = agent_default_model
            else:
                self.model_id = get_default_model_id()

    def _configure_source(self):
        """Configure the source based on agent data"""
        api_key = self.data.get("api_key") or self.agent_key

        if api_key:
            agent_data = self._get_data_from_api_key(api_key)

            if agent_data.get("sources") and len(agent_data["sources"]) > 0:
                source_ids = [
                    source["id"]
                    for source in agent_data["sources"]
                    if source.get("id")
                ]
                if source_ids:
                    self.source = {"active_docs": source_ids}
                else:
                    self.source = {}
                self.all_sources = agent_data["sources"]
            elif agent_data.get("source"):
                self.source = {"active_docs": agent_data["source"]}
                self.all_sources = [
                    {
                        "id": agent_data["source"],
                        "retriever": agent_data.get("retriever", "classic"),
                    }
                ]
            else:
                self.source = {}
                self.all_sources = []
            return
        if "active_docs" in self.data:
            self.source = {"active_docs": self.data["active_docs"]}
            return
        self.source = {}
        self.all_sources = []

    def _configure_retriever(self):
        doc_token_limit = calculate_doc_token_budget(model_id=self.model_id)

        self.retriever_config = {
            "retriever_name": self.data.get("retriever", "classic"),
            "chunks": int(self.data.get("chunks", 2)),
            "doc_token_limit": doc_token_limit,
        }

        api_key = self.data.get("api_key") or self.agent_key
        if not api_key and "isNoneDoc" in self.data and self.data["isNoneDoc"]:
            self.retriever_config["chunks"] = 0

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
                    "json_schema": data_key.get("json_schema"),
                    "default_model_id": data_key.get("default_model_id", ""),
                }
            )
            self.initial_user_id = data_key.get("user")
            self.decoded_token = {"sub": data_key.get("user")}
            if data_key.get("source"):
                self.source = {"active_docs": data_key["source"]}
            if data_key.get("retriever"):
                self.retriever_config["retriever_name"] = data_key["retriever"]
            if data_key.get("chunks") is not None:
                try:
                    self.retriever_config["chunks"] = int(data_key["chunks"])
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid chunks value: {data_key['chunks']}, using default value 2"
                    )
                    self.retriever_config["chunks"] = 2
        elif self.agent_key:
            data_key = self._get_data_from_api_key(self.agent_key)
            self.agent_config.update(
                {
                    "prompt_id": data_key.get("prompt_id", "default"),
                    "agent_type": data_key.get("agent_type", settings.AGENT_NAME),
                    "user_api_key": self.agent_key,
                    "json_schema": data_key.get("json_schema"),
                    "default_model_id": data_key.get("default__model_id", ""),
                }
            )
            self.decoded_token = (
                self.decoded_token
                if self.is_shared_usage
                else {"sub": data_key.get("user")}
            )
            if data_key.get("source"):
                self.source = {"active_docs": data_key["source"]}
            if data_key.get("retriever"):
                self.retriever_config["retriever_name"] = data_key["retriever"]
            if data_key.get("chunks") is not None:
                try:
                    self.retriever_config["chunks"] = int(data_key["chunks"])
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid chunks value: {data_key['chunks']}, using default value 2"
                    )
                    self.retriever_config["chunks"] = 2
        else:
            self.agent_config.update(
                {
                    "prompt_id": self.data.get("prompt_id", "default"),
                    "agent_type": settings.AGENT_NAME,
                    "user_api_key": None,
                    "json_schema": None,
                    "default_model_id": "",
                }
            )

    def _get_data_from_api_key(self, api_key: str) -> Dict[str, Any]:
        data = self.agents_collection.find_one({"key": api_key})
        if not data:
            raise Exception("Invalid API Key, please generate a new key", 401)
        source = data.get("source")
        if isinstance(source, DBRef):
            source_doc = self.db.dereference(source)
            if source_doc:
                data["source"] = str(source_doc["_id"])
                data["retriever"] = source_doc.get("retriever", data.get("retriever"))
                data["chunks"] = source_doc.get("chunks", data.get("chunks"))
            else:
                data["source"] = None
        elif source == "default":
            data["source"] = "default"
        else:
            data["source"] = None
        # Handle multiple sources

        sources = data.get("sources", [])
        if sources and isinstance(sources, list):
            sources_list = []
            for i, source_ref in enumerate(sources):
                if source_ref == "default":
                    processed_source = {
                        "id": "default",
                        "retriever": "classic",
                        "chunks": data.get("chunks", "2"),
                    }
                    sources_list.append(processed_source)
                elif isinstance(source_ref, DBRef):
                    source_doc = self.db.dereference(source_ref)
                    if source_doc:
                        processed_source = {
                            "id": str(source_doc["_id"]),
                            "retriever": source_doc.get("retriever", "classic"),
                            "chunks": source_doc.get("chunks", data.get("chunks", "2")),
                        }
                        sources_list.append(processed_source)
            data["sources"] = sources_list
        else:
            data["sources"] = []

        # Preserve model configuration from agent
        data["default_model_id"] = data.get("default_model_id", "")

        return data
