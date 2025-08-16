import logging
from application.core.settings import settings
from application.llm.llm_creator import LLMCreator
from application.retriever.base import BaseRetriever

from application.vectorstore.vector_creator import VectorCreator


class ClassicRAG(BaseRetriever):
    def __init__(
        self,
        source,
        chat_history=None,
        prompt="",
        chunks=2,
        token_limit=150,
        gpt_model="docsgpt",
        user_api_key=None,
        llm_name=settings.LLM_PROVIDER,
        api_key=settings.API_KEY,
        decoded_token=None,
    ):
        self.original_question = source.get("question", "")
        self.chat_history = chat_history if chat_history is not None else []
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
        self.llm_name = llm_name
        self.api_key = api_key
        self.llm = LLMCreator.create_llm(
            self.llm_name,
            api_key=self.api_key,
            user_api_key=self.user_api_key,
            decoded_token=decoded_token,
        )
        if "active_docs" in source:
            if isinstance(source["active_docs"], list):
                self.vectorstores = source["active_docs"]
            elif isinstance(source["active_docs"], str) and "," in source["active_docs"]:
                # ✅ split multiple IDs from comma string
                self.vectorstores = [doc_id.strip() for doc_id in source["active_docs"].split(",") if doc_id.strip()]
            else:
                self.vectorstores = [source["active_docs"]]
        else:
            self.vectorstores = []

        self.vectorstore = None
        self.question = self._rephrase_query()
        self.decoded_token = decoded_token

    def _rephrase_query(self):
        if (
            not self.original_question
            or not self.chat_history
            or self.chat_history == []
            or self.chunks == 0
            or self.vectorstore is None
        ):
            return self.original_question

        prompt = f"""Given the following conversation history:
        {self.chat_history}

        Rephrase the following user question to be a standalone search query 
        that captures all relevant context from the conversation:
        """

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": self.original_question},
        ]

        try:
            rephrased_query = self.llm.gen(model=self.gpt_model, messages=messages)
            print(f"Rephrased query: {rephrased_query}")
            return rephrased_query if rephrased_query else self.original_question
        except Exception as e:
            logging.error(f"Error rephrasing query: {e}", exc_info=True)
            return self.original_question

    def _get_data(self):
        if self.chunks == 0 or not self.vectorstores:
            return []

        all_docs = []
        chunks_per_source = max(1, self.chunks // len(self.vectorstores))

        for vectorstore in self.vectorstores:
            if vectorstore:
                try:
                    docsearch = VectorCreator.create_vectorstore(
                        settings.VECTOR_STORE, vectorstore, settings.EMBEDDINGS_KEY
                    )
                    docs_temp = docsearch.search(self.question, k=chunks_per_source)
                    for i in docs_temp:
                        all_docs.append({
                            "title": i.metadata.get("title", i.metadata.get("post_title", i.page_content)).split("/")[-1],
                            "text": i.page_content,
                            "source": i.metadata.get("source") or vectorstore,
                        })
                except Exception as e:
                    logging.error(f"Error searching vectorstore {vectorstore}: {e}")
                    continue

        return all_docs

    def gen():
        pass

    def search(self, query: str = ""):
        if query:
            self.original_question = query
            self.question = self._rephrase_query()
        return self._get_data()

    def get_params(self):
        return {
            "question": self.original_question,
            "rephrased_question": self.question,
            "sources": self.vectorstores,
            "chunks": self.chunks,
            "token_limit": self.token_limit,
            "gpt_model": self.gpt_model,
            "user_api_key": self.user_api_key,
        }
