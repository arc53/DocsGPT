"""What `docsgpt up` writes to the stack's .env, and where the stack lives."""

from itertools import count
from pathlib import Path

import pytest

from docsgpt.core import paths
from docsgpt.deploy import stack

REPO_ROOT = Path(__file__).resolve().parents[2]


def _secrets():
    numbers = count(1)
    return lambda: f"secret{next(numbers)}"


def _first_install(**overrides):
    options = {"image_tag": "0.21.0", "fresh_database": True, "secret": _secrets()}
    options.update(overrides)
    return stack.plan({}, **options)


class TestFirstInstall:
    def test_defaults_are_local_with_the_public_api(self):
        updates = _first_install()
        assert updates["DOCSGPT_IMAGE_TAG"] == "0.21.0"
        assert updates["DOCSGPT_BIND"] == "127.0.0.1"
        assert updates["LLM_PROVIDER"] == "docsgpt"
        assert updates["VITE_API_STREAMING"] == "true"
        assert "AUTH_TYPE" not in updates

    def test_secrets_are_generated_once_each(self):
        updates = _first_install()
        generated = {updates["INTERNAL_KEY"], updates["JWT_SECRET_KEY"], updates["POSTGRES_PASSWORD"]}
        assert len(generated) == 3

    def test_an_existing_database_keeps_its_password(self):
        """Postgres reads the password only when its volume is created."""
        updates = _first_install(fresh_database=False)
        assert "POSTGRES_PASSWORD" not in updates


class TestRerun:
    def test_secrets_and_settings_are_left_alone(self):
        existing = {
            "DOCSGPT_IMAGE_TAG": "0.20.0",
            "INTERNAL_KEY": "k",
            "JWT_SECRET_KEY": "j",
            "POSTGRES_PASSWORD": "p",
            "VITE_API_STREAMING": "true",
            "LLM_PROVIDER": "anthropic",
            "API_KEY": "sk",
            "DOCSGPT_BIND": "0.0.0.0",
            "AUTH_TYPE": "simple_jwt",
        }
        updates = stack.plan(existing, image_tag="0.21.0", fresh_database=False, secret=_secrets())
        assert updates == {"DOCSGPT_IMAGE_TAG": "0.21.0"}

    def test_a_missing_password_is_not_invented_for_an_existing_database(self):
        updates = stack.plan({"INTERNAL_KEY": "k", "JWT_SECRET_KEY": "j"}, image_tag="x", fresh_database=False)
        assert "POSTGRES_PASSWORD" not in updates


class TestExposure:
    def test_network_publishes_everywhere_and_turns_on_auth(self):
        updates = _first_install(expose="network")
        assert updates["DOCSGPT_BIND"] == "0.0.0.0"
        assert updates["AUTH_TYPE"] == "simple_jwt"
        assert updates.get("COMPOSE_PROFILES") is None

    def test_domain_adds_caddy_and_auth_and_keeps_the_port_local(self):
        updates = _first_install(expose="domain", domain="docs.example.com")
        assert updates["COMPOSE_PROFILES"] == "https"
        assert updates["DOCSGPT_DOMAIN"] == "docs.example.com"
        assert updates["DOCSGPT_BIND"] == "127.0.0.1"
        assert updates["AUTH_TYPE"] == "simple_jwt"

    def test_domain_needs_a_domain(self):
        with pytest.raises(ValueError, match="domain"):
            _first_install(expose="domain")

    def test_an_existing_auth_mode_is_not_downgraded(self):
        updates = stack.plan({"AUTH_TYPE": "oidc"}, image_tag="x", expose="network", fresh_database=False)
        assert "AUTH_TYPE" not in updates

    def test_back_to_local_removes_the_proxy(self):
        existing = {"COMPOSE_PROFILES": "https", "DOCSGPT_DOMAIN": "docs.example.com", "DOCSGPT_BIND": "127.0.0.1"}
        updates = stack.plan(existing, image_tag="x", expose="local", fresh_database=False)
        assert updates["COMPOSE_PROFILES"] is None
        assert updates["DOCSGPT_DOMAIN"] is None

    def test_port_and_docling(self):
        updates = _first_install(port=8080, docling=True)
        assert updates["DOCSGPT_PORT"] == "8080"
        assert updates["DOCSGPT_IMAGE_VARIANT"] == "-docling"
        assert stack.plan({"DOCSGPT_IMAGE_VARIANT": "-docling"}, image_tag="x", docling=False, fresh_database=False)[
            "DOCSGPT_IMAGE_VARIANT"
        ] is None

    @pytest.mark.parametrize(
        "env, mode",
        [
            ({}, "local"),
            ({"DOCSGPT_BIND": "0.0.0.0"}, "network"),
            ({"COMPOSE_PROFILES": "https", "DOCSGPT_DOMAIN": "d.example.com"}, "domain"),
        ],
    )
    def test_the_mode_is_read_back_from_the_env(self, env, mode):
        assert stack.exposure(env) == mode


