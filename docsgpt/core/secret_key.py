"""Resolve stable application signing secrets for local and production use."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from docsgpt.core import paths

_SHARED_SECRET_DEPLOYMENTS = {"cloud", "production"}
KEY_FILE_NAME = ".jwt_secret_key"


def _read_secret_file(key_path: Path) -> str:
    """Read and validate a generated local signing secret."""
    secret = key_path.read_text(encoding="utf-8").strip()
    if not secret:
        raise RuntimeError(f"Signing secret file is empty: {key_path}")
    return secret


def _create_secret_file_atomically(key_path: Path, new_secret: str | None = None) -> str:
    """Create a complete mode-0600 secret before atomically publishing it.

    Args:
        key_path: Where the secret is published.
        new_secret: The value to write; a random one when omitted.

    Returns:
        The secret now in ``key_path``: this one, or the one another process published first.
    """
    new_secret = new_secret or os.urandom(32).hex()
    key_path.parent.mkdir(parents=True, exist_ok=True)
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


def _legacy_secret(key_path: Path) -> str | None:
    """A key an older version left in the working directory, copied into ``key_path``.

    Older versions wrote the fallback key relative to the working directory. Keeping
    it means tokens and avatar URLs signed with it stay valid after an upgrade. The
    old file is left where it is; an empty one is ignored.

    Args:
        key_path: Where the key file belongs now, under the data home.

    Returns:
        The legacy secret (copied into ``key_path`` when that is writable), or ``None``
        when there is no legacy file, it is empty, or it is ``key_path`` itself.
    """
    legacy_path = Path.cwd() / KEY_FILE_NAME
    if legacy_path.resolve() == key_path.resolve() or not legacy_path.is_file():
        return None
    secret = legacy_path.read_text(encoding="utf-8").strip()
    if not secret:
        return None
    try:
        return _create_secret_file_atomically(key_path, secret)
    except OSError:
        # A read-only data home still runs on the old file.
        return secret


def resolve_jwt_secret_key(
    configured_secret: str | None,
    deployment_type: str | None,
    key_file: str | Path | None = None,
) -> str:
    """Return a shared configured secret or a stable local-development secret.

    Args:
        configured_secret: Operator-supplied signing secret.
        deployment_type: Deployment class, such as ``cloud`` or ``production``.
        key_file: Local fallback file used outside production deployments. Defaults to
            ``.jwt_secret_key`` in the data home (``DOCSGPT_HOME``, the checkout, or
            ``~/.docsgpt/server``); a key an older version wrote to the working
            directory is copied there.

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

    key_path = Path(key_file) if key_file is not None else paths.home_dir() / KEY_FILE_NAME
    try:
        return _read_secret_file(key_path)
    except FileNotFoundError:
        try:
            if key_file is None:
                legacy = _legacy_secret(key_path)
                if legacy is not None:
                    return legacy
            return _create_secret_file_atomically(key_path)
        except Exception as exc:
            raise RuntimeError(f"Failed to create signing secret: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to read signing secret: {exc}") from exc
