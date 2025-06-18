import sys
from datetime import datetime

from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.utils import num_tokens_from_object_or_list, num_tokens_from_string

mongo = MongoDB.get_client()
db = mongo[settings.MONGO_DB_NAME]
usage_collection = db["token_usage"]


def update_token_usage(decoded_token, user_api_key, token_usage):
    if "pytest" in sys.modules:
        return
    if decoded_token:
        user_id = decoded_token["sub"]
    else:
        user_id = None
    usage_data = {
        "user_id": user_id,
        "api_key": user_api_key,
        "prompt_tokens": token_usage["prompt_tokens"],
        "generated_tokens": token_usage["generated_tokens"],
        "timestamp": datetime.now(),
    }
    usage_collection.insert_one(usage_data)


def gen_token_usage(func):
    def wrapper(self, model, messages, stream, tools, **kwargs):
        for message in messages:
            if message["content"]:
                self.token_usage["prompt_tokens"] += num_tokens_from_string(
                    message["content"]
                )
        result = func(self, model, messages, stream, tools, **kwargs)
        if isinstance(result, str):
            self.token_usage["generated_tokens"] += num_tokens_from_string(result)
        else:
            self.token_usage["generated_tokens"] += num_tokens_from_object_or_list(
                result
            )
        update_token_usage(self.decoded_token, self.user_api_key, self.token_usage)
        return result

    return wrapper


def stream_token_usage(func):
    def wrapper(self, model, messages, stream, tools, **kwargs):
        for message in messages:
            self.token_usage["prompt_tokens"] += num_tokens_from_string(
                message["content"]
            )
        batch = []
        result = func(self, model, messages, stream, tools, **kwargs)
        for r in result:
            batch.append(r)
            yield r
        for line in batch:
            self.token_usage["generated_tokens"] += num_tokens_from_string(line)
        update_token_usage(self.decoded_token, self.user_api_key, self.token_usage)

    return wrapper
