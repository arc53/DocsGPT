import json

from langchain_community.tools import BraveSearch

from application.core.settings import settings
from application.llm.llm_creator import LLMCreator
from application.retriever.base import BaseRetriever


class BraveRetSearch(BaseRetriever):

    def __init__(
        self,
        source,
        chat_history,
        prompt,
        chunks=2,
        token_limit=150,
        gpt_model="docsgpt",
        user_api_key=None,
        decoded_token=None,
    ):
        self.question = ""
        self.source = source
        self.chat_history = chat_history
        self.prompt = prompt
        self.chunks = chunks
        self.gpt_model = gpt_model
        self.token_limit = (
            token_limit
            if token_limit
            < settings.LLM_TOKEN_LIMITS.get(
                self.gpt_model, settings.DEFAULT_MAX_HISTORY
            )
            else settings.LLM_TOKEN_LIMITS.get(
                self.gpt_model, settings.DEFAULT_MAX_HISTORY
            )
        )
        self.user_api_key = user_api_key
        self.decoded_token = decoded_token

    def _get_data(self):
        if self.chunks == 0:
            docs = []
        else:
            search = BraveSearch.from_api_key(
                api_key=settings.BRAVE_SEARCH_API_KEY,
                search_kwargs={"count": int(self.chunks)},
            )
            results = search.run(self.question)
            results = json.loads(results)

            docs = []
            for i in results:
                try:
                    title = i["title"]
                    link = i["link"]
                    snippet = i["snippet"]
                    docs.append({"text": snippet, "title": title, "link": link})
                except IndexError:
                    pass
        if settings.LLM_PROVIDER == "llama.cpp":
            docs = [docs[0]]

        return docs

    def gen(self):
        docs = self._get_data()

        # join all page_content together with a newline
        docs_together = "\n".join([doc["text"] for doc in docs])
        p_chat_combine = self.prompt.replace("{summaries}", docs_together)
        messages_combine = [{"role": "system", "content": p_chat_combine}]
        for doc in docs:
            yield {"source": doc}

        if len(self.chat_history) > 0:
            for i in self.chat_history:
                if "prompt" in i and "response" in i:
                    messages_combine.append({"role": "user", "content": i["prompt"]})
                    messages_combine.append(
                        {"role": "assistant", "content": i["response"]}
                    )
        messages_combine.append({"role": "user", "content": self.question})

        llm = LLMCreator.create_llm(
            settings.LLM_PROVIDER,
            api_key=settings.API_KEY,
            user_api_key=self.user_api_key,
            decoded_token=self.decoded_token,
        )

        completion = llm.gen_stream(model=self.gpt_model, messages=messages_combine)
        for line in completion:
            yield {"answer": str(line)}

    def search(self, query: str = ""):
        if query:
            self.question = query
        return self._get_data()

    def get_params(self):
        return {
            "question": self.question,
            "source": self.source,
            "chat_history": self.chat_history,
            "prompt": self.prompt,
            "chunks": self.chunks,
            "token_limit": self.token_limit,
            "gpt_model": self.gpt_model,
            "user_api_key": self.user_api_key,
        }
