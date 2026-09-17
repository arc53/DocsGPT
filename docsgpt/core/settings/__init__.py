"""Application settings.

``settings`` is the process-wide instance, loaded from the environment and the
``.env`` file in the data home (see ``docsgpt.core.paths``). Every setting is a
flat attribute, ``settings.NAME``, matching the environment variable of the
same name.

The definitions are split by domain into the modules of this package; each
module owns one ``SettingsGroup`` and ``Settings`` composes them all. Add a new
setting to the group it belongs to (or add a group and list it in
``SETTINGS_GROUPS``), with a ``description`` -- the settings reference in the
docs is generated from these definitions.
"""

from __future__ import annotations

from typing import Optional

from docsgpt.core.paths import env_file, home_dir
from docsgpt.core.settings._shared import SettingsGroup, normalize_secret
from docsgpt.core.settings.agents import AgentSettings
from docsgpt.core.settings.auth import AuthSettings
from docsgpt.core.settings.connectors import ConnectorSettings
from docsgpt.core.settings.database import DatabaseSettings
from docsgpt.core.settings.embeddings import EmbeddingsSettings
from docsgpt.core.settings.events import EventsSettings
from docsgpt.core.settings.guardrails import GuardrailSettings
from docsgpt.core.settings.ingestion import IngestionSettings
from docsgpt.core.settings.llm import LLMSettings
from docsgpt.core.settings.ocr import OCRSettings
from docsgpt.core.settings.retrieval import RetrievalSettings
from docsgpt.core.settings.sandbox import SandboxSettings
from docsgpt.core.settings.scheduler import SchedulerSettings
from docsgpt.core.settings.server import ServerSettings
from docsgpt.core.settings.speech import SpeechSettings
from docsgpt.core.settings.storage import StorageSettings
from docsgpt.core.settings.vectorstores import VectorStoreSettings
from docsgpt.core.settings.workers import WorkerSettings

#: Every settings group, in the order the generated reference lists them.
SETTINGS_GROUPS: tuple[tuple[str, type[SettingsGroup]], ...] = (
    ("Authentication", AuthSettings),
    ("LLM providers", LLMSettings),
    ("Embeddings", EmbeddingsSettings),
    ("Retrieval", RetrievalSettings),
    ("Vector stores", VectorStoreSettings),
    ("User-data database", DatabaseSettings),
    ("Workers", WorkerSettings),
    ("Ingestion and parsing", IngestionSettings),
    ("OCR", OCRSettings),
    ("File storage", StorageSettings),
    ("Connectors", ConnectorSettings),
    ("Server", ServerSettings),
    ("Events and devices", EventsSettings),
    ("Agents", AgentSettings),
    ("Guardrails", GuardrailSettings),
    ("Scheduler", SchedulerSettings),
    ("Sandbox", SandboxSettings),
    ("Speech", SpeechSettings),
)

# Runtime data home (DOCSGPT_HOME, the checkout, or cwd); see docsgpt.core.paths.
current_dir = str(home_dir())


class Settings(*(group for _, group in SETTINGS_GROUPS)):
    """All settings, composed from the per-domain groups in this package."""

    @classmethod
    def normalize_api_key(cls, v: Optional[str]) -> Optional[str]:
        """Normalize a secret the way the per-field validators do; kept for callers that reuse it."""
        return normalize_secret(v)


settings = Settings(_env_file=env_file(), _env_file_encoding="utf-8")

__all__ = ["SETTINGS_GROUPS", "Settings", "SettingsGroup", "current_dir", "settings"]
