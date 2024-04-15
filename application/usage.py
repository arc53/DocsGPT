from pymongo import MongoClient
from bson.son import SON
from datetime import datetime
from application.core.settings import settings
from application.utils import count_tokens

mongo = MongoClient(settings.MONGO_URI)
db = mongo["docsgpt"]
usage_collection = db["token_usage"]


def update_token_usage(api_key, token_usage):
    usage_data = {
        "api_key": api_key,
        "prompt_tokens": token_usage["prompt_tokens"],
        "generated_tokens": token_usage["generated_tokens"],
        "timestamp": datetime.now(),
    }
    usage_collection.insert_one(usage_data)


def gen_token_usage(func):
    def wrapper(self, model, messages, *args, **kwargs):
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"
        self.token_usage["prompt_tokens"] += count_tokens(prompt)
        result = func(self, model, messages, *args, **kwargs)
        self.token_usage["generated_tokens"] += count_tokens(result)
        update_token_usage(self.api_key, self.token_usage)
        return result

    return wrapper


def stream_token_usage(func):
    def wrapper(self, model, messages, *args, **kwargs):
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"
        self.token_usage["prompt_tokens"] += count_tokens(prompt)
        batch = []
        result = func(self, model, messages, *args, **kwargs)
        for r in result:
            batch.append(r)
            yield r
        for line in batch:
            self.token_usage["generated_tokens"] += count_tokens(line)
        update_token_usage(self.api_key, self.token_usage)

    return wrapper
