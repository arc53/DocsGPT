from application.retriever.base import BaseRetriever
from application.core.settings import settings
from application.vectorstore.vector_creator import VectorCreator
from application.llm.llm_creator import LLMCreator

from application.utils import num_tokens_from_string


class ClassicRAG(BaseRetriever):

    def __init__(
        self,
        question,
        source,
        chat_history,
        prompt,
        chunks=2,
        token_limit=150,
        gpt_model="docsgpt",
        user_api_key=None,
    ):
        self.question = question
        self.vectorstore = source['active_docs'] if 'active_docs' in source else None
        self.chat_history = chat_history
        self.prompt = prompt
        self.chunks = chunks
        self.gpt_model = gpt_model
        self.token_limit = (
            token_limit
            if token_limit
            < settings.MODEL_TOKEN_LIMITS.get(
                self.gpt_model, settings.DEFAULT_MAX_HISTORY
            )
            else settings.MODEL_TOKEN_LIMITS.get(
                self.gpt_model, settings.DEFAULT_MAX_HISTORY
            )
        )
        self.user_api_key = user_api_key

    def _get_data(self):
        if self.chunks == 0:
            docs = []
        else:
            docsearch = VectorCreator.create_vectorstore(
                settings.VECTOR_STORE, self.vectorstore, settings.EMBEDDINGS_KEY
            )
            docs_temp = docsearch.search(self.question, k=self.chunks)
            docs = [
                {
                    "title": (
                        i.metadata["title"].split("/")[-1]
                        if i.metadata
                        else i.page_content
                    ),
                    "text": i.page_content,
                    "source": (
                        i.metadata.get("source")
                        if i.metadata.get("source")
                        else "local"
                    ),
                }
                for i in docs_temp
            ]
        if settings.LLM_NAME == "llama.cpp":
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

        if len(self.chat_history) > 1:
            tokens_current_history = 0
            # count tokens in history
            self.chat_history.reverse()
            for i in self.chat_history:
                if "prompt" in i and "response" in i:
                    tokens_batch = num_tokens_from_string(i["prompt"]) + num_tokens_from_string(
                        i["response"]
                    )
                    if tokens_current_history + tokens_batch < self.token_limit:
                        tokens_current_history += tokens_batch
                        messages_combine.append(
                            {"role": "user", "content": i["prompt"]}
                        )
                        messages_combine.append(
                            {"role": "system", "content": i["response"]}
                        )
        messages_combine.append({"role": "user", "content": self.question})

        llm = LLMCreator.create_llm(
            settings.LLM_NAME, api_key=settings.API_KEY, user_api_key=self.user_api_key
        )

        completion = llm.gen_stream(model=self.gpt_model, messages=messages_combine)
        for line in completion:
            yield {"answer": str(line)}

    def search(self):
        return self._get_data()
