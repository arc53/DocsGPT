import sys
from pymongo import MongoClient
from datetime import datetime
from application.core.settings import settings
from application.utils import count_tokens

mongo = MongoClient(settings.MONGO_URI)
db = mongo["docsgpt"]
usage_collection = db["token_usage"]


def update_token_usage(api_key, token_usage):
    if "pytest" in sys.modules:
        return
    usage_data = {
        "api_key": api_key,
        "prompt_tokens": token_usage["prompt_tokens"],
        "generated_tokens": token_usage["generated_tokens"],
        "timestamp": datetime.now(),
    }
    usage_collection.insert_one(usage_data)


def gen_token_usage(func):
    def wrapper(self, model, messages, stream, **kwargs):
        for message in messages:
            self.token_usage["prompt_tokens"] += count_tokens(message["content"])
        result = func(self, model, messages, stream, **kwargs)
        self.token_usage["generated_tokens"] += count_tokens(result)
        update_token_usage(self.api_key, self.token_usage)
        return result

    return wrapper


def stream_token_usage(func):
    def wrapper(self, model, messages, stream, **kwargs):
        for message in messages:
            self.token_usage["prompt_tokens"] += count_tokens(message["content"])
        batch = []
        result = func(self, model, messages, stream, **kwargs)
        for r in result:
            batch.append(r)
            yield r
        for line in batch:
            self.token_usage["generated_tokens"] += count_tokens(line)
        update_token_usage(self.api_key, self.token_usage)

    return wrapper
