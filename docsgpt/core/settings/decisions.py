"""The decision model (arc-decide): where it runs, which files it loads and how calls share the CPU."""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import NoDecode

from docsgpt.core.paths import home_dir
from docsgpt.core.settings._shared import EnvList, SettingsGroup, normalize_choice


class DecisionSettings(SettingsGroup):
    """The small classifier that answers typed questions about a state; every feature that uses it ships off."""

    DECISION_MODE: Optional[Literal["none", "local", "api"]] = Field(
        default=None,
        description=(
            "`none` turns the decision model off everywhere; `local` runs it inside the API process, which Celery "
            "workers call with `INTERNAL_KEY`; `api` calls the server at `DECISION_BASE_URL`. Unset means `api` "
            "when `DECISION_BASE_URL` is set and `local` otherwise; neither loads anything until a feature asks for "
            "it."
        ),
    )
    DECISION_BASE_URL: Optional[str] = Field(
        default=None,
        description=(
            "A decision server to call instead of running the model here: a `docsgpt decide-server`, `arcd serve` "
            "or stock vLLM (with `DECISION_PROTOCOL=vllm`). It receives the text of every state it is asked about."
        ),
    )
    DECISION_PROTOCOL: Literal["decide", "vllm"] = Field(
        default="decide",
        description=(
            "How `DECISION_BASE_URL` is called: `decide` for the `/v1/decide` contract, `vllm` for stock vLLM's "
            "`/v1/completions` (served with `--logprobs-mode processed_logprobs --max-logprobs 16`)."
        ),
    )
    DECISION_KEY: Optional[str] = Field(
        default=None,
        description=(
            "Bearer key sent to `DECISION_BASE_URL`, and only there. Unset sends no key; `INTERNAL_KEY` is never "
            "sent to the decision server."
        ),
    )
    DECISION_MODEL: Optional[str] = Field(
        default=None,
        description=(
            "Decision model repository. Unset follows the runtime: arc53/arc-decide-0.4b-v0.2 on ONNX, "
            "arc53/arc-decide-0.6b-v0.1 on vLLM; a `decide` server answers with the model it reports."
        ),
    )
    DECISION_MODEL_REVISION: Optional[str] = Field(
        default=None,
        description=(
            "Hub commit to download instead of the pinned one. The pin keeps question wording and calibration "
            "from changing under stored scores."
        ),
    )
    DECISION_MODEL_PATH: Optional[str] = Field(
        default=None,
        description=(
            "A local copy of the model (a snapshot folder or its onnx folder). Nothing is downloaded; for "
            "air-gapped installs."
        ),
    )
    DECISION_CACHE_DIR: str = Field(
        default_factory=lambda: str(home_dir() / "models" / "decision"),
        description=(
            "Where the decision model is downloaded, at its pinned revision, the first time it is needed or by "
            "`docsgpt decisions prefetch`."
        ),
    )
    DECISION_DEVICE: Literal["cpu", "mps", "cuda"] = Field(
        default="cpu",
        description=(
            "Where `docsgpt decide-server` runs the model: `cpu` (ONNX) or, with the `decisions-torch` extra, "
            "`mps` (a Mac's GPU) or `cuda` (PyTorch). Read by `decide-server` only; the API and the worker never "
            "load PyTorch, which cannot share a macOS process with faiss."
        ),
    )
    DECISION_THREADS: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Threads for the decision model. Unset uses the CPUs this process may use (affinity, cgroup quota, "
            "physical cores); onnxruntime's own default counts every host core, which is far slower in a container."
        ),
    )
    DECISION_LOCAL_QUEUE: int = Field(
        default=32, ge=1, description="Calls that may wait for the model in the interactive lane before new ones fail."
    )
    DECISION_BACKGROUND_QUEUE: int = Field(
        default=8, ge=1, description="Calls that may wait for the model in the background lane before new ones fail."
    )
    DECISION_BACKGROUND_SHARE: float = Field(
        default=0.25,
        ge=0.05,
        le=1.0,
        description=(
            "Largest share of wall time background decision work may keep the CPU busy; interactive calls are "
            "never throttled."
        ),
    )
    DECISION_PRELOAD: bool = Field(
        default=False,
        description=(
            "Download, load and time the decision model when an API process starts (under gunicorn, as the image "
            "and `docsgpt api` run it), even with every feature off."
        ),
    )
    DECISION_LOAD_RETRY_SECONDS: int = Field(
        default=300, ge=1, description="Seconds before a failed download or load of the decision model is retried."
    )
    DECISION_MIN_FREE_MB: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Refuse to load the decision model with less free memory than this, in MB. Unset uses the model's "
            "own figure: 1200 for v0.2 (it peaks under 1 GB)."
        ),
    )
    DECISION_HOT_TIMEOUT: float = Field(
        default=3.0, gt=0, description="Default deadline, in seconds, of a decision someone is waiting for."
    )
    DECISION_BACKGROUND_TIMEOUT: float = Field(
        default=120.0, gt=0, description="Default deadline, in seconds, of a background decision."
    )
    DECISION_MAX_BATCH_STATES: int = Field(
        default=128, ge=1, le=1000, description="Most states one decision call may carry; more is a caller bug."
    )
    DECISION_MAX_TEXT_CHARS: int = Field(
        default=4500,
        ge=200,
        le=20000,
        description="Characters a long state field is cut to before the decision model's tokenizer has loaded.",
    )
    DECISION_CACHE_SIZE: int = Field(
        default=2048, ge=0, description="Decision answers kept in memory per process; 0 disables the cache."
    )

    DECISION_PROBE_SECONDS: int = Field(
        default=30,
        ge=5,
        description=(
            "API mode: seconds between two reads of the server's `/v1/models` (its model, status, speed and the "
            "round trip)."
        ),
    )
    DECISION_BATCH_SIZE: int = Field(
        default=32, ge=1, le=256, description="API mode: states per `/v1/decide/batch` request."
    )
    DECISION_API_CONCURRENCY: int = Field(
        default=4, ge=1, description="API mode: requests in flight at once for decisions someone is waiting for."
    )
    DECISION_BACKGROUND_CONCURRENCY: int = Field(
        default=1,
        ge=1,
        description="API mode: requests in flight at once for background decisions; they never take interactive slots.",
    )
    DECISION_API_RETRIES: int = Field(
        default=1,
        ge=0,
        le=1,
        description=(
            "API mode: retries of a request after a connection error or a 502, 503 or 504, made only while 30% of "
            "the call's deadline remains. Timeouts and other errors are not retried."
        ),
    )
    DECISION_BREAKER_FAILURES: int = Field(
        default=3,
        ge=1,
        description="API mode: consecutive transport failures after which calls are skipped for the cooldown.",
    )
    DECISION_BREAKER_COOLDOWN: float = Field(
        default=30.0,
        ge=0,
        description="API mode: seconds calls are skipped after the failures above; then one is let through.",
    )
    DECISION_VLLM_PRIORITY: bool = Field(
        default=False,
        description=(
            "vLLM protocol: send request priorities (interactive before background). Only valid when vLLM runs "
            "with `--scheduling-policy priority`."
        ),
    )
    DECISION_USAGE_RETENTION_DAYS: int = Field(
        default=90,
        ge=1,
        description=(
            "Days the per-day counts of decision-model calls (`decision_usage`) are kept before the cleanup task "
            "removes them."
        ),
    )

    # Model-scored relevance in retrieval (the rerank stage and the decision prescreen backend).
    DECISION_RERANK_MODE: Literal["off", "monitor", "on", "auto"] = Field(
        default="off",
        description=(
            "Rerank retrieved chunks by the decision model's relevance score: classic and hybrid sources fetch "
            "DECISION_RERANK_CANDIDATE_K candidates and keep as many chunks as they would without it, most "
            "relevant first. `monitor` scores and records without changing the result; `auto` is `on` while the "
            "predicted call on this machine fits DECISION_RERANK_BUDGET (a GPU or API-mode server, rarely a CPU). "
            "While it is not off, a source's `reranker` can opt that source in (any retriever, outside the rollout) or "
            "out; while it is off, no source is reranked and the model is never loaded for it. No stage runs with "
            "PER_SOURCE_RETRIEVAL_ENABLED=false."
        ),
    )
    DECISION_RERANK_BUDGET: float = Field(
        default=3.0,
        gt=0,
        description=(
            "Under DECISION_RERANK_MODE=auto, the longest predicted time, in seconds, of one rerank call "
            "(DECISION_RERANK_CANDIDATE_K chunks; best-window passages on a CPU, whole chunks elsewhere)."
        ),
    )
    DECISION_RERANK_ROLLOUT_PERCENT: int = Field(
        default=100,
        ge=0,
        le=100,
        description=(
            "Share of conversations, by a hash of the conversation id, that the instance rerank mode applies to; "
            "the rest are the `control` arm. The decision record and the trace carry the arm."
        ),
    )
    DECISION_RERANK_RETRIEVERS: Annotated[list[str], NoDecode, EnvList()] = Field(
        default=["classic", "hybrid"],
        description=(
            "Retrievers the instance rerank mode applies to, as a JSON list or comma-separated keys. A source of "
            "another retriever (graphrag) can still turn it on with its own `reranker` setting."
        ),
    )
    DECISION_RERANK_CANDIDATE_K: int = Field(
        default=20,
        ge=1,
        le=100,
        description=(
            "Candidates a reranked retrieval fetches and scores; a source's `reranker.candidate_k` overrides it."
        ),
    )
    DECISION_RERANK_THRESHOLD: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Reranked chunks scoring below this relevance are dropped (keeping DECISION_RELEVANCE_MIN_KEEP); 0 "
            "reorders only. A source's `reranker.min_relevance` overrides it."
        ),
    )
    DECISION_RERANK_CANDIDATE_TOKENS: int = Field(
        default=60000,
        ge=1,
        description=(
            "Token budget of the rerank's candidate fetch, so a small model context does not cut the candidates in "
            "retriever order; the request's own document budget applies after the rerank."
        ),
    )
    DECISION_PRESCREEN_ENABLED: bool = Field(
        default=False,
        description=(
            "Run prescreens set to `backend: decision` on the decision model: one call that keeps chunks at or "
            "above DECISION_PRESCREEN_THRESHOLD, most relevant first. While false, those prescreens run on the LLM "
            "as `backend: llm` does, and no source can make the model load."
        ),
    )
    DECISION_PRESCREEN_THRESHOLD: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description=(
            "Default `min_relevance` of a prescreen with `backend: decision`: chunks scoring below it are dropped, "
            "keeping DECISION_RELEVANCE_MIN_KEEP."
        ),
    )
    DECISION_RELEVANCE_MIN_KEEP: int = Field(
        default=1,
        ge=0,
        description="Chunks a relevance threshold always keeps from a non-empty retrieval, most relevant first.",
    )
    DECISION_RELEVANCE_MAX_PASSAGES: int = Field(
        default=100,
        ge=1,
        le=128,
        description="Most chunks one relevance call scores; later candidates are not considered.",
    )
    DECISION_RELEVANCE_TIMEOUT: float = Field(
        default=2.0,
        gt=0,
        description=(
            "Deadline, in seconds, of one relevance call; past it the retrieval returns what it would without the "
            "model."
        ),
    )
    DECISION_RELEVANCE_CPU_PASSAGE_TOKENS: int = Field(
        default=256,
        ge=128,
        le=2048,
        description=(
            "Where the decision model runs on a CPU, each chunk is scored on its first 64 tokens plus the window "
            "sharing the most words with the query, this many tokens in all; GPU and API-mode servers score whole "
            "chunks."
        ),
    )

    @field_validator(
        "DECISION_MODE", "DECISION_PROTOCOL", "DECISION_DEVICE", "DECISION_RERANK_MODE", mode="before"
    )
    @classmethod
    def _normalize_mode(cls, v):
        return normalize_choice(v)
