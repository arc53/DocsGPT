"""Pluggable code-execution sandbox abstraction for running untrusted LLM code."""


def sandbox_configured() -> bool:
    """Whether the selected sandbox backend has what it needs to run code.

    Only reads settings; nothing is contacted. Daytona needs an API key and
    the Jupyter runner a gateway URL. The chat attachment planner offers
    files to the code execution tool only when this holds, so a tool that
    would fail on every call is never named as the way to read a file.

    Returns:
        True when the configured backend can be used.
    """
    from docsgpt.core.settings import settings

    backend = (settings.SANDBOX_BACKEND or "").lower()
    if backend == "daytona":
        return bool(settings.DAYTONA_API_KEY)
    if backend == "jupyter":
        return bool((settings.SANDBOX_GATEWAY_URL or "").strip())
    return False
