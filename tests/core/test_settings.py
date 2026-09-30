"""Contract tests for ``docsgpt.core.settings``.

``Settings`` is composed from one ``SettingsGroup`` per domain; these tests pin
the properties that composition must keep (flat names, no duplicate fields,
validators from every group applied) and that the generated reference page
tracks the definitions.
"""

import types
import typing
import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

from docsgpt.core.settings import SETTINGS_GROUPS, Settings, settings
from docsgpt.core.settings.reference import reference_path, render_reference

SECRET_FIELDS = (
    "API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "NOVITA_API_KEY",
    "OPEN_ROUTER_API_KEY",
    "EMBEDDINGS_KEY",
    "FALLBACK_LLM_API_KEY",
    "QDRANT_API_KEY",
    "ELASTIC_PASSWORD",
    "ELEVENLABS_API_KEY",
    "INTERNAL_KEY",
    "SCIM_TOKEN",
    "OIDC_ISSUER",
    "GITHUB_ACCESS_TOKEN",
    "MICROSOFT_AUTHORITY",
    "MCP_OAUTH_REDIRECT_URI",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "SANDBOX_GATEWAY_AUTH_TOKEN",
    "DAYTONA_API_KEY",
)


@pytest.mark.unit
class TestComposition:
    def test_every_group_field_is_a_flat_settings_attribute(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)  # reading a deprecated field warns
            for _, group in SETTINGS_GROUPS:
                for name in group.model_fields:
                    assert name in Settings.model_fields, name
                    assert hasattr(settings, name), name

    def test_deprecated_fields_warn_on_read(self):
        with pytest.warns(DeprecationWarning, match="S3_REGION"):
            _ = Settings(_env_file=None).SAGEMAKER_REGION

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

    Pydantic collects validators by method name across the MRO, so two groups
    defining one under the same name would silently keep only one; the checks
    below span every group.
    """

    def test_every_optional_string_treats_unset_spellings_as_none(self):
        names = [
            name
            for name, field in Settings.model_fields.items()
            if typing.get_origin(field.annotation) in (typing.Union, types.UnionType)
            and type(None) in typing.get_args(field.annotation)
            and all(a is str or typing.get_origin(a) is typing.Literal for a in typing.get_args(field.annotation) if a is not type(None))
        ]
        assert len(names) > 60
        assert {"EMBEDDINGS_POOLING", "AUTH_TYPE", "OIDC_ISSUER"} <= set(names)
        loaded = Settings.model_validate({name: " None " for name in names})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            assert [name for name in names if getattr(loaded, name) is not None] == []

    def test_plain_strings_keep_empty_values(self):
        assert Settings.model_validate({"MILVUS_TOKEN": "", "JWT_SECRET_KEY": ""}).MILVUS_TOKEN == ""

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


DEFAULT_TOOLS = ["memory", "read_webpage", "scheduler"]


def _list_fields() -> list[str]:
    """Every settings field whose type is a list (optional or not)."""

    def is_list(annotation) -> bool:
        if typing.get_origin(annotation) is list:
            return True
        return any(is_list(arg) for arg in typing.get_args(annotation))

    return [name for name, field in Settings.model_fields.items() if is_list(field.annotation)]


@pytest.mark.unit
class TestListSettings:
    """List settings accept a JSON list or comma-separated values, from the environment or a .env file."""

    def test_every_list_setting_takes_the_shared_parsing(self):
        from pydantic_settings import NoDecode

        from docsgpt.core.settings._shared import EnvList

        names = _list_fields()
        assert {"DEFAULT_CHAT_TOOLS", "GUARDRAILS_CHECKS_ENABLED", "QUOTA_UNPRICED_RATE_PER_MILLION"} <= set(names)
        for name in names:
            metadata = Settings.model_fields[name].metadata
            assert NoDecode in metadata, name
            assert any(isinstance(item, EnvList) for item in metadata), name

    @pytest.mark.parametrize(
        ("name", "raw", "expected"),
        [
            ("DEFAULT_CHAT_TOOLS", '["memory","code_executor"]', ["memory", "code_executor"]),
            ("DEFAULT_CHAT_TOOLS", '[ "memory" , "scheduler" ]', ["memory", "scheduler"]),
            ("DEFAULT_CHAT_TOOLS", "memory,read_webpage,scheduler", ["memory", "read_webpage", "scheduler"]),
            ("DEFAULT_CHAT_TOOLS", " memory , read_webpage ,", ["memory", "read_webpage"]),
            ("DEFAULT_CHAT_TOOLS", "memory", ["memory"]),
            ("GUARDRAILS_CHECKS_ENABLED", '["secrets","pii"]', ["secrets", "pii"]),
            ("GUARDRAILS_CHECKS_ENABLED", "secrets, pii", ["secrets", "pii"]),
            ("GUARDRAILS_CHECKS_ENABLED", "secrets", ["secrets"]),
            ("QUOTA_UNPRICED_RATE_PER_MILLION", "[0.5, 1.5]", [0.5, 1.5]),
            ("QUOTA_UNPRICED_RATE_PER_MILLION", "0.5,1.5", [0.5, 1.5]),
        ],
    )
    def test_environment_value(self, monkeypatch, name, raw, expected):
        monkeypatch.setenv(name, raw)
        assert getattr(Settings(_env_file=None), name) == expected

    @pytest.mark.parametrize(
        ("line", "name", "expected"),
        [
            ('DEFAULT_CHAT_TOOLS=["memory","scheduler"]', "DEFAULT_CHAT_TOOLS", ["memory", "scheduler"]),
            ("DEFAULT_CHAT_TOOLS=memory,read_webpage", "DEFAULT_CHAT_TOOLS", ["memory", "read_webpage"]),
            ("DEFAULT_CHAT_TOOLS=memory", "DEFAULT_CHAT_TOOLS", ["memory"]),
            ("DEFAULT_CHAT_TOOLS=", "DEFAULT_CHAT_TOOLS", DEFAULT_TOOLS),
            ("DEFAULT_CHAT_TOOLS=none", "DEFAULT_CHAT_TOOLS", []),
            ("GUARDRAILS_CHECKS_ENABLED=secrets,pii", "GUARDRAILS_CHECKS_ENABLED", ["secrets", "pii"]),
            ("QUOTA_UNPRICED_RATE_PER_MILLION=0.5,1.5", "QUOTA_UNPRICED_RATE_PER_MILLION", [0.5, 1.5]),
        ],
    )
    def test_env_file_value(self, monkeypatch, tmp_path, line, name, expected):
        monkeypatch.delenv(name, raising=False)
        env = tmp_path / ".env"
        env.write_text(line + "\n")
        assert getattr(Settings(_env_file=env), name) == expected

    @pytest.mark.parametrize(
        ("name", "default"),
        [
            ("DEFAULT_CHAT_TOOLS", DEFAULT_TOOLS),
            ("GUARDRAILS_CHECKS_ENABLED", []),
            ("QUOTA_UNPRICED_RATE_PER_MILLION", None),
        ],
    )
    @pytest.mark.parametrize("raw", ["", "   "])
    def test_empty_value_keeps_the_default(self, monkeypatch, name, default, raw):
        monkeypatch.setenv(name, raw)
        assert getattr(Settings(_env_file=None), name) == default

    @pytest.mark.parametrize("raw", ["none", "NONE", " None ", "[]"])
    def test_none_turns_the_default_chat_tools_off(self, monkeypatch, raw):
        monkeypatch.setenv("DEFAULT_CHAT_TOOLS", raw)
        assert Settings(_env_file=None).DEFAULT_CHAT_TOOLS == []

    def test_none_is_unset_for_an_optional_list(self, monkeypatch):
        monkeypatch.setenv("QUOTA_UNPRICED_RATE_PER_MILLION", "None")
        assert Settings(_env_file=None).QUOTA_UNPRICED_RATE_PER_MILLION is None

    def test_python_list_is_kept(self):
        assert Settings.model_validate({"DEFAULT_CHAT_TOOLS": ["memory"]}).DEFAULT_CHAT_TOOLS == ["memory"]

    def test_unset_keeps_the_default(self, monkeypatch):
        monkeypatch.delenv("DEFAULT_CHAT_TOOLS", raising=False)
        assert Settings(_env_file=None).DEFAULT_CHAT_TOOLS == DEFAULT_TOOLS

    @pytest.mark.parametrize("name", ["DEFAULT_CHAT_TOOLS", "GUARDRAILS_CHECKS_ENABLED"])
    def test_malformed_json_list_is_rejected(self, monkeypatch, name):
        monkeypatch.setenv(name, '["memory",')
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_quota_rates_are_still_checked(self, monkeypatch):
        monkeypatch.setenv("QUOTA_UNPRICED_RATE_PER_MILLION", "0.5")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)


@pytest.mark.unit
class TestReference:
    def test_reference_lists_every_setting_once(self):
        page = render_reference()
        for name in Settings.model_fields:
            assert page.count(f"### `{name}`") == 1, name

    def test_reference_prose_has_no_bare_angle_brackets_or_braces(self):
        """MDX parses ``<`` and ``{`` in prose as JSX; only code spans may carry them raw."""
        for lineno, line in enumerate(render_reference().splitlines(), 1):
            if line.startswith(("{/*", "---")):
                continue
            prose = "".join(line.split("`")[::2])  # drop the inside of every code span
            prose = prose.replace("\\{", "").replace("\\}", "")  # escaped braces are fine
            assert "<" not in prose and "{" not in prose and "}" not in prose, f"line {lineno}: {line}"

    def test_checked_in_reference_is_current(self):
        path: Path = reference_path()
        if not path.exists():
            pytest.skip("docs tree not present (installed package, not a checkout)")
        assert path.read_text(encoding="utf-8") == render_reference(), (
            "docs/content/Deploying/Settings-Reference.mdx is stale; "
            "run: python -m docsgpt.core.settings.reference --write"
        )


@pytest.mark.unit
class TestCrossFieldRules:
    OIDC = {"OIDC_ISSUER": "https://idp.example/", "OIDC_CLIENT_ID": "docsgpt", "OIDC_FRONTEND_URL": "http://app"}

    def test_oidc_requires_issuer_client_and_frontend(self):
        with pytest.raises(ValidationError, match="AUTH_TYPE=oidc requires settings: OIDC_CLIENT_ID, OIDC_FRONTEND_URL"):
            Settings.model_validate({"AUTH_TYPE": "oidc", "OIDC_ISSUER": self.OIDC["OIDC_ISSUER"]})

    @pytest.mark.parametrize("raw", ["", "None", "  "])
    def test_oidc_unset_spellings_do_not_satisfy_the_requirement(self, raw):
        with pytest.raises(ValidationError, match="OIDC_CLIENT_ID"):
            Settings.model_validate({"AUTH_TYPE": "oidc", **self.OIDC, "OIDC_CLIENT_ID": raw})

    def test_oidc_with_required_settings_loads(self):
        assert Settings.model_validate({"AUTH_TYPE": "OIDC", **self.OIDC}).AUTH_TYPE == "oidc"

    def test_oidc_settings_are_not_required_for_other_modes(self):
        assert Settings.model_validate({"AUTH_TYPE": "session_jwt"}).OIDC_ISSUER is None

    @pytest.mark.parametrize("raw", [None, "", "None"])
    def test_scim_enabled_requires_a_token(self, raw):
        with pytest.raises(ValidationError, match="SCIM_ENABLED requires settings: SCIM_TOKEN"):
            Settings.model_validate({"SCIM_ENABLED": True, "SCIM_TOKEN": raw})

    def test_scim_disabled_needs_no_token(self):
        assert Settings.model_validate({"SCIM_ENABLED": False}).SCIM_TOKEN is None


@pytest.mark.unit
class TestClosedChoices:
    """Enum-like settings are Literal types: a typo fails at startup instead of falling through."""

    @pytest.mark.parametrize("name", ["AUTH_TYPE", "EMBEDDINGS_POOLING"])
    @pytest.mark.parametrize("raw", ["None", "none", "", "  "])
    def test_optional_choice_unset_spellings(self, name, raw):
        assert getattr(Settings.model_validate({name: raw}), name) is None

    @pytest.mark.parametrize(
        ("name", "raw", "expected"),
        [
            ("AUTH_TYPE", " Session_JWT ", "session_jwt"),
            ("VECTOR_STORE", "PGVector", "pgvector"),
            ("STORAGE_TYPE", "S3", "s3"),
            ("URL_STRATEGY", "Backend", "backend"),
            ("OCR_BACKEND", "Native", "native"),
            ("OCR_ENGINE", "Tesseract ", "tesseract"),
            ("SANDBOX_BACKEND", "Daytona", "daytona"),
            ("DOC_PARSER_ENGINE", "Docling", "docling"),
            ("TTS_PROVIDER", "ElevenLabs", "elevenlabs"),
            ("STT_PROVIDER", "", "none"),
            ("TTS_PROVIDER", "NONE", "none"),
            ("EMBEDDINGS_POOLING", "CLS", "cls"),
        ],
    )
    def test_choices_are_case_insensitive(self, name, raw, expected):
        assert getattr(Settings.model_validate({name: raw}), name) == expected

    @pytest.mark.parametrize(
        ("name", "raw"),
        [
            ("AUTH_TYPE", "basic"),
            ("VECTOR_STORE", "lancedb"),
            ("STORAGE_TYPE", "gcs"),
            ("OCR_BACKEND", "paddle"),
            ("SANDBOX_BACKEND", "docker"),
            ("DOC_PARSER_ENGINE", "fast"),
            ("STT_PROVIDER", "whisper"),
            ("EMBEDDINGS_POOLING", "max"),
        ],
    )
    def test_unknown_choice_is_rejected(self, name, raw):
        with pytest.raises(ValidationError):
            Settings.model_validate({name: raw})

    def test_lancedb_is_not_a_vector_store(self):
        """VECTOR_STORE=lancedb was never accepted; its orphaned module and settings are gone too."""
        import importlib.util

        assert not [name for name in Settings.model_fields if name.startswith("LANCEDB_")]
        assert importlib.util.find_spec("docsgpt.vectorstore.lancedb") is None

    @pytest.mark.parametrize(
        ("name", "raw"),
        [
            ("EMBEDDINGS_BATCH_SIZE", 0),
            ("COMPRESSION_THRESHOLD_PERCENTAGE", 1.5),
            ("UPLOAD_MAX_FILE_BYTES", 0),
            ("MESSAGE_EVENTS_RETENTION_DAYS", 0),
            ("REMOTE_DEVICE_CMD_QUEUE_TTL_SECONDS", 605),
            ("GRAPHRAG_MAX_CHUNKS_FOR_EXTRACTION", -1),
        ],
    )
    def test_out_of_range_numbers_are_rejected(self, name, raw):
        with pytest.raises(ValidationError):
            Settings.model_validate({name: raw})
