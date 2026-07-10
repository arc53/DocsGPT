import logging

from application.core.settings import settings
from application.llm.llm_creator import LLMCreator
from application.retriever.base import BaseRetriever
from application.retriever.labels import labels_from_metadata
from application.utils import num_tokens_from_string
from application.vectorstore.vector_creator import VectorCreator


class ClassicRAG(BaseRetriever):
    def __init__(
        self,
        source,
        chat_history=None,
        prompt="",
        chunks=2,
        doc_token_limit=50000,
        model_id="docsgpt-local",
        user_api_key=None,
        agent_id=None,
        llm_name=settings.LLM_PROVIDER,
        api_key=settings.API_KEY,
        decoded_token=None,
        model_user_id=None,
        defer_rephrase=False,
        request_id=None,
    ):
        self.original_question = source.get("question", "")
        self.chat_history = chat_history if chat_history is not None else []
        self.prompt = prompt
        if isinstance(chunks, str):
            try:
                self.chunks = int(chunks)
            except ValueError:
                logging.warning(
                    f"Invalid chunks value '{chunks}', using default value 2"
                )
                self.chunks = 2
        else:
            self.chunks = chunks
        user_id = decoded_token.get("sub") if decoded_token else "default"
        logging.info(
            f"ClassicRAG initialized with chunks={self.chunks}, user_id={user_id}, "
            f"sources={'active_docs' in source and source['active_docs'] is not None}"
        )
        self.model_id = model_id
        self.model_user_id = model_user_id
        self.doc_token_limit = doc_token_limit
        self.user_api_key = user_api_key
        self.agent_id = agent_id
        self.llm_name = llm_name
        self.api_key = api_key
        # Forward model_id + model_user_id so LLMCreator resolves BYOM
        # base_url / api_key / upstream id for the rephrase client.
        self.llm = LLMCreator.create_llm(
            self.llm_name,
            api_key=self.api_key,
            user_api_key=self.user_api_key,
            decoded_token=decoded_token,
            model_id=self.model_id,
            agent_id=self.agent_id,
            model_user_id=self.model_user_id,
        )
        # Query-rephrase LLM is a side channel — tag it so its rows
        # land as ``source='rag_condense'`` in cost-attribution, and stamp
        # the originating request so the rows correlate to it.
        self.llm._token_usage_source = "rag_condense"
        self.llm._request_id = request_id

        if "active_docs" in source and source["active_docs"] is not None:
            if isinstance(source["active_docs"], list):
                self.vectorstores = source["active_docs"]
            else:
                self.vectorstores = [source["active_docs"]]
        else:
            self.vectorstores = []
        # Per-source retrieval overrides ({doc_id: RetrievalConfig}); set by the
        # Dispatcher. Empty → global behaviour, byte-identical to today.
        self.per_source_retrieval = {}
        # Rephrased query is computed lazily when deferred so a source with
        # rephrase_query=False can skip the LLM side-call entirely. The default
        # path (defer_rephrase=False) rephrases eagerly, exactly as before.
        self._rephrased_question = None
        if defer_rephrase:
            self.question = self.original_question
        else:
            self.question = self._rephrase_query()
            self._rephrased_question = self.question
        self.decoded_token = decoded_token
        self._validate_vectorstore_config()

    def _get_rephrased_question(self) -> str:
        """Return the rephrased query, computing it once and caching it."""
        if self._rephrased_question is None:
            self._rephrased_question = self._rephrase_query()
        return self._rephrased_question

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
        prompt = (
            "Given the following conversation history:\n"
            f"{self.chat_history}\n\n"
            "Rephrase the following user question to be a standalone search query "
            "that captures all relevant context from the conversation:\n"
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": self.original_question},
        ]

        try:
            # Send upstream id (resolved by LLMCreator), not registry UUID.
            rephrased_query = self.llm.gen(
                model=getattr(self.llm, "model_id", None) or self.model_id,
                messages=messages,
            )
            print(f"Rephrased query: {rephrased_query}")
            return rephrased_query if rephrased_query else self.original_question
        except Exception as e:
            logging.error(f"Error rephrasing query: {e}", exc_info=True)
            return self.original_question

    def _fetch_candidates(self, docsearch, question, src_k, score_threshold):
        """Fetch candidate hits for one vector store (vector search).

        Subclasses override this to change candidate sourcing (e.g. RRF fusion)
        while inheriting the surrounding per-source resolution and budgeting.
        """
        # ``score_threshold`` is honoured by pgvector/mongodb and safely ignored
        # by stores whose ``search`` swallows kwargs. The candidate count is
        # clamped to a ceiling to bound memory/latency.
        k = min(max(src_k * 2, 20), 500)
        search_kwargs = {"k": k}
        if score_threshold is not None:
            search_kwargs["score_threshold"] = score_threshold
        return docsearch.search(question, **search_kwargs)

    def _get_data(self):
        if self.chunks == 0 or not self.vectorstores:
            logging.info(
                f"ClassicRAG._get_data: Skipping retrieval - chunks={self.chunks}, "
                f"vectorstores_count={len(self.vectorstores) if self.vectorstores else 0}"
            )
            return []

        all_docs = []
        chunks_per_source = max(1, self.chunks // len(self.vectorstores))
        token_budget = max(int(self.doc_token_limit * 0.9), 100)
        cumulative_tokens = 0

        for vectorstore_id in self.vectorstores:
            if vectorstore_id:
                try:
                    # Per-source overrides (set by the Dispatcher). Absent →
                    # global behaviour, byte-identical to before.
                    src_cfg = self.per_source_retrieval.get(vectorstore_id)
                    if src_cfg is not None:
                        src_k = max(1, int(src_cfg.chunks))
                        # Prescreen fetches a larger candidate set up front; the
                        # Dispatcher's prescreen stage trims back to max_keep
                        # afterwards. Raise the fetch size to candidate_k here.
                        ps_cfg = (
                            src_cfg.prescreen_config()
                            if hasattr(src_cfg, "prescreen_config")
                            else None
                        )
                        if ps_cfg is not None:
                            src_k = max(src_k, int(ps_cfg.candidate_k))
                        score_threshold = src_cfg.score_threshold
                        question = (
                            self._get_rephrased_question()
                            if src_cfg.rephrase_query
                            else self.original_question
                        )
                    else:
                        src_k = chunks_per_source
                        score_threshold = None
                        # No per-source override → the effective rephrase_query
                        # defaults to True, so use the (lazily-cached) rephrased
                        # question. In the non-deferred path the cache is already
                        # populated, so this matches today's behaviour exactly.
                        question = self._get_rephrased_question()

                    docsearch = VectorCreator.create_vectorstore(
                        settings.VECTOR_STORE, vectorstore_id, settings.EMBEDDINGS_KEY
                    )
                    docs_temp = self._fetch_candidates(
                        docsearch, question, src_k, score_threshold
                    )

                    for doc in docs_temp:
                        if cumulative_tokens >= token_budget:
                            break

                        if hasattr(doc, "page_content") and hasattr(doc, "metadata"):
                            page_content = doc.page_content
                            metadata = doc.metadata
                        else:
                            page_content = doc.get("text", doc.get("page_content", ""))
                            metadata = doc.get("metadata", {})

                        labels = labels_from_metadata(
                            metadata, page_content, vectorstore_id
                        )

                        doc_text_with_header = f"{labels['filename']}\n{page_content}"
                        doc_tokens = num_tokens_from_string(doc_text_with_header)

                        if cumulative_tokens + doc_tokens < token_budget:
                            all_docs.append({"text": page_content, **labels})
                            cumulative_tokens += doc_tokens

                    if cumulative_tokens >= token_budget:
                        break

                except Exception as e:
                    logging.error(
                        f"Error searching vectorstore {vectorstore_id}: {e}",
                        exc_info=True,
                    )
                    continue

        logging.info(
            f"ClassicRAG._get_data: Retrieval complete - retrieved {len(all_docs)} documents "
            f"(requested chunks={self.chunks}, chunks_per_source={chunks_per_source}, "
            f"cumulative_tokens={cumulative_tokens}/{token_budget})"
        )
        return all_docs

    def search(self, query: str = ""):
        """Search for documents using optional query override"""
        if query:
            self.original_question = query
            # Invalidate the cached rephrase so a per-source path that opts in
            # rephrases against the new query, not a stale one.
            self._rephrased_question = None
            self.question = self._rephrase_query()
            self._rephrased_question = self.question
        return self._get_data()
