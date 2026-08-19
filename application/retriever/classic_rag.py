import logging
from typing import Any, Dict, List, Optional, Tuple

from application.core.settings import settings
from application.llm.llm_creator import LLMCreator
from application.retriever.base import BaseRetriever
from application.retriever.fanout import (  # noqa: F401  (re-exported)
    DEFAULT_MAX_PARALLEL_SOURCES,
    EMBEDDING_ATTRS as _EMBEDDING_ATTRS,
    embed_questions,
    max_parallel_sources,
    run_source_jobs,
    store_embeddings,
)
from application.retriever.labels import labels_from_metadata
from application.utils import num_tokens_from_string
from application.vectorstore.vector_creator import VectorCreator

logger = logging.getLogger(__name__)


def _max_parallel_sources(n_sources: int) -> int:
    """Worker count for the per-source fan-out, bounded by the source count."""
    return max_parallel_sources(n_sources, settings)


class ClassicRAG(BaseRetriever):
    # The group's real top-k, set by the Dispatcher when it inflates ``chunks``
    # for a prescreen fetch. None → ``chunks`` is already the top-k.
    base_chunks = None

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
        include_scores=False,
    ):
        self.include_scores = include_scores
        self.original_question = source.get("question", "")
        self.chat_history = chat_history if chat_history is not None else []
        self.prompt = prompt
        if isinstance(chunks, str):
            try:
                self.chunks = int(chunks)
            except ValueError:
                logger.warning(
                    f"Invalid chunks value '{chunks}', using default value 2"
                )
                self.chunks = 2
        else:
            self.chunks = chunks
        user_id = decoded_token.get("sub") if decoded_token else "default"
        logger.info(
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
            logger.warning("No vectorstores configured for retrieval")
            return
        invalid_ids = [
            vs_id for vs_id in self.vectorstores if not vs_id or not vs_id.strip()
        ]
        if invalid_ids:
            logger.warning(f"Found invalid vectorstore IDs: {invalid_ids}")
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
            logger.debug(f"Rephrased query: {rephrased_query}")
            return rephrased_query if rephrased_query else self.original_question
        except Exception as e:
            logger.error(f"Error rephrasing query: {e}", exc_info=True)
            return self.original_question

    def _fetch_candidates(
        self,
        docsearch,
        question: str,
        src_k: int,
        score_threshold: Optional[float],
        query_vector: Optional[List[float]] = None,
    ):
        """Fetch candidate hits for one vector store (vector search).

        Returns plain hits, or ``(hit, score)`` pairs when ``include_scores`` is
        set. Subclasses override this to change candidate sourcing (e.g. RRF
        fusion) while inheriting the surrounding per-source resolution and
        budgeting.

        Args:
            query_vector: Query embedding computed once for the whole
                retrieval. Forwarded so the store skips embedding the query
                again; stores that don't support it ignore the kwarg.
        """
        # ``score_threshold`` is honoured by pgvector/mongodb and safely ignored
        # by stores whose ``search`` swallows kwargs. The candidate count is
        # clamped to a ceiling to bound memory/latency.
        k = min(max(src_k * 2, 20), 500)
        search_kwargs = {"k": k}
        if score_threshold is not None:
            search_kwargs["score_threshold"] = score_threshold
        if query_vector is not None:
            search_kwargs["query_vector"] = query_vector
        if self.include_scores:
            return docsearch.search_with_scores(question, **search_kwargs)
        return docsearch.search(question, **search_kwargs)

    def _score_kind(self, docsearch):
        """Label for the scores ``_fetch_candidates`` attaches (None if unscored)."""
        return getattr(docsearch, "score_kind", None)

    def _resolve_source(
        self, vectorstore_id: str, chunks_per_source: int
    ) -> Dict[str, Any]:
        """Resolve one source's fetch parameters (top-k, threshold, query).

        Per-source overrides come from the Dispatcher; absent, the source gets
        the global behaviour — byte-identical to the pre-override path.
        """
        src_cfg = self.per_source_retrieval.get(vectorstore_id)
        if src_cfg is None:
            # No per-source override → the effective rephrase_query defaults to
            # True, so use the (lazily-cached) rephrased question. In the
            # non-deferred path the cache is already populated.
            return {
                "id": vectorstore_id,
                "src_k": chunks_per_source,
                "score_threshold": None,
                "question": self._get_rephrased_question(),
            }
        src_k = max(1, int(src_cfg.chunks))
        # Prescreen fetches a larger candidate set up front; the Dispatcher's
        # prescreen stage trims back to max_keep afterwards. Raise the fetch
        # size to candidate_k here.
        ps_cfg = (
            src_cfg.prescreen_config() if hasattr(src_cfg, "prescreen_config") else None
        )
        if ps_cfg is not None:
            src_k = max(src_k, int(ps_cfg.candidate_k))
        return {
            "id": vectorstore_id,
            "src_k": src_k,
            "score_threshold": src_cfg.score_threshold,
            "question": (
                self._get_rephrased_question()
                if src_cfg.rephrase_query
                else self.original_question
            ),
        }

    def _plan_sources(self, chunks_per_source: int) -> List[Dict[str, Any]]:
        """Resolve every source's fetch parameters, in source order.

        Runs on the calling thread: the lazy rephrase behind it is an LLM
        side-call that must happen once, not once per worker.
        """
        plans = []
        for vectorstore_id in self.vectorstores:
            if not vectorstore_id:
                continue
            try:
                plans.append(self._resolve_source(vectorstore_id, chunks_per_source))
            except Exception as e:
                logger.error(
                    f"Error searching vectorstore {vectorstore_id}: {e}", exc_info=True
                )
        return plans

    @staticmethod
    def _store_embeddings(docsearch):
        """Return the embeddings object a vector store searches with, if any."""
        return store_embeddings(docsearch)

    def _embed_questions(
        self, docsearch, questions: List[str]
    ) -> Dict[str, List[float]]:
        """Embed each distinct query once for the whole retrieval."""
        return embed_questions(docsearch, questions)

    def _search_source(
        self,
        plan: Dict[str, Any],
        docsearch=None,
        query_vector: Optional[List[float]] = None,
    ) -> Optional[Tuple[Any, Optional[str]]]:
        """Search one source, returning ``(candidates, score_kind)``.

        Builds the vector store when not supplied, so each worker thread owns
        its own store instance (and therefore its own DB connection). Errors are
        logged and reported as ``None`` so one bad source cannot take the rest
        of the retrieval down with it.
        """
        try:
            if docsearch is None:
                docsearch = VectorCreator.create_vectorstore(
                    settings.VECTOR_STORE, plan["id"], settings.EMBEDDINGS_KEY
                )
            docs_temp = self._fetch_candidates(
                docsearch,
                plan["question"],
                plan["src_k"],
                plan["score_threshold"],
                query_vector=query_vector,
            )
            score_kind = self._score_kind(docsearch) if self.include_scores else None
            return docs_temp, score_kind
        except Exception as e:
            logger.error(
                f"Error searching vectorstore {plan['id']}: {e}", exc_info=True
            )
            return None

    def _fetch_all(
        self, plans: List[Dict[str, Any]]
    ) -> List[Optional[Tuple[Any, Optional[str]]]]:
        """Fetch every source's candidates, one embedding and one fan-out.

        The first store is built on the calling thread because its embeddings
        object supplies the shared query vector — and priming the embeddings
        singleton there keeps the workers off a concurrent model load. The
        searches then run on a bounded pool, and results come back in the
        original source order so the merge stays deterministic.
        """
        first_store = None
        try:
            first_store = VectorCreator.create_vectorstore(
                settings.VECTOR_STORE, plans[0]["id"], settings.EMBEDDINGS_KEY
            )
        except Exception as e:
            logger.error(
                f"Error searching vectorstore {plans[0]['id']}: {e}", exc_info=True
            )

        if first_store is None:
            # The first source is already a logged failure; the rest still run,
            # each embedding its own query (there is no store to borrow one from).
            return [None] + self._run_jobs([(plan, None, None) for plan in plans[1:]])

        questions = list(dict.fromkeys(plan["question"] for plan in plans))
        vectors = self._embed_questions(first_store, questions)
        return self._run_jobs(
            [
                (plan, first_store if idx == 0 else None, vectors.get(plan["question"]))
                for idx, plan in enumerate(plans)
            ]
        )

    def _run_jobs(self, jobs: List[Tuple]) -> List[Optional[Tuple[Any, Optional[str]]]]:
        """Run the per-source search jobs, concurrently when there are several."""
        if not jobs:
            return []
        return run_source_jobs(
            lambda job: self._search_source(*job),
            jobs,
            workers=_max_parallel_sources(len(jobs)),
        )

    def _get_data(self):
        if self.chunks == 0 or not self.vectorstores:
            logger.info(
                f"ClassicRAG._get_data: Skipping retrieval - chunks={self.chunks}, "
                f"vectorstores_count={len(self.vectorstores) if self.vectorstores else 0}"
            )
            return []

        all_docs = []
        # The Dispatcher inflates ``chunks`` to a prescreen source's candidate_k
        # so the fetch is large enough for the screening stage. That inflated
        # number must not become the top-k of the *other* sources in the group,
        # so the fallback splits the group's real top-k (``base_chunks``) when
        # the Dispatcher supplied one.
        base_chunks = self.base_chunks if self.base_chunks is not None else self.chunks
        chunks_per_source = max(1, base_chunks // len(self.vectorstores))
        token_budget = max(int(self.doc_token_limit * 0.9), 100)
        cumulative_tokens = 0

        # Resolve every source, then fetch them all (one query embedding, one
        # bounded fan-out). The merge below stays serial and in source order, so
        # dedupe/budget/trim semantics are exactly what they were.
        plans = self._plan_sources(chunks_per_source)
        results = self._fetch_all(plans) if plans else []

        for plan, result in zip(plans, results):
            if result is None:
                continue
            vectorstore_id = plan["id"]
            src_k = plan["src_k"]
            docs_temp, score_kind = result
            try:
                # ``_fetch_candidates`` over-fetches (k >= 20) so a prescreen
                # stage has candidates to filter; trim back to src_k so
                # ``chunks`` is the final top-k it claims to be. With
                # prescreen on, src_k is already raised to candidate_k above,
                # so the stage still sees its full candidate set.
                kept = 0

                for doc in docs_temp:
                    if kept >= src_k or cumulative_tokens >= token_budget:
                        break

                    score = None
                    if isinstance(doc, tuple):
                        doc, score = doc

                    if hasattr(doc, "page_content") and hasattr(doc, "metadata"):
                        page_content = doc.page_content
                        metadata = doc.metadata
                    else:
                        page_content = doc.get("text", doc.get("page_content", ""))
                        metadata = doc.get("metadata", {})

                    labels = labels_from_metadata(metadata, page_content, vectorstore_id)

                    doc_text_with_header = f"{labels['filename']}\n{page_content}"
                    doc_tokens = num_tokens_from_string(doc_text_with_header)

                    if cumulative_tokens + doc_tokens < token_budget:
                        entry = {"text": page_content, **labels}
                        if self.include_scores:
                            entry["score"] = score
                            entry["score_kind"] = score_kind
                        all_docs.append(entry)
                        cumulative_tokens += doc_tokens
                        kept += 1

                if cumulative_tokens >= token_budget:
                    break

            except Exception as e:
                logger.error(
                    f"Error searching vectorstore {vectorstore_id}: {e}",
                    exc_info=True,
                )
                continue

        # ``chunks_per_source`` has a floor of 1 so no attached source is
        # starved, which means N sources always yield at least N documents —
        # ``chunks=2`` across 4 sources returned 4, though ``chunks`` is
        # documented as a top-k. Bound the overshoot to exactly that floor so
        # attaching more sources can no longer inflate the result without limit.
        # Ceiling on ``self.chunks`` (the actual fetch target), not
        # ``base_chunks``: under prescreen the former is the inflated
        # candidate_k the Dispatcher asked for and trims itself later.
        ceiling = max(self.chunks, len(self.vectorstores))
        if len(all_docs) > ceiling:
            logger.info(
                "ClassicRAG._get_data: trimming %d documents to the %d ceiling "
                "(top-k=%d across %d sources).",
                len(all_docs), ceiling, base_chunks, len(self.vectorstores),
            )
            all_docs = all_docs[:ceiling]

        logger.info(
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