class TestProviders:
    def test_switching_provider_drops_the_old_keys(self):
        existing = {"LLM_PROVIDER": "openai", "API_KEY": "sk", "LLM_NAME": "m", "OPENAI_BASE_URL": "http://x/v1"}
        provider = stack.provider_settings("anthropic", api_key="ak")
        updates = stack.plan(existing, image_tag="x", provider=provider, fresh_database=False)
        assert updates["LLM_PROVIDER"] == "anthropic"
        assert updates["API_KEY"] == "ak"
        assert updates["LLM_NAME"] is None
        assert updates["OPENAI_BASE_URL"] is None

    def test_the_public_api_needs_no_key(self):
        assert stack.provider_settings("docsgpt") == {
            "LLM_PROVIDER": "docsgpt",
            "API_KEY": None,
            "LLM_NAME": None,
            "OPENAI_BASE_URL": None,
        }

    def test_a_hosted_provider_needs_a_key(self):
        with pytest.raises(ValueError, match="API key"):
            stack.provider_settings("openai")

    def test_an_openai_compatible_server_needs_a_url_and_a_model(self):
        with pytest.raises(ValueError, match="base URL"):
            stack.provider_settings("openai-compatible", model="llama3")
        settings = stack.provider_settings("openai-compatible", base_url="http://host.docker.internal:11434/v1", model="llama3")
        assert settings == {
            "LLM_PROVIDER": "openai",
            "API_KEY": "not-needed",
            "LLM_NAME": "llama3",
            "OPENAI_BASE_URL": "http://host.docker.internal:11434/v1",
        }

    def test_an_unknown_provider(self):
        with pytest.raises(ValueError, match="unknown provider"):
            stack.provider_settings("nope")


class TestUrls:
    def test_local(self):
        assert stack.url({"DOCSGPT_PORT": "8080"}, lan_ip="10.0.0.5") == "http://localhost:8080"

    def test_network_uses_the_machine_address(self):
        assert stack.url({"DOCSGPT_BIND": "0.0.0.0"}, lan_ip="10.0.0.5") == "http://10.0.0.5:7091"

    def test_domain(self):
        env = {"COMPOSE_PROFILES": "https", "DOCSGPT_DOMAIN": "docs.example.com"}
        assert stack.url(env, lan_ip="10.0.0.5") == "https://docs.example.com"

    def test_health_is_always_checked_on_this_machine(self):
        assert stack.health_url({"DOCSGPT_BIND": "0.0.0.0", "DOCSGPT_PORT": "9000"}) == "http://127.0.0.1:9000/api/health"


class TestToken:
    def test_matches_what_the_api_prints(self):
        """docsgpt/app.py signs {"sub": "local"} with JWT_SECRET_KEY for AUTH_TYPE=simple_jwt."""
        from jose import jwt

        token = stack.simple_jwt_token("s3cret")
        assert token == jwt.encode({"sub": "local"}, "s3cret", algorithm="HS256")
        assert jwt.decode(token, "s3cret", algorithms=["HS256"]) == {"sub": "local"}


class TestLocations:
    def test_the_stack_dir_is_never_the_checkout(self, monkeypatch, tmp_path):
        monkeypatch.delenv(paths.HOME_ENV, raising=False)
        monkeypatch.setattr(paths, "default_home", lambda: tmp_path / "home")
        assert stack.stack_dir(None) == tmp_path / "home"

    def test_docsgpt_home_and_then_an_explicit_dir_win(self, monkeypatch, tmp_path):
        monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "env-home"))
        assert stack.stack_dir(None) == (tmp_path / "env-home").resolve()
        assert stack.stack_dir(str(tmp_path / "flag")) == (tmp_path / "flag").resolve()

    def test_a_checkout_uses_the_deployment_compose_file(self):
        assert stack.compose_source() == REPO_ROOT / "deployment" / "docker-compose-standalone.yaml"

    def test_the_packaged_compose_file_wins(self, monkeypatch, tmp_path):
        packaged = tmp_path / "docsgpt" / "deploy" / "docker-compose.yaml"
        packaged.parent.mkdir(parents=True)
        packaged.write_text("name: docsgpt\n")
        monkeypatch.setattr(paths, "package_dir", lambda: tmp_path / "docsgpt")
        assert stack.compose_source() == packaged
