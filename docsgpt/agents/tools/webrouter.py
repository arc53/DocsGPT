import logging
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from docsgpt.agents.tools.base import Tool

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_SEARCH_RESULTS = 20
MAX_URLS = 5
MAX_SNIPPET_CHARS = 500
DEFAULT_MAX_CHARS = 20000


class WebRouterTool(Tool):
    """
    WebRouter
    Web search and page reading through WebRouter, which sends each call to one of several providers and falls back
    to the next if it fails. Works without an API key; an optional provider key adds that provider.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the tool from its configuration.

        Args:
            config: Tool configuration with an optional ``provider``, ``token`` and ``timeout``.
        """
        self.config = config
        self.provider = (config.get("provider") or "").strip().lower() or None
        self.token = (config.get("token") or "").strip()
        self.timeout = float(config.get("timeout") or DEFAULT_TIMEOUT)

    def _router(self) -> Any:
        """Build a WebRouter client for one call.

        Returns:
            A ``web_router.WebRouter``, which the caller closes.
        """
        from web_router import WebRouter

        provider_config = {self.provider: {"api_key": self.token}} if self.provider and self.token else None
        return WebRouter(provider_config=provider_config)

    def _config_error(self) -> Optional[str]:
        """Return a message when the key is set without the provider it belongs to.

        Returns:
            The message, or ``None`` when the configuration is usable.
        """
        if self.token and not self.provider:
            return "An API key is set without a provider. Set the provider the key belongs to, or remove the key."
        return None

    def execute_action(self, action_name: str, **kwargs: Any) -> Dict[str, Any]:
        """Run one of the tool's actions.

        Args:
            action_name: ``webrouter_web_search`` or ``webrouter_read_pages``.
            **kwargs: Arguments for the action.

        Returns:
            The action's result dict.

        Raises:
            ValueError: If the action name is unknown.
        """
        actions = {
            "webrouter_web_search": self._web_search,
            "webrouter_read_pages": self._read_pages,
        }
        if action_name not in actions:
            raise ValueError(f"Unknown action: {action_name}")
        return actions[action_name](**kwargs)

    def _web_search(
        self,
        query: str,
        max_results: int = 5,
        include_domains: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Search the web.

        Args:
            query: The search query.
            max_results: Number of results, clamped to 1-20.
            include_domains: Optional domains to restrict results to.

        Returns:
            A dict with ``status_code``, ``results``, ``provider`` and ``message``.
        """
        logger.debug("WebRouter web search for: %s", query)
        error = self._config_error()
        if error:
            return {"status_code": 400, "results": [], "message": error}
        if not isinstance(query, str) or not query.strip():
            return {"status_code": 400, "results": [], "message": "A non-empty query is required."}
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = 5
        domains = [d.strip() for d in include_domains or [] if isinstance(d, str) and d.strip()] or None

        from web_router import WebRouterError

        try:
            with self._router() as router:
                response = router.search(
                    query.strip(),
                    provider=self.provider,
                    max_results=max(1, min(max_results, MAX_SEARCH_RESULTS)),
                    include_domains=domains,
                    timeout=self.timeout,
                    data_apis=False,
                )
        except WebRouterError as e:
            logger.warning("WebRouter web search failed: %s", e)
            return {"status_code": 500, "results": [], "message": f"Web search failed: {e}"}

        results = [
            {
                "title": result.title,
                "url": result.url,
                "snippet": (result.description or result.content)[:MAX_SNIPPET_CHARS],
                "published_date": result.published_date,
            }
            for result in response.results
        ]
        return {
            "status_code": 200,
            "results": results,
            "provider": response.provider,
            "message": "Web search completed successfully.",
        }

    def _read_pages(
        self,
        urls: Union[str, List[str]],
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> Dict[str, Any]:
        """Read one or more web pages as markdown.

        The pages are fetched by the extraction provider on its servers, not by DocsGPT.

        Args:
            urls: One URL or a list of up to five http(s) URLs.
            max_chars: Maximum characters kept from each page, at least 1.

        Returns:
            A dict with ``status_code``, ``results`` (one per page read), ``failures`` (URLs not read and why),
            ``provider`` and ``message``.
        """
        error = self._config_error()
        if error:
            return {"status_code": 400, "results": [], "failures": [], "message": error}
        if isinstance(urls, str):
            urls = [urls]
        urls = [u.strip() for u in urls or [] if isinstance(u, str) and u.strip()]
        if not urls:
            return {"status_code": 400, "results": [], "failures": [], "message": "At least one URL is required."}
        if len(urls) > MAX_URLS:
            return {
                "status_code": 400,
                "results": [],
                "failures": [],
                "message": f"At most {MAX_URLS} URLs can be read in one call.",
            }
        refused = [{"url": u, "error": "Only http and https URLs can be read."} for u in urls if not _is_http(u)]
        allowed = [u for u in urls if _is_http(u)]
        if not allowed:
            return {"status_code": 400, "results": [], "failures": refused, "message": "No readable URLs."}
        try:
            max_chars = max(1, int(max_chars))
        except (TypeError, ValueError):
            max_chars = DEFAULT_MAX_CHARS
        logger.debug("WebRouter reading %d page(s)", len(allowed))

        from web_router import WebRouterError

        try:
            with self._router() as router:
                response = router.extract(allowed, provider=self.provider, timeout=self.timeout, data_apis=False)
        except WebRouterError as e:
            logger.warning("WebRouter page read failed: %s", e)
            failures = refused + [{"url": u, "error": str(e)} for u in allowed]
            return {"status_code": 500, "results": [], "failures": failures, "message": f"Reading failed: {e}"}

        results = [
            {
                "url": doc.url,
                "title": doc.title,
                "content": doc.content[:max_chars],
                "truncated": len(doc.content) > max_chars,
            }
            for doc in response.documents
        ]
        failures = refused + [{"url": f.url, "error": f.error} for f in response.failures]
        return {
            "status_code": 200,
            "results": results,
            "failures": failures,
            "provider": response.provider,
            "message": f"Read {len(results)} of {len(urls)} page(s).",
        }

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """Describe the tool's actions for the model.

        Returns:
            The action metadata list.
        """
        return [
            {
                "name": "webrouter_web_search",
                "access": "read",
                "description": (
                    "Search the web. Returns result titles, URLs, snippets and publish dates when known. "
                    "Use it for current events or information not found in the user's documents."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results (default: 5, max: 20)",
                        },
                        "include_domains": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Only return results from these domains, e.g. ['docs.python.org']",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "webrouter_read_pages",
                "access": "read",
                "description": (
                    "Read the full text of one to five web pages as markdown, for example the pages behind "
                    "search results. URLs that could not be read are listed with the reason."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "The http(s) URLs to read (max 5)",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": f"Maximum characters kept from each page (default: {DEFAULT_MAX_CHARS})",
                        },
                    },
                    "required": ["urls"],
                    "additionalProperties": False,
                },
            },
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        """Describe the tool's optional configuration.

        Returns:
            The configuration fields.
        """
        return {
            "provider": {
                "type": "string",
                "label": "Provider",
                "description": "Optional, e.g. tavily or exa. Leave empty to route and fall back automatically",
                "required": False,
                "order": 1,
            },
            "token": {
                "type": "string",
                "label": "Provider API Key",
                "description": "Optional key for the provider above. Without one, keyless tiers are used",
                "required": False,
                "secret": True,
                "order": 2,
            },
        }


def _is_http(url: str) -> bool:
    """Return whether ``url`` is an absolute http(s) URL with a host.

    Args:
        url: The URL to check.

    Returns:
        ``True`` for an http(s) URL with a host.
    """
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)
