import stat

import pytest


def test_configured_secret_is_used_without_touching_the_filesystem(tmp_path):
    from docsgpt.core.secret_key import resolve_jwt_secret_key

    key_file = tmp_path / "missing" / "jwt-secret"

    assert (
        resolve_jwt_secret_key("configured-secret", None, key_file)
        == "configured-secret"
    )
    assert not key_file.exists()


def test_cloud_deployment_requires_an_explicit_shared_secret(tmp_path):
    from docsgpt.core.secret_key import resolve_jwt_secret_key

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY must be set"):
        resolve_jwt_secret_key("", "cloud", tmp_path / "jwt-secret")


def test_local_secret_is_created_once_with_owner_only_permissions(tmp_path):
    from docsgpt.core.secret_key import resolve_jwt_secret_key

    key_file = tmp_path / "jwt-secret"

    first = resolve_jwt_secret_key("", None, key_file)
    second = resolve_jwt_secret_key("", None, key_file)

    assert second == first
    assert key_file.read_text(encoding="utf-8") == first
    assert len(first) == 64
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_local_secret_lives_in_the_data_home_not_the_working_directory(tmp_path, monkeypatch):
    """A pip install runs from any directory; its key must not follow the CWD."""
    from docsgpt.core.secret_key import resolve_jwt_secret_key

    home = tmp_path / "home"
    workdir = tmp_path / "somewhere"
    workdir.mkdir()
    monkeypatch.setenv("DOCSGPT_HOME", str(home))
    monkeypatch.chdir(workdir)

    secret = resolve_jwt_secret_key("", None)

    assert (home / ".jwt_secret_key").read_text(encoding="utf-8") == secret
    assert not (workdir / ".jwt_secret_key").exists()
    assert resolve_jwt_secret_key("", None) == secret


def test_a_key_left_in_the_working_directory_by_an_older_version_is_kept(tmp_path, monkeypatch):
    """Tokens signed with it stay valid: it is moved into the data home rather than replaced."""
    from docsgpt.core.secret_key import resolve_jwt_secret_key

    home = tmp_path / "home"
    workdir = tmp_path / "somewhere"
    workdir.mkdir()
    (workdir / ".jwt_secret_key").write_text("legacy-secret\n", encoding="utf-8")
    monkeypatch.setenv("DOCSGPT_HOME", str(home))
    monkeypatch.chdir(workdir)

    assert resolve_jwt_secret_key("", None) == "legacy-secret"
    assert (home / ".jwt_secret_key").read_text(encoding="utf-8") == "legacy-secret"
    assert stat.S_IMODE((home / ".jwt_secret_key").stat().st_mode) == 0o600


def test_the_data_home_key_wins_over_a_stray_working_directory_key(tmp_path, monkeypatch):
    from docsgpt.core.secret_key import resolve_jwt_secret_key

    home = tmp_path / "home"
    home.mkdir()
    (home / ".jwt_secret_key").write_text("home-secret", encoding="utf-8")
    workdir = tmp_path / "somewhere"
    workdir.mkdir()
    (workdir / ".jwt_secret_key").write_text("stray-secret", encoding="utf-8")
    monkeypatch.setenv("DOCSGPT_HOME", str(home))
    monkeypatch.chdir(workdir)

    assert resolve_jwt_secret_key("", None) == "home-secret"
