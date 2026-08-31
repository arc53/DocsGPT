"""Resolve stable application signing secrets for local and production use."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


_SHARED_SECRET_DEPLOYMENTS = {"cloud", "production"}


def _read_secret_file(key_path: Path) -> str:
    """Read and validate a generated local signing secret."""
    secret = key_path.read_text(encoding="utf-8").strip()
    if not secret:
        raise RuntimeError(f"Signing secret file is empty: {key_path}")
    return secret


def _create_secret_file_atomically(key_path: Path) -> str:
    """Create a complete mode-0600 secret before atomically publishing it."""
    new_secret = os.urandom(32).hex()
    descriptor, temporary_name = tempfile.mkstemp(
        dir=key_path.parent,
        prefix=f".{key_path.name}.",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            descriptor = -1
            temporary_file.write(new_secret)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        try:
            # A hard link publishes the fully written file without replacing a
            # secret another process may have won the race to create.
            os.link(temporary_path, key_path)
        except FileExistsError:
            return _read_secret_file(key_path)
        return new_secret
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def resolve_jwt_secret_key(
    configured_secret: str | None,
    deployment_type: str | None,
    key_file: str | Path = ".jwt_secret_key",
) -> str:
    """Return a shared configured secret or a stable local-development secret.

    Args:
        configured_secret: Operator-supplied signing secret.
        deployment_type: Deployment class, such as ``cloud`` or ``production``.
        key_file: Local fallback file used outside production deployments.

    Returns:
        The configured or locally persisted signing secret.

    Raises:
        RuntimeError: If production lacks a shared secret or local persistence fails.
    """
    if configured_secret and configured_secret.strip():
        return configured_secret

    normalized_deployment = (deployment_type or "").strip().lower()
    if normalized_deployment in _SHARED_SECRET_DEPLOYMENTS:
        raise RuntimeError(
            "JWT_SECRET_KEY must be set to the same strong random value on every "
            f"{normalized_deployment} API and worker replica"
        )

    key_path = Path(key_file)
    try:
        return _read_secret_file(key_path)
    except FileNotFoundError:
        try:
            return _create_secret_file_atomically(key_path)
        except Exception as exc:
            raise RuntimeError(f"Failed to create signing secret: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to read signing secret: {exc}") from exc
