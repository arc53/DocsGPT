import stat

import pytest


def test_configured_secret_is_used_without_touching_the_filesystem(tmp_path):
    from application.core.secret_key import resolve_jwt_secret_key

    key_file = tmp_path / "missing" / "jwt-secret"

    assert (
        resolve_jwt_secret_key("configured-secret", None, key_file)
        == "configured-secret"
    )
    assert not key_file.exists()


def test_cloud_deployment_requires_an_explicit_shared_secret(tmp_path):
    from application.core.secret_key import resolve_jwt_secret_key

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY must be set"):
        resolve_jwt_secret_key("", "cloud", tmp_path / "jwt-secret")


def test_local_secret_is_created_once_with_owner_only_permissions(tmp_path):
    from application.core.secret_key import resolve_jwt_secret_key

    key_file = tmp_path / "jwt-secret"

    first = resolve_jwt_secret_key("", None, key_file)
    second = resolve_jwt_secret_key("", None, key_file)

    assert second == first
    assert key_file.read_text(encoding="utf-8") == first
    assert len(first) == 64
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
