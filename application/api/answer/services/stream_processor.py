import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Set

from bson.dbref import DBRef

from bson.objectid import ObjectId

from application.api.answer.services.agent_configurator import AgentConfigurator
from application.api.answer.services.compression import CompressionOrchestrator
from application.api.answer.services.compression.token_counter import TokenCounter
from application.api.answer.services.conversation_service import ConversationService
from application.api.answer.services.prompt_renderer import PromptRenderer
from application.core.model_utils import (
    get_api_key_for_provider,
    get_provider_from_model_id,
)
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.retriever.retriever_creator import RetrieverCreator
from application.utils import (
    limit_chat_history,
)

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
        self.conversation_id = self.data.get("conversation_id")
        self.attachments = []
        self.history = []
        self.retrieved_docs = []
        self.all_sources = []
        self.conversation_service = ConversationService()
        self.compression_orchestrator = CompressionOrchestrator(
            self.conversation_service
        )
        self.prompt_renderer = PromptRenderer()
        self._prompt_content: Optional[str] = None
        self._required_tool_actions: Optional[Dict[str, Set[Optional[str]]]] = None
        self.compressed_summary: Optional[str] = None
        self.compressed_summary_tokens: int = 0

        # These will be set by the configurator
        self.decoded_token: Optional[Dict[str, Any]] = decoded_token
        self.initial_user_id: Optional[str] = (
            self.decoded_token.get("sub") if self.decoded_token is not None else None
        )
        self.agent_config: Dict[str, Any] = {}
        self.retriever_config: Dict[str, Any] = {}
        self.is_shared_usage: bool = False
        self.shared_token: Optional[str] = None
        self.model_id: Optional[str] = None
        self.source: Dict[str, Any] = {}

    def initialize(self):
        """Initialize all required components for processing"""
        configurator = AgentConfigurator(self.data, self.decoded_token)
        config = configurator.get_config()

        self.agent_config = config["agent_config"]
        self.retriever_config = config["retriever_config"]
        self.is_shared_usage = config["is_shared_usage"]
        self.shared_token = config["shared_token"]
        self.model_id = config["model_id"]
        self.source = config["source"]
        self.initial_user_id = config["initial_user_id"]
        self.decoded_token = config["decoded_token"]

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

            # Check if compression is enabled and needed
            if settings.ENABLE_CONVERSATION_COMPRESSION:
                self._handle_compression(conversation)
            else:
                # Original behavior - load all history
                self.history = [
                    {"prompt": query["prompt"], "response": query["response"]}
                    for query in conversation.get("queries", [])
                ]
        else:
            self.history = limit_chat_history(
                json.loads(self.data.get("history", "[]")), model_id=self.model_id
            )

    def _handle_compression(self, conversation: Dict[str, Any]):
        """
        Handle conversation compression logic using orchestrator.

        Args:
            conversation: Full conversation document
        """
        try:
            # Use orchestrator to handle all compression logic
            result = self.compression_orchestrator.compress_if_needed(
                conversation_id=self.conversation_id,
                user_id=self.initial_user_id,
                model_id=self.model_id,
                decoded_token=self.decoded_token,
            )

            if not result.success:
                logger.error(
                    f"Compression failed: {result.error}, using full history"
                )
                self.history = [
                    {"prompt": query["prompt"], "response": query["response"]}
                    for query in conversation.get("queries", [])
                ]
                return

            # Set compressed summary if compression was performed
            if result.compression_performed and result.compressed_summary:
                self.compressed_summary = result.compressed_summary
                self.compressed_summary_tokens = TokenCounter.count_message_tokens(
                    [{"content": result.compressed_summary}]
                )
                logger.info(
                    f"Using compressed summary ({self.compressed_summary_tokens} tokens) "
                    f"+ {len(result.recent_queries)} recent messages"
                )

            # Build history from recent queries
            self.history = result.as_history()

        except Exception as e:
            logger.error(
                f"Error handling compression, falling back to standard history: {str(e)}",
                exc_info=True,
            )
            # Fallback to original behavior
            self.history = [
                {"prompt": query["prompt"], "response": query["response"]}
                for query in conversation.get("queries", [])
            ]

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



    def create_retriever(self):
        return RetrieverCreator.create_retriever(
            self.retriever_config["retriever_name"],
            source=self.source,
            chat_history=self.history,
            prompt=get_prompt(self.agent_config["prompt_id"], self.prompts_collection),
            chunks=self.retriever_config["chunks"],
            doc_token_limit=self.retriever_config.get("doc_token_limit", 50000),
            model_id=self.model_id,
            user_api_key=self.agent_config["user_api_key"],
            decoded_token=self.decoded_token,
        )

    def pre_fetch_docs(self, question: str) -> tuple[Optional[str], Optional[list]]:
        """Pre-fetch documents for template rendering before agent creation"""
        if self.data.get("isNoneDoc", False):
            logger.info("Pre-fetch skipped: isNoneDoc=True")
            return None, None
        try:
            retriever = self.create_retriever()
            logger.info(
                f"Pre-fetching docs with chunks={retriever.chunks}, doc_token_limit={retriever.doc_token_limit}"
            )
            docs = retriever.search(question)
            logger.info(f"Pre-fetch retrieved {len(docs) if docs else 0} documents")

            if not docs:
                logger.info("Pre-fetch: No documents returned from search")
                return None, None
            self.retrieved_docs = docs

            docs_with_filenames = []
            for doc in docs:
                filename = doc.get("filename") or doc.get("title") or doc.get("source")
                if filename:
                    chunk_header = str(filename)
                    docs_with_filenames.append(f"{chunk_header}\n{doc['text']}")
                else:
                    docs_with_filenames.append(doc["text"])
            docs_together = "\n\n".join(docs_with_filenames)

            logger.info(f"Pre-fetch docs_together size: {len(docs_together)} chars")

            return docs_together, docs
        except Exception as e:
            logger.error(f"Failed to pre-fetch docs: {str(e)}", exc_info=True)
            return None, None

    def pre_fetch_tools(self) -> Optional[Dict[str, Any]]:
        """Pre-fetch tool data for template rendering before agent creation

        Can be controlled via:
        1. Global setting: ENABLE_TOOL_PREFETCH in .env
        2. Per-request: disable_tool_prefetch in request data
        """
        if not settings.ENABLE_TOOL_PREFETCH:
            logger.info(
                "Tool pre-fetching disabled globally via ENABLE_TOOL_PREFETCH setting"
            )
            return None

        if self.data.get("disable_tool_prefetch", False):
            logger.info("Tool pre-fetching disabled for this request")
            return None

        required_tool_actions = self._get_required_tool_actions()
        filtering_enabled = required_tool_actions is not None

        try:
            user_tools_collection = self.db["user_tools"]
            user_id = self.initial_user_id or "local"

            user_tools = list(
                user_tools_collection.find({"user": user_id, "status": True})
            )

            if not user_tools:
                return None

            tools_data = {}

            for tool_doc in user_tools:
                tool_name = tool_doc.get("name")
                tool_id = str(tool_doc.get("_id"))

                if filtering_enabled:
                    required_actions_by_name = required_tool_actions.get(
                        tool_name, set()
                    )
                    required_actions_by_id = required_tool_actions.get(tool_id, set())

                    required_actions = required_actions_by_name | required_actions_by_id

                    if not required_actions:
                        continue
                else:
                    required_actions = None

                tool_data = self._fetch_tool_data(tool_doc, required_actions)
                if tool_data:
                    tools_data[tool_name] = tool_data
                    tools_data[tool_id] = tool_data

            return tools_data if tools_data else None
        except Exception as e:
            logger.warning(f"Failed to pre-fetch tools: {type(e).__name__}")
            return None

    def _fetch_tool_data(
        self,
        tool_doc: Dict[str, Any],
        required_actions: Optional[Set[Optional[str]]],
    ) -> Optional[Dict[str, Any]]:
        """Fetch and execute tool actions with saved parameters"""
        try:
            from application.agents.tools.tool_manager import ToolManager

            tool_name = tool_doc.get("name")
            tool_config = tool_doc.get("config", {}).copy()
            tool_config["tool_id"] = str(tool_doc["_id"])

            tool_manager = ToolManager(config={tool_name: tool_config})
            user_id = self.initial_user_id or "local"
            tool = tool_manager.load_tool(tool_name, tool_config, user_id=user_id)

            if not tool:
                logger.debug(f"Tool '{tool_name}' failed to load")
                return None

            tool_actions = tool.get_actions_metadata()
            if not tool_actions:
                logger.debug(f"Tool '{tool_name}' has no actions")
                return None

            saved_actions = tool_doc.get("actions", [])

            include_all_actions = required_actions is None or (
                required_actions and None in required_actions
            )
            allowed_actions: Set[str] = (
                {action for action in required_actions if isinstance(action, str)}
                if required_actions
                else set()
            )

            action_results = {}
            for action_meta in tool_actions:
                action_name = action_meta.get("name")
                if action_name is None:
                    continue
                if (
                    not include_all_actions
                    and allowed_actions
                    and action_name not in allowed_actions
                ):
                    continue

                try:
                    saved_action = None
                    for sa in saved_actions:
                        if sa.get("name") == action_name:
                            saved_action = sa
                            break

                    action_params = action_meta.get("parameters", {})
                    properties = action_params.get("properties", {})

                    kwargs = {}
                    for param_name, param_spec in properties.items():
                        if saved_action:
                            saved_props = saved_action.get("parameters", {}).get(
                                "properties", {}
                            )
                            if param_name in saved_props:
                                param_value = saved_props[param_name].get("value")
                                if param_value is not None:
                                    kwargs[param_name] = param_value
                                    continue

                        if param_name in tool_config:
                            kwargs[param_name] = tool_config[param_name]
                        elif "default" in param_spec:
                            kwargs[param_name] = param_spec["default"]

                    result = tool.execute_action(action_name, **kwargs)
                    action_results[action_name] = result
                except Exception as e:
                    logger.debug(
                        f"Action '{action_name}' execution failed: {type(e).__name__}"
                    )
                    continue

            return action_results if action_results else None

        except Exception as e:
            logger.debug(f"Tool pre-fetch failed for '{tool_name}': {type(e).__name__}")
            return None

    def _get_prompt_content(self) -> Optional[str]:
        """Retrieve and cache the raw prompt content for the current agent configuration."""
        if self._prompt_content is not None:
            return self._prompt_content
        prompt_id = (
            self.agent_config.get("prompt_id")
            if isinstance(self.agent_config, dict)
            else None
        )
        if not prompt_id:
            return None
        try:
            self._prompt_content = get_prompt(prompt_id, self.prompts_collection)
        except ValueError as e:
            logger.debug(f"Invalid prompt ID '{prompt_id}': {str(e)}")
            self._prompt_content = None
        except Exception as e:
            logger.debug(f"Failed to fetch prompt '{prompt_id}': {type(e).__name__}")
            self._prompt_content = None
        return self._prompt_content

    def _get_required_tool_actions(self) -> Optional[Dict[str, Set[Optional[str]]]]:
        """Determine which tool actions are referenced in the prompt template"""
        if self._required_tool_actions is not None:
            return self._required_tool_actions

        prompt_content = self._get_prompt_content()
        if prompt_content is None:
            return None

        if "{{" not in prompt_content or "}}" not in prompt_content:
            self._required_tool_actions = {}
            return self._required_tool_actions

        try:
            from application.templates.template_engine import TemplateEngine

            template_engine = TemplateEngine()
            usages = template_engine.extract_tool_usages(prompt_content)
            self._required_tool_actions = usages
            return self._required_tool_actions
        except Exception as e:
            logger.debug(f"Failed to extract tool usages: {type(e).__name__}")
            self._required_tool_actions = {}
            return self._required_tool_actions

    def _fetch_memory_tool_data(
        self, tool_doc: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Fetch memory tool data for pre-injection into prompt"""
        try:
            tool_config = tool_doc.get("config", {}).copy()
            tool_config["tool_id"] = str(tool_doc["_id"])

            from application.agents.tools.memory import MemoryTool

            memory_tool = MemoryTool(tool_config, self.initial_user_id)

            root_view = memory_tool.execute_action("view", path="/")

            if "Error:" in root_view or not root_view.strip():
                return None

            return {"root": root_view, "available": True}
        except Exception as e:
            logger.warning(f"Failed to fetch memory tool data: {str(e)}")
            return None

    def create_agent(
        self,
        docs_together: Optional[str] = None,
        docs: Optional[list] = None,
        tools_data: Optional[Dict[str, Any]] = None,
    ):
        """Create and return the configured agent with rendered prompt"""
        raw_prompt = self._get_prompt_content()
        if raw_prompt is None:
            raw_prompt = get_prompt(
                self.agent_config["prompt_id"], self.prompts_collection
            )
            self._prompt_content = raw_prompt

        rendered_prompt = self.prompt_renderer.render_prompt(
            prompt_content=raw_prompt,
            user_id=self.initial_user_id,
            request_id=self.data.get("request_id"),
            passthrough_data=self.data.get("passthrough"),
            docs=docs,
            docs_together=docs_together,
            tools_data=tools_data,
        )

        provider = (
            get_provider_from_model_id(self.model_id)
            if self.model_id
            else settings.LLM_PROVIDER
        )
        system_api_key = get_api_key_for_provider(provider or settings.LLM_PROVIDER)

        agent = AgentCreator.create_agent(
            self.agent_config["agent_type"],
            endpoint="stream",
            llm_name=provider or settings.LLM_PROVIDER,
            model_id=self.model_id,
            api_key=system_api_key,
            user_api_key=self.agent_config["user_api_key"],
            prompt=rendered_prompt,
            chat_history=self.history,
            retrieved_docs=self.retrieved_docs,
            decoded_token=self.decoded_token,
            attachments=self.attachments,
            json_schema=self.agent_config.get("json_schema"),
            compressed_summary=self.compressed_summary,
        )

        agent.conversation_id = self.conversation_id
        agent.initial_user_id = self.initial_user_id

        return agent
