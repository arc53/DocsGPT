"""GitHub account lookups for the GitHub connector: who a token is, what it can read.

A connection signs in with a personal access token (``api_key``) or through
the GitHub App (``oauth``). A token lists the repositories it was granted;
an App sign-in lists the repositories of the App's installations the user
can see, which the user chooses on GitHub when installing the App.
"""

from __future__ import annotations

from typing import Optional

import requests

from docsgpt.connectors.service import TransientConnectionError

API_URL = "https://api.github.com"
_PAGE_SIZE = 100
# A picker, not an export: enough for any one person's list.
MAX_REPOSITORIES = 1000


class TokenRejected(ValueError):
    """GitHub answered 401: the token is wrong, expired or revoked."""


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get(url: str, token: str, params: Optional[dict] = None):
    """GET ``url`` as ``token`` and return its JSON.

    Raises:
        TokenRejected: 401.
        TransientConnectionError: Network trouble, rate limiting or a 5xx.
        ValueError: Any other refusal.
    """
    try:
        response = requests.get(url, headers=_headers(token), params=params, timeout=30)
    except requests.RequestException as exc:
        raise TransientConnectionError(f"GitHub did not answer: {type(exc).__name__}") from exc
    if response.status_code == 401:
        raise TokenRejected("GitHub did not accept this token.")
    if response.status_code == 429 or response.status_code >= 500 or (
        response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0"
    ):
        raise TransientConnectionError(f"GitHub is busy ({response.status_code}). Try again.")
    if response.status_code >= 400:
        raise ValueError(f"GitHub refused the request ({response.status_code}).")
    return response.json()


def token_account(token: Optional[str]) -> str:
    """The login of the account ``token`` belongs to.

    Raises:
        TokenRejected: No token, or GitHub did not accept it.
        TransientConnectionError: GitHub could not be reached.
    """
    if not token or not str(token).strip():
        raise TokenRejected("Paste a GitHub token.")
    user = _get(f"{API_URL}/user", str(token).strip())
    login = user.get("login") if isinstance(user, dict) else None
    if not login:
        raise TokenRejected("GitHub did not say whose token this is.")
    return str(login)


def _summary(repo: dict) -> dict:
    return {
        "full_name": repo.get("full_name"),
        "private": bool(repo.get("private")),
        "description": repo.get("description") or "",
        "default_branch": repo.get("default_branch") or "",
        "updated_at": repo.get("pushed_at") or repo.get("updated_at"),
        "html_url": repo.get("html_url") or "",
    }


def _paged(url: str, token: str, key: Optional[str] = None, params: Optional[dict] = None):
    """Every item of a paginated list endpoint, up to :data:`MAX_REPOSITORIES`."""
    page = 1
    fetched = 0
    while fetched < MAX_REPOSITORIES:
        payload = _get(url, token, {**(params or {}), "per_page": _PAGE_SIZE, "page": page})
        items = payload.get(key, []) if key else payload
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict):
                fetched += 1
                yield item
        if len(items) < _PAGE_SIZE:
            return
        page += 1


def list_repositories(token: str, *, app: bool) -> list[dict]:
    """Repositories ``token`` can read, most recently pushed first.

    Args:
        token: The connection's access token.
        app: Whether it is a GitHub App user token, whose repositories are
            those of the App's installations.

    Returns:
        ``{full_name, private, description, default_branch, updated_at,
        html_url}`` per repository.

    Raises:
        TokenRejected: GitHub did not accept the token.
        TransientConnectionError: GitHub could not be reached.
    """
    if app:
        raw = []
        for installation in _paged(f"{API_URL}/user/installations", token, "installations"):
            raw.extend(_paged(
                f"{API_URL}/user/installations/{installation.get('id')}/repositories", token, "repositories",
            ))
    else:
        raw = list(_paged(f"{API_URL}/user/repos", token, params={"sort": "pushed"}))
    seen: dict[str, dict] = {}
    for repo in raw:
        name = repo.get("full_name")
        if name and name not in seen:
            seen[name] = _summary(repo)
    return sorted(seen.values(), key=lambda r: r["updated_at"] or "", reverse=True)[:MAX_REPOSITORIES]
