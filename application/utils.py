import tiktoken
import hashlib
from flask import jsonify, make_response


_encoding = None


def get_encoding():
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def num_tokens_from_string(string: str) -> int:
    encoding = get_encoding()
    num_tokens = len(encoding.encode(string))
    return num_tokens


def count_tokens_docs(docs):
    docs_content = ""
    for doc in docs:
        docs_content += doc.page_content

    tokens = num_tokens_from_string(docs_content)
    return tokens


def check_required_fields(data, required_fields):
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return make_response(
            jsonify(
                {
                    "success": False,
                    "message": f"Missing fields: {', '.join(missing_fields)}",
                }
            ),
            400,
        )
    return None


def get_hash(data):
    return hashlib.md5(data.encode()).hexdigest()

def limit_chat_history(history, max_token_limit=None, gpt_model="docsgpt"):
    """
    Limits chat history based on token count.
    Returns a list of messages that fit within the token limit.
    """
    from application.core.settings import settings

    max_token_limit = (
            max_token_limit
            if max_token_limit and 
            max_token_limit < settings.MODEL_TOKEN_LIMITS.get(
                gpt_model, settings.DEFAULT_MAX_HISTORY
            )
            else settings.MODEL_TOKEN_LIMITS.get(
                gpt_model, settings.DEFAULT_MAX_HISTORY
            )
        )
    

    if not history:
        return []
        
    tokens_current_history = 0
    trimmed_history = []
    
    for message in reversed(history):
        if "prompt" in message and "response" in message:
            tokens_batch = num_tokens_from_string(message["prompt"]) + num_tokens_from_string(
                message["response"]
            )
            if tokens_current_history + tokens_batch < max_token_limit:
                tokens_current_history += tokens_batch
                trimmed_history.insert(0, message)
            else:
                break

    return trimmed_history
