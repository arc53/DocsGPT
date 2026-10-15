"""The decision model (arc-decide): where it runs, which files it loads and how calls share the CPU."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, field_validator

from docsgpt.core.paths import home_dir
from docsgpt.core.settings._shared import SettingsGroup, normalize_choice


class DecisionSettings(SettingsGroup):
    """The small classifier that answers typed questions about a state; every feature that uses it ships off."""

    DECISION_MODE: Optional[Literal["none", "local"]] = Field(
        default=None,
        description=(
            "`none` turns the decision model off everywhere; `local` runs it inside the API process. Unset means "
            "`local`, which loads nothing until a feature asks for it."
        ),
    )
    DECISION_MODEL: Optional[str] = Field(
        default=None,
        description="Decision model repository. Unset follows the runtime: arc53/arc-decide-0.4b-v0.2 on ONNX.",
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

    @field_validator("DECISION_MODE", mode="before")
    @classmethod
    def _normalize_mode(cls, v):
        return normalize_choice(v)
