import logging
from application.core.settings import settings
from application.llm.llm_creator import LLMCreator
from application.retriever.base import BaseRetriever
from application.vectorstore.vector_creator import VectorCreator

logger = logging.getLogger(__name__)

class ClassicRAG(BaseRetriever):
    # Settings for Auto-Chunking
    AUTO_CHUNK_MIN: int = 0
    AUTO_CHUNK_MAX: int = 10
    SIMILARITY_SCORE_THRESHOLD: float = 0.5
    
    def __init__(
        self,
        source,
        chat_history=None,
        prompt="",
        chunks=2,
        token_limit=150,
        gpt_model="docsgpt",
        user_api_key=None,
        llm_name=settings.LLM_NAME,
        api_key=settings.API_KEY,
        decoded_token=None,
    ):
        self.original_question = ""
        self.chat_history = chat_history if chat_history is not None else []
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
        self.llm_name = llm_name
        self.api_key = api_key
        self.llm = LLMCreator.create_llm(
            self.llm_name,
            api_key=self.api_key,
            user_api_key=self.user_api_key,
            decoded_token=decoded_token,
        )
        self.question = self._rephrase_query()
        self.vectorstore = source["active_docs"] if "active_docs" in source else None
        self.decoded_token = decoded_token
        self.actual_chunks_retrieved = 0

    def _rephrase_query(self):
        if (
            not self.original_question
            or not self.chat_history
            or self.chat_history == []
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
        if self.chunks == 'Auto':
            return self._get_data_auto()
        else:
            return self._get_data_classic()

    def _get_data_auto(self):
        if not self.vectorstore:
            self.actual_chunks_retrieved = 0
            return []

        docsearch = VectorCreator.create_vectorstore(
            settings.VECTOR_STORE, self.vectorstore, settings.EMBEDDINGS_KEY
        )
        
        try:
            docs_with_scores = docsearch.search_with_scores(self.question, k=self.AUTO_CHUNK_MAX)
        except Exception as e:
            logger.error(f"Error during search_with_scores: {e}", exc_info=True)
            self.actual_chunks_retrieved = 0
            return []
        
        if not docs_with_scores:
            self.actual_chunks_retrieved = 0
            return []

        candidate_docs = []
        for doc, score in docs_with_scores:
            if score >= self.SIMILARITY_SCORE_THRESHOLD:
                candidate_docs.append(doc)
                
        if len(candidate_docs) < self.AUTO_CHUNK_MIN and self.AUTO_CHUNK_MIN > 0:
            final_docs_to_format = [doc for doc, score in docs_with_scores[:self.AUTO_CHUNK_MIN]]
        else:
            final_docs_to_format = candidate_docs
            
        self.actual_chunks_retrieved = len(final_docs_to_format)
        
        if not final_docs_to_format:
            return []

        formatted_docs = [
            {
                "title": i.metadata.get(
                    "title", i.metadata.get("post_title", i.page_content)
                ).split("/")[-1],
                "text": i.page_content,
                "source": (
                    i.metadata.get("source")
                    if i.metadata.get("source")
                    else "local"
                ),
            }
            for i in final_docs_to_format
        ]
        logger.info(f"AutoRAG: Retrieved {self.actual_chunks_retrieved} chunks for query '{self.original_question}'.")
        return formatted_docs

    def _get_data_classic(self):
        if self.chunks == 0:
            return []
        else:
            docsearch = VectorCreator.create_vectorstore(
                settings.VECTOR_STORE, self.vectorstore, settings.EMBEDDINGS_KEY
            )
            docs_temp = docsearch.search(self.question, k=self.chunks)
            docs = [
                {
                    "title": i.metadata.get(
                        "title", i.metadata.get("post_title", i.page_content)
                    ).split("/")[-1],
                    "text": i.page_content,
                    "source": (
                        i.metadata.get("source")
                        if i.metadata.get("source")
                        else "local"
                    ),
                }
                for i in docs_temp
            ]
            return docs

    def gen():
        pass

    def search(self, query: str = ""):
        if query:
            self.original_question = query
            self.question = self._rephrase_query()
        return self._get_data()

    def get_params(self):
        params = {
            "question": self.original_question,
            "rephrased_question": self.question,
            "source": self.vectorstore,
            "token_limit": self.token_limit,
            "gpt_model": self.gpt_model,
            "user_api_key": self.user_api_key,
        }
        if self.chunks == 'Auto':
            params.update({
                "chunks_mode": "Auto",
                "chunks_retrieved_auto": self.actual_chunks_retrieved,
                "auto_chunk_min_setting": self.AUTO_CHUNK_MIN,
                "auto_chunk_max_setting": self.AUTO_CHUNK_MAX,
                "similarity_threshold_setting": self.SIMILARITY_SCORE_THRESHOLD,
            })
        else:
            params["chunks_mode"] = "Classic"
            params["chunks"] = self.chunks

        return params