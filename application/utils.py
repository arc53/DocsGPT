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

def limit_chat_history(history,max_token_limit = 500):
   
    cumulative_token_count = 0
    trimmed_history = []
    
    for i in reversed(history):
        
        if("prompt" in i and "response" in i):
            cumulative_token_count += num_tokens_from_string(i["prompt"] + i["response"])
            if(cumulative_token_count > max_token_limit):
                    break
            trimmed_history.insert(0,i)
            
    return trimmed_history