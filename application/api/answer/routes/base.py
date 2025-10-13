import datetime
import json
import logging
from typing import Any, Dict, Generator, List, Optional

from flask import Response, make_response, jsonify
from flask_restx import Namespace

from application.api.answer.services.conversation_service import ConversationService

from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.llm.llm_creator import LLMCreator
from application.utils import check_required_fields, get_gpt_model

logger = logging.getLogger(__name__)


answer_ns = Namespace("answer", description="Answer related operations", path="/")


class BaseAnswerResource:
    """Shared base class for answer endpoints"""

    def __init__(self):
        mongo = MongoDB.get_client()
        db = mongo[settings.MONGO_DB_NAME]
        self.db = db
        self.user_logs_collection = db["user_logs"]
        self.gpt_model = get_gpt_model()
        self.conversation_service = ConversationService()

    def validate_request(
        self, data: Dict[str, Any], require_conversation_id: bool = False
    ) -> Optional[Response]:
        """Common request validation"""
        required_fields = ["question"]
        if require_conversation_id:
            required_fields.append("conversation_id")
        if missing_fields := check_required_fields(data, required_fields):
            return missing_fields
        return None

    def check_usage(
            self, agent_config: Dict
    ) -> Optional[Response]:
        """Check if there is a usage limit and if it is exceeded

        Args:
            agent_config: The config dict of agent instance

        Returns:
            None or Response if either of limits exceeded.
        
        """
        api_key = agent_config.get("user_api_key")
        if not api_key:
            return None
        
        agents_collection = self.db["agents"]
        agent = agents_collection.find_one({"key": api_key})

        if not agent:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Invalid API key."
                    }
                ),
                401
            )

        limited_token_mode = agent.get("limited_token_mode", False)
        limited_request_mode = agent.get("limited_request_mode", False)
        token_limit = int(agent.get("token_limit", settings.DEFAULT_AGENT_LIMITS["token_limit"]))
        request_limit = int(agent.get("request_limit", settings.DEFAULT_AGENT_LIMITS["request_limit"]))

        token_usage_collection = self.db["token_usage"]

        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(hours=24)

        match_query = {
            "timestamp": {"$gte": start_date, "$lte": end_date},
            "api_key": api_key
        }
        
        if limited_token_mode:
            token_pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": None,
                        "total_tokens": {"$sum": {"$add": ["$prompt_tokens", "$generated_tokens"]}}
                    }
                }
            ]
            token_result = list(token_usage_collection.aggregate(token_pipeline))
            daily_token_usage = token_result[0]["total_tokens"] if token_result else 0
        else:
            daily_token_usage = 0

        if limited_request_mode:
            daily_request_usage = token_usage_collection.count_documents(match_query)
        else:
            daily_request_usage = 0

        if not limited_token_mode and not limited_request_mode:
            return None
        elif limited_token_mode and token_limit > daily_token_usage:
            return None
        elif limited_request_mode and request_limit > daily_request_usage:
            return None

        return make_response(
            jsonify(
                {
                    "success": False,
                    "message": "Exceeding usage limit, please try again later."
                }
            ),
            429, # too many requests
        )

    def complete_stream(
        self,
        question: str,
        agent: Any,
        retriever: Any,
        conversation_id: Optional[str],
        user_api_key: Optional[str],
        decoded_token: Dict[str, Any],
        isNoneDoc: bool = False,
        index: Optional[int] = None,
        should_save_conversation: bool = True,
        attachment_ids: Optional[List[str]] = None,
        agent_id: Optional[str] = None,
        is_shared_usage: bool = False,
        shared_token: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Generator function that streams the complete conversation response.

        Args:
            question: The user's question
            agent: The agent instance
            retriever: The retriever instance
            conversation_id: Existing conversation ID
            user_api_key: User's API key if any
            decoded_token: Decoded JWT token
            isNoneDoc: Flag for document-less responses
            index: Index of message to update
            should_save_conversation: Whether to persist the conversation
            attachment_ids: List of attachment IDs
            agent_id: ID of agent used
            is_shared_usage: Flag for shared agent usage
            shared_token: Token for shared agent

        Yields:
            Server-sent event strings
        """
        try:
            response_full, thought, source_log_docs, tool_calls = "", "", [], []
            is_structured = False
            schema_info = None
            structured_chunks = []

            for line in agent.gen(query=question, retriever=retriever):
                if "answer" in line:
                    response_full += str(line["answer"])
                    if line.get("structured"):
                        is_structured = True
                        schema_info = line.get("schema")
                        structured_chunks.append(line["answer"])
                    else:
                        data = json.dumps({"type": "answer", "answer": line["answer"]})
                        yield f"data: {data}\n\n"
                elif "sources" in line:
                    truncated_sources = []
                    source_log_docs = line["sources"]
                    for source in line["sources"]:
                        truncated_source = source.copy()
                        if "text" in truncated_source:
                            truncated_source["text"] = (
                                truncated_source["text"][:100].strip() + "..."
                            )
                        truncated_sources.append(truncated_source)
                    if truncated_sources:
                        data = json.dumps(
                            {"type": "source", "source": truncated_sources}
                        )
                        yield f"data: {data}\n\n"
                elif "tool_calls" in line:
                    tool_calls = line["tool_calls"]
                    data = json.dumps({"type": "tool_calls", "tool_calls": tool_calls})
                    yield f"data: {data}\n\n"
                elif "thought" in line:
                    thought += line["thought"]
                    data = json.dumps({"type": "thought", "thought": line["thought"]})
                    yield f"data: {data}\n\n"
                elif "type" in line:
                    data = json.dumps(line)
                    yield f"data: {data}\n\n"

            if is_structured and structured_chunks:
                structured_data = {
                    "type": "structured_answer",
                    "answer": response_full,
                    "structured": True,
                    "schema": schema_info,
                }
                data = json.dumps(structured_data)
                yield f"data: {data}\n\n"

            if isNoneDoc:
                for doc in source_log_docs:
                    doc["source"] = "None"
            llm = LLMCreator.create_llm(
                settings.LLM_PROVIDER,
                api_key=settings.API_KEY,
                user_api_key=user_api_key,
                decoded_token=decoded_token,
            )

            if should_save_conversation:
                conversation_id = self.conversation_service.save_conversation(
                    conversation_id,
                    question,
                    response_full,
                    thought,
                    source_log_docs,
                    tool_calls,
                    llm,
                    self.gpt_model,
                    decoded_token,
                    index=index,
                    api_key=user_api_key,
                    agent_id=agent_id,
                    is_shared_usage=is_shared_usage,
                    shared_token=shared_token,
                    attachment_ids=attachment_ids,
                )
            else:
                conversation_id = None
            id_data = {"type": "id", "id": str(conversation_id)}
            data = json.dumps(id_data)
            yield f"data: {data}\n\n"

            retriever_params = retriever.get_params()
            log_data = {
                "action": "stream_answer",
                "level": "info",
                "user": decoded_token.get("sub"),
                "api_key": user_api_key,
                "question": question,
                "response": response_full,
                "sources": source_log_docs,
                "retriever_params": retriever_params,
                "attachments": attachment_ids,
                "timestamp": datetime.datetime.now(datetime.timezone.utc),
            }
            if is_structured:
                log_data["structured_output"] = True
                if schema_info:
                    log_data["schema"] = schema_info
  
            # clean up text fields to be no longer than 10000 characters
            for key, value in log_data.items():
                if isinstance(value, str) and len(value) > 10000:
                    log_data[key] = value[:10000]
            
            self.user_logs_collection.insert_one(log_data)

            # End of stream

            data = json.dumps({"type": "end"})
            yield f"data: {data}\n\n"
        except GeneratorExit:
            # Client aborted the connection
            logger.info(
                f"Stream aborted by client for question: {question[:50]}... "
            )
            # Save partial response to database before exiting
            if should_save_conversation and response_full:
                try:
                    if isNoneDoc:
                        for doc in source_log_docs:
                            doc["source"] = "None"
                    llm = LLMCreator.create_llm(
                        settings.LLM_PROVIDER,
                        api_key=settings.API_KEY,
                        user_api_key=user_api_key,
                        decoded_token=decoded_token,
                    )
                    self.conversation_service.save_conversation(
                        conversation_id,
                        question,
                        response_full,
                        thought,
                        source_log_docs,
                        tool_calls,
                        llm,
                        self.gpt_model,
                        decoded_token,
                        index=index,
                        api_key=user_api_key,
                        agent_id=agent_id,
                        is_shared_usage=is_shared_usage,
                        shared_token=shared_token,
                        attachment_ids=attachment_ids,
                    )
                except Exception as e:
                    logger.error(f"Error saving partial response: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Error in stream: {str(e)}", exc_info=True)
            data = json.dumps(
                {
                    "type": "error",
                    "error": "Please try again later. We apologize for any inconvenience.",
                }
            )
            yield f"data: {data}\n\n"
            return

    def process_response_stream(self, stream):
        """Process the stream response for non-streaming endpoint"""
        conversation_id = ""
        response_full = ""
        source_log_docs = []
        tool_calls = []
        thought = ""
        stream_ended = False
        is_structured = False
        schema_info = None

        for line in stream:
            try:
                event_data = line.replace("data: ", "").strip()
                event = json.loads(event_data)

                if event["type"] == "id":
                    conversation_id = event["id"]
                elif event["type"] == "answer":
                    response_full += event["answer"]
                elif event["type"] == "structured_answer":
                    response_full = event["answer"]
                    is_structured = True
                    schema_info = event.get("schema")
                elif event["type"] == "source":
                    source_log_docs = event["source"]
                elif event["type"] == "tool_calls":
                    tool_calls = event["tool_calls"]
                elif event["type"] == "thought":
                    thought = event["thought"]
                elif event["type"] == "error":
                    logger.error(f"Error from stream: {event['error']}")
                    return None, None, None, None, event["error"]
                elif event["type"] == "end":
                    stream_ended = True
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Error parsing stream event: {e}, line: {line}")
                continue
        if not stream_ended:
            logger.error("Stream ended unexpectedly without an 'end' event.")
            return None, None, None, None, "Stream ended unexpectedly"

        result = (
            conversation_id,
            response_full,
            source_log_docs,
            tool_calls,
            thought,
            None,
        )

        if is_structured:
            result = result + ({"structured": True, "schema": schema_info},)

        return result

    def error_stream_generate(self, err_response):
        data = json.dumps({"type": "error", "error": err_response})
        yield f"data: {data}\n\n"
