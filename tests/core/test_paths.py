"""Data home and .env discovery (docsgpt.core.paths)."""

from pathlib import Path

import pytest

from docsgpt.core import paths

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestHomeDir:
    def test_the_checkout_wins_over_cwd(self, monkeypatch, tmp_path):
        monkeypatch.delenv(paths.HOME_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        assert paths.checkout_root() == REPO_ROOT
        assert paths.home_dir() == REPO_ROOT

    def test_the_env_var_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv(paths.HOME_ENV, str(tmp_path))
        assert paths.home_dir() == tmp_path.resolve()

    def test_an_installed_package_falls_back_to_cwd(self, monkeypatch, tmp_path):
        monkeypatch.delenv(paths.HOME_ENV, raising=False)
        monkeypatch.setattr(paths, "checkout_root", lambda: None)
        monkeypatch.chdir(tmp_path)
        assert paths.home_dir() == Path.cwd()


class TestEnvFile:
    def test_default_is_dot_env_in_the_home(self, monkeypatch, tmp_path):
        monkeypatch.delenv(paths.ENV_FILE_ENV, raising=False)
        monkeypatch.setenv(paths.HOME_ENV, str(tmp_path))
        assert paths.env_file() == tmp_path.resolve() / ".env"

    def test_the_env_var_wins(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.env"
        custom.write_text("LLM_NAME=x\n")
        monkeypatch.setenv(paths.ENV_FILE_ENV, str(custom))
        assert paths.env_file() == custom

    def test_a_missing_configured_file_is_an_error(self, monkeypatch, tmp_path):
        """Booting with every default because of a typo in the path must not be silent."""
        monkeypatch.setenv(paths.ENV_FILE_ENV, str(tmp_path / "nope.env"))
        with pytest.raises(FileNotFoundError, match="DOCSGPT_ENV_FILE"):
            paths.env_file()


class TestSettingsFollowTheHome:
    def test_embedded_vector_stores_default_under_the_home(self, monkeypatch, tmp_path):
        from docsgpt.core.settings import Settings

        monkeypatch.setenv(paths.HOME_ENV, str(tmp_path))
        monkeypatch.delenv("MILVUS_URI", raising=False)
        monkeypatch.delenv("LANCEDB_PATH", raising=False)
        fresh = Settings(_env_file=None)
        assert fresh.MILVUS_URI == str(tmp_path.resolve() / "milvus_local.db")
        assert fresh.LANCEDB_PATH == str(tmp_path.resolve() / "data" / "lancedb")

    def test_env_overrides_still_win(self, monkeypatch, tmp_path):
        from docsgpt.core.settings import Settings

        monkeypatch.setenv(paths.HOME_ENV, str(tmp_path))
        monkeypatch.setenv("LANCEDB_PATH", "/srv/lancedb")
        assert Settings(_env_file=None).LANCEDB_PATH == "/srv/lancedb"


class TestPackageDir:
    def test_holds_the_shipped_data(self):
        assert paths.package_dir().name == "docsgpt"
        assert (paths.package_dir() / "alembic.ini").is_file()
        assert (paths.package_dir() / "prompts" / "chat_reduce_prompt.txt").is_file()
