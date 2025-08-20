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
        """Initialize ClassicRAG retriever with vectorstore sources and LLM configuration"""
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
            elif (
                isinstance(source["active_docs"], str) and "," in source["active_docs"]
            ):
                self.vectorstores = [
                    doc_id.strip()
                    for doc_id in source["active_docs"].split(",")
                    if doc_id.strip()
                ]
            else:
                self.vectorstores = [source["active_docs"]]
        else:
            self.vectorstores = []

        self.question = self._rephrase_query()
        self.decoded_token = decoded_token
        self._validate_vectorstore_config()

    def _validate_vectorstore_config(self):
        """Validate vectorstore IDs and remove any empty/invalid entries"""
        if not self.vectorstores:
            logging.warning("No vectorstores configured for retrieval")
            return

        invalid_ids = [
            vs_id for vs_id in self.vectorstores if not vs_id or not vs_id.strip()
        ]
        if invalid_ids:
            logging.warning(f"Found invalid vectorstore IDs: {invalid_ids}")
            self.vectorstores = [
                vs_id for vs_id in self.vectorstores if vs_id and vs_id.strip()
            ]

    def _rephrase_query(self):
        """Rephrase user query with chat history context for better retrieval"""
        if (
            not self.original_question
            or not self.chat_history
            or self.chat_history == []
            or self.chunks == 0
            or not self.vectorstores
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
        """Retrieve relevant documents from configured vectorstores"""
        if self.chunks == 0 or not self.vectorstores:
            return []

        all_docs = []
        chunks_per_source = max(1, self.chunks // len(self.vectorstores))

        for vectorstore_id in self.vectorstores:
            if vectorstore_id:
                try:
                    docsearch = VectorCreator.create_vectorstore(
                        settings.VECTOR_STORE, vectorstore_id, settings.EMBEDDINGS_KEY
                    )
                    docs_temp = docsearch.search(self.question, k=chunks_per_source)

                    for doc in docs_temp:
                        if hasattr(doc, "page_content") and hasattr(doc, "metadata"):
                            page_content = doc.page_content
                            metadata = doc.metadata
                        else:
                            page_content = doc.get("text", doc.get("page_content", ""))
                            metadata = doc.get("metadata", {})

                        title = metadata.get(
                            "title", metadata.get("post_title", page_content)
                        )
                        if isinstance(title, str):
                            title = title.split("/")[-1]
                        else:
                            title = str(title).split("/")[-1]

                        all_docs.append(
                            {
                                "title": title,
                                "text": page_content,
                                "source": metadata.get("source") or vectorstore_id,
                            }
                        )
                except Exception as e:
                    logging.error(
                        f"Error searching vectorstore {vectorstore_id}: {e}",
                        exc_info=True,
                    )
                    continue

        return all_docs

    def search(self, query: str = ""):
        """Search for documents using optional query override"""
        if query:
            self.original_question = query
            self.question = self._rephrase_query()
        return self._get_data()

    def get_params(self):
        """Return current retriever configuration parameters"""
        return {
            "question": self.original_question,
            "rephrased_question": self.question,
            "sources": self.vectorstores,
            "chunks": self.chunks,
            "token_limit": self.token_limit,
            "gpt_model": self.gpt_model,
            "user_api_key": self.user_api_key,
        }
