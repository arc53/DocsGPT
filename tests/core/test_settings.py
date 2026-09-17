"""Contract tests for ``docsgpt.core.settings``.

``Settings`` is composed from one ``SettingsGroup`` per domain; these tests pin
the properties that composition must keep (flat names, no duplicate fields,
validators from every group applied) and that the generated reference page
tracks the definitions.
"""

from pathlib import Path

import pytest

from docsgpt.core.settings import SETTINGS_GROUPS, Settings, settings
from docsgpt.core.settings.reference import reference_path, render_reference

SECRET_FIELDS = (
    "API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "HUGGINGFACE_API_KEY",
    "NOVITA_API_KEY",
    "EMBEDDINGS_KEY",
    "FALLBACK_LLM_API_KEY",
    "QDRANT_API_KEY",
    "ELEVENLABS_API_KEY",
    "INTERNAL_KEY",
)


@pytest.mark.unit
class TestComposition:
    def test_every_group_field_is_a_flat_settings_attribute(self):
        for _, group in SETTINGS_GROUPS:
            for name in group.model_fields:
                assert name in Settings.model_fields, name
                assert hasattr(settings, name), name

    def test_no_field_is_defined_in_two_groups(self):
        owners: dict[str, str] = {}
        for title, group in SETTINGS_GROUPS:
            for name in group.model_fields:
                assert name not in owners, f"{name} is defined in both {owners[name]} and {title}"
                owners[name] = title
        assert len(owners) == len(Settings.model_fields)

    def test_every_field_has_a_description(self):
        missing = [name for name, field in Settings.model_fields.items() if not field.description]
        assert not missing, f"settings without a description: {missing}"

    def test_defaults_load_without_an_env_file(self, monkeypatch):
        for name in Settings.model_fields:
            monkeypatch.delenv(name, raising=False)
        fresh = Settings(_env_file=None)
        assert fresh.LLM_PROVIDER == "docsgpt"
        assert fresh.VECTOR_STORE == "faiss"


@pytest.mark.unit
class TestValidators:
    """Validators live on the group that owns the field; composition must keep all of them.

    Two groups defining a validator under the same method name would silently
    keep only one, so this checks every secret field, across every group.
    """

    @pytest.mark.parametrize("name", SECRET_FIELDS)
    @pytest.mark.parametrize("raw", ["None", "none", "", "   "])
    def test_unset_secret_spellings_become_none(self, name, raw):
        assert getattr(Settings.model_validate({name: raw}), name) is None

    @pytest.mark.parametrize("name", SECRET_FIELDS)
    def test_secret_is_stripped(self, name):
        assert getattr(Settings.model_validate({name: "  k3y  "}), name) == "k3y"

    def test_normalize_api_key_classmethod_is_kept(self):
        assert Settings.normalize_api_key("None") is None
        assert Settings.normalize_api_key("  x ") == "x"
        assert Settings.normalize_api_key(42) == 42

    def test_postgres_uris_are_normalized(self):
        loaded = Settings.model_validate(
            {"POSTGRES_URI": "postgres://u:p@h/db", "PGVECTOR_CONNECTION_STRING": "postgresql+psycopg://u:p@h/v"}
        )
        assert loaded.POSTGRES_URI.startswith("postgresql+psycopg://")
        assert loaded.PGVECTOR_CONNECTION_STRING.startswith("postgresql://")

    def test_legacy_docling_ocr_aliases_are_read(self):
        loaded = Settings.model_validate({"DOCLING_OCR_ENABLED": "true", "DOCLING_OCR_MIN_CHARS_PER_PAGE": "7"})
        assert loaded.OCR_ENABLED is True
        assert loaded.OCR_MIN_CHARS_PER_PAGE == 7


@pytest.mark.unit
class TestReference:
    def test_reference_lists_every_setting_once(self):
        page = render_reference()
        for name in Settings.model_fields:
            assert page.count(f"### `{name}`") == 1, name

    def test_checked_in_reference_is_current(self):
        path: Path = reference_path()
        if not path.exists():
            pytest.skip("docs tree not present (installed package, not a checkout)")
        assert path.read_text(encoding="utf-8") == render_reference(), (
            "docs/content/Deploying/Settings-Reference.mdx is stale; "
            "run: python -m docsgpt.core.settings.reference --write"
        )
