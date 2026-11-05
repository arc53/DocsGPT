"""The decision model (arc-decide): where it runs, which files it loads and how calls share the CPU."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, field_validator

from docsgpt.core.paths import home_dir
from docsgpt.core.settings._shared import SettingsGroup, normalize_choice


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

    # Model-scored prompt injection in guardrails: the operator's switch. Policy (which agents, stages, actions and
    # thresholds; the floor) lives in the UI.
    DECISION_INJECTION_ENABLED: bool = Field(
        default=False,
        description=(
            "Let the decision model score text for prompt injection: the `injection_model` guardrail check of "
            "agents and of the floor (Admin > Guardrails), chat attachments once uploaded, and MCP tool descriptions "
            "when Admin > Guardrails warns on them. While false nothing loads or calls the model for "
            "guardrails, those controls are not evaluated, and the UI marks the check unavailable. While true, the "
            "API process (or the decide server) loads the model at start."
        ),
    )

    # Conversation analytics: the operator's switch. Which agents are labelled, with which topics and tags, lives in
    # the UI; the sweep's tuning knobs are the ANALYTICS_* settings.
    DECISION_ANALYTICS_ENABLED: bool = Field(
        default=False,
        description=(
            "Let the decision model label stored conversations in the background (answer status, docs gaps, "
            "reactions, frustration, requests for a person, goal met, topics and custom tags) for the Analytics "
            "and Logs pages. While false the sweep does nothing and the UI says how to turn it on. While true, the "
            "worker labels conversations without an agent and those of every agent whose analytics setting is on, "
            "calling the model at background priority, and the API process (or the decide server) loads the model "
            "at start."
        ),
    )

    # Model-scored relevance in retrieval: the operator's switch, then the tuning knobs (never shown in the UI).
    DECISION_RELEVANCE_ENABLED: bool = Field(
        default=False,
        description=(
            "Let the decision model score retrieved chunks for the sources whose relevance setting is on (their "
            "`reranker`). While false, no source's setting calls or loads the model, retrieval returns what it "
            "would without it, and the source settings hide the relevance controls. While true, the API process (or "
            "the decide server) loads the model at start, so the first answer does not fall back while it loads. "
            "No stage runs with PER_SOURCE_RETRIEVAL_ENABLED=false."
        ),
    )
    DECISION_RELEVANCE_ROLLOUT_PERCENT: int = Field(
        default=100,
        ge=0,
        le=100,
        description=(
            "Share of conversations, by a hash of the conversation id, in which sources with relevance on are "
            "scored; the rest are the `control` arm and keep the retriever's output. The decision record and the "
            "trace carry the arm. The retrieval test ignores it."
        ),
    )
    DECISION_RELEVANCE_CANDIDATE_TOKENS: int = Field(
        default=60000,
        ge=1,
        description=(
            "Token budget of the candidate fetch for relevance, so a small model context does not cut the candidates "
            "in retriever order; the request's own document budget applies after the scoring."
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

    @field_validator("DECISION_MODE", "DECISION_PROTOCOL", "DECISION_DEVICE", mode="before")
    @classmethod
    def _normalize_mode(cls, v):
        return normalize_choice(v)
