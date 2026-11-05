"""MCP Apps (``io.modelcontextprotocol/ui``): interactive views an MCP server ships with its tools.

A tool names its view with ``_meta.ui.resourceUri``; the chat reads that
``ui://`` resource and renders it in a double iframe
(``frontend/src/conversation/McpAppView.tsx``). The outer frame is the
sandbox page served by ``/api/mcp_apps/sandbox`` on an origin other than the
app's, which writes the view into an inner frame under a CSP built only from
what the resource declares. These helpers are the contract both ends rely on:
which tool metadata is kept, who may call a tool, the sandbox's origin and CSP,
and the tool result the view is handed. Spec:
https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx
"""

from __future__ import annotations

import base64
import json
import re
from email.message import Message
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit

from docsgpt.core.settings import settings
from docsgpt.security.origins import normalize_origin

EXTENSION_ID = "io.modelcontextprotocol/ui"
APP_MIME_TYPE = "text/html;profile=mcp-app"
SANDBOX_PATH = "/api/mcp_apps/sandbox"
DEFAULT_VISIBILITY = ("model", "app")
# Ceiling on the tool result handed to a view; it is streamed and saved with the call.
APP_RESULT_MAX_CHARS = 200_000
# Ceiling on a view's HTML, which is cached and sent to the chat (Excalidraw's is ~430 KB).
VIEW_MAX_BYTES = 5_000_000

# A CSP source a resource may declare: an http(s)/ws(s) origin, a ``*.`` subdomain
# wildcard allowed, an optional path. Anything else (keywords, ``;``, spaces) could
# widen the policy, so it is dropped.
_CSP_SOURCE = re.compile(r"^(https?|wss?)://(\*\.)?[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*(:\d{1,5})?(/[^\s;,'\"]*)?$")
# Permission Policy features a resource may ask for (``_meta.ui.permissions``).
_PERMISSIONS = {
    "camera": "camera",
    "microphone": "microphone",
    "geolocation": "geolocation",
    "clipboardWrite": "clipboard-write",
}


def tool_ui_metadata(meta: Any) -> dict:
    """The UI part of a tool's ``_meta``: its view's ``resourceUri`` and its ``visibility``.

    Args:
        meta: The tool's wire ``_meta`` mapping.

    Returns:
        ``resourceUri`` when it is a ``ui://`` URI (the deprecated flat
        ``ui/resourceUri`` too) and ``visibility`` when set; a malformed
        visibility becomes ``[]``, so the tool is offered to no one.
    """
    if not isinstance(meta, dict):
        return {}
    ui = meta.get("ui") if isinstance(meta.get("ui"), dict) else {}
    kept: dict = {}
    uri = ui.get("resourceUri") or meta.get("ui/resourceUri")
    if isinstance(uri, str) and uri.startswith("ui://"):
        kept["resourceUri"] = uri
    if "visibility" in ui:
        visibility = ui["visibility"]
        valid = isinstance(visibility, list) and all(isinstance(v, str) for v in visibility)
        kept["visibility"] = list(visibility) if valid else []
    return kept


def _visibility(action: dict) -> tuple:
    ui = action.get("ui") if isinstance(action.get("ui"), dict) else {}
    if "visibility" not in ui:
        return DEFAULT_VISIBILITY
    visibility = ui["visibility"]
    return tuple(visibility) if isinstance(visibility, list) else ()


def visible_to_model(action: dict) -> bool:
    """Whether the model may be offered and call ``action``."""
    return "model" in _visibility(action)


def visible_to_app(action: dict) -> bool:
    """Whether a view may call ``action`` through the chat."""
    return "app" in _visibility(action)


def resource_uri(action: dict) -> Optional[str]:
    """The ``ui://`` view ``action`` renders, if any."""
    ui = action.get("ui") if isinstance(action.get("ui"), dict) else {}
    uri = ui.get("resourceUri")
    return uri if isinstance(uri, str) and uri.startswith("ui://") else None


def is_app_mime_type(mime_type: Optional[str]) -> bool:
    """Whether ``mime_type`` is ``text/html;profile=mcp-app``, in any parameter spelling."""
    if not mime_type:
        return False
    message = Message()
    message["content-type"] = re.sub(r"\s*=\s*", "=", mime_type)
    profile = message.get_param("profile")
    return message.get_content_type() == "text/html" and isinstance(profile, str) and profile.lower() == "mcp-app"


def _reaches(source: str, hosts: set[str]) -> bool:
    """Whether a CSP source would allow any of ``hosts``, by name or ``*.`` wildcard, whatever its scheme or port."""
    host = (urlsplit(source).hostname or "").lower()
    if host.startswith("*."):
        return any(h.endswith(host[1:]) for h in hosts)
    return host in hosts


def _sources(domains: Any, own_hosts: set[str] = frozenset()) -> list[str]:
    if not isinstance(domains, list):
        return []
    return [d for d in domains if isinstance(d, str) and _CSP_SOURCE.match(d) and not _reaches(d, own_hosts)]


def build_csp(csp: Optional[dict], frame_ancestors: Iterable[str], sandbox_origin: Optional[str] = None) -> str:
    """The sandbox page's Content-Security-Policy, which the view's frame inherits.

    Only the domains the resource declares in ``_meta.ui.csp`` are allowed;
    without them the view reaches nothing. A declared domain that would
    reach the sandbox's own origin (this API) or one of the app's is
    dropped: the view has no business calling either.

    Args:
        csp: The resource's ``_meta.ui.csp``.
        frame_ancestors: The app origins allowed to embed the sandbox.
        sandbox_origin: The sandbox page's own origin.

    Returns:
        The header value.
    """
    csp = csp if isinstance(csp, dict) else {}
    ancestor_origins = [o for o in (normalize_origin(a) for a in frame_ancestors) if o]
    own_hosts = {
        (urlsplit(o).hostname or "").lower() for o in (*ancestor_origins, normalize_origin(sandbox_origin)) if o
    }
    resources = " ".join(_sources(csp.get("resourceDomains"), own_hosts))
    connect = " ".join(_sources(csp.get("connectDomains"), own_hosts)) or "'none'"
    frames = " ".join(_sources(csp.get("frameDomains"), own_hosts)) or "'none'"
    base = " ".join(_sources(csp.get("baseUriDomains"), own_hosts)) or "'self'"
    ancestors = " ".join(ancestor_origins) or "'none'"
    directives = [
        "default-src 'none'",
        f"script-src 'unsafe-inline' 'unsafe-eval' blob: data: {resources}",
        f"style-src 'unsafe-inline' blob: data: {resources}",
        f"img-src data: blob: {resources}",
        f"font-src data: blob: {resources}",
        f"media-src data: blob: {resources}",
        f"worker-src blob: {resources}",
        f"connect-src {connect}",
        f"frame-src {frames}",
        "object-src 'none'",
        f"base-uri {base}",
        f"frame-ancestors {ancestors}",
    ]
    return "; ".join(directive.strip() for directive in directives)


def allow_attribute(permissions: Any) -> str:
    """The inner frame's ``allow`` attribute for a resource's ``_meta.ui.permissions``."""
    if not isinstance(permissions, dict):
        return ""
    return "; ".join(feature for key, feature in sorted(_PERMISSIONS.items()) if key in permissions)


def _app_origins() -> list[str]:
    # Lazy: the API package is not an import of the agents layer.
    from docsgpt.api.agent_origins import trusted_origins

    return trusted_origins()


def sandbox_url() -> Optional[str]:
    """Where the app loads the sandbox page, or None when there is no usable sandbox origin.

    ``MCP_APPS_SANDBOX_URL`` when set; on a loopback ``API_URL`` the other
    loopback name, a different origin for the browser. A sandbox on one of the
    app's own origins is refused: the view's code would run where the
    session lives.
    """
    configured = (settings.MCP_APPS_SANDBOX_URL or "").strip()
    if configured:
        url = configured
    else:
        try:
            api = urlsplit(settings.API_URL or "")
            port = f":{api.port}" if api.port else ""
        except ValueError:
            return None
        other = {"localhost": "127.0.0.1", "127.0.0.1": "localhost"}.get(api.hostname or "")
        if not other:
            return None
        url = f"{api.scheme}://{other}{port}{SANDBOX_PATH}"
    origin = normalize_origin(url)
    if not origin or origin in _app_origins():
        return None
    return url


def enabled() -> bool:
    """Whether MCP Apps render: switched on and with a sandbox origin."""
    return bool(settings.MCP_APPS_ENABLED) and sandbox_url() is not None


def host_origins() -> list[str]:
    """The app origins the sandbox page accepts as its parent."""
    sandbox = normalize_origin(sandbox_url())
    return [origin for origin in _app_origins() if origin != sandbox]


def _field(item: Any, key: str, attribute: str) -> Any:
    return item.get(key) if isinstance(item, dict) else getattr(item, attribute, None)


def _app_item(contents: Iterable[Any]) -> Any:
    """The first ``text/html;profile=mcp-app`` item of a ``resources/read`` answer, or None."""
    for item in contents or []:
        if is_app_mime_type(_field(item, "mimeType", "mime_type")):
            return item
    return None


def _item_ui(item: Any) -> Optional[dict]:
    meta = _field(item, "_meta", "meta")
    ui = meta.get("ui") if isinstance(meta, dict) else None
    return ui if isinstance(ui, dict) else None


def declares_ui(contents: Iterable[Any]) -> bool:
    """Whether the view item of a ``resources/read`` answer carries its own ``_meta.ui``.

    When it doesn't, the ``csp`` and ``permissions`` may be on the
    resource's ``resources/list`` entry instead.
    """
    item = _app_item(contents)
    return item is not None and _item_ui(item) is not None


def resource_view(contents: Iterable[Any], listing_meta: Any) -> dict:
    """A ``resources/read`` answer as the view the chat renders.

    Args:
        contents: The read's contents; the first ``text/html;profile=mcp-app`` one is used.
        listing_meta: The resource's ``_meta`` from ``resources/list``, used when
            the view item carries no ``_meta.ui``.

    Returns:
        ``html`` plus ``csp``, ``permissions`` and ``prefersBorder`` when declared.

    Raises:
        ValueError: No contents are an MCP App, or its HTML is over ``VIEW_MAX_BYTES``.
    """
    item = _app_item(contents)
    if item is None:
        raise ValueError("The resource is not an MCP App (text/html;profile=mcp-app)")
    too_large = ValueError(f"The view is too large (over {VIEW_MAX_BYTES} bytes)")
    text = _field(item, "text", "text")
    if text is None:
        blob = _field(item, "blob", "blob") or ""
        # Checked before decoding: base64 is 4 characters per 3 bytes, less the padding.
        if len(blob.rstrip("=")) * 3 // 4 > VIEW_MAX_BYTES:
            raise too_large
        text = base64.b64decode(blob).decode("utf-8")
    if len(text.encode("utf-8")) > VIEW_MAX_BYTES:
        raise too_large
    ui = _item_ui(item)
    if ui is None:
        listed = listing_meta.get("ui") if isinstance(listing_meta, dict) else None
        ui = listed if isinstance(listed, dict) else {}
    view: dict = {"html": text}
    for key in ("csp", "permissions"):
        if isinstance(ui.get(key), dict):
            view[key] = ui[key]
    if isinstance(ui.get("prefersBorder"), bool):
        view["prefersBorder"] = ui["prefersBorder"]
    return view


def _dump(item: Any) -> Any:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(by_alias=True, mode="json", exclude_none=True)
    return {"type": "text", "text": str(item)}


def app_result(result: Any) -> dict:
    """A tool's ``CallToolResult`` as the view is handed it (``ui/notifications/tool-result``).

    Unlike the model's copy it keeps ``structuredContent``. Over
    ``APP_RESULT_MAX_CHARS`` the content goes first, then the structured
    content.
    """
    if isinstance(result, dict):
        content = result.get("content") or []
        structured = result.get("structuredContent")
        is_error = bool(result.get("isError"))
    else:
        content = getattr(result, "content", None) or []
        structured = getattr(result, "structured_content", None)
        # FastMCP's client result names it ``is_error``; the MCP type ``isError``.
        is_error = getattr(result, "is_error", None)
        if not isinstance(is_error, bool):
            is_error = bool(getattr(result, "isError", False))
    projected: dict = {"content": [_dump(item) for item in content]}
    if structured is not None:
        projected["structuredContent"] = structured
    projected["isError"] = is_error
    for key in ("content", "structuredContent"):
        if len(json.dumps(projected, default=str)) <= APP_RESULT_MAX_CHARS:
            break
        if key == "content":
            projected["content"] = []
        else:
            projected.pop("structuredContent", None)
    return projected


_SANDBOX_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<title>MCP App sandbox</title>
<style>
html, body { margin: 0; height: 100%; width: 100%; background: transparent; }
body { display: flex; flex-direction: column; }
iframe { flex-grow: 1; width: 100%; border: 0; background: transparent; color-scheme: inherit; }
</style>
</head>
<body>
<script>
(function () {
  "use strict";
  var HOSTS = __HOSTS__;
  var PERMISSIONS = __PERMISSIONS__;
  if (window.self === window.top) return;
  var ancestors = window.location.ancestorOrigins;
  var host = ancestors && ancestors.length ? ancestors[0] : null;
  if (!host) {
    try { host = new URL(document.referrer).origin; } catch (e) { return; }
  }
  if (HOSTS.indexOf(host) === -1) return;
  var own = window.location.origin;
  var inner = null;
  window.addEventListener("message", function (event) {
    var data = event.data;
    if (event.source === window.parent) {
      if (event.origin !== host || !data || typeof data !== "object") return;
      var method = typeof data.method === "string" ? data.method : "";
      if (method === "ui/notifications/sandbox-resource-ready") {
        if (inner) return;
        var params = data.params || {};
        if (typeof params.html !== "string") return;
        var allow = [];
        var asked = params.permissions || {};
        Object.keys(PERMISSIONS).forEach(function (key) {
          if (Object.prototype.hasOwnProperty.call(asked, key)) allow.push(PERMISSIONS[key]);
        });
        inner = document.createElement("iframe");
        inner.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms");
        if (allow.length) inner.setAttribute("allow", allow.join("; "));
        document.body.appendChild(inner);
        var doc = inner.contentDocument;
        doc.open();
        doc.write(params.html);
        doc.close();
      } else if (method.indexOf("ui/notifications/sandbox-") !== 0 && inner && inner.contentWindow) {
        inner.contentWindow.postMessage(data, own);
      }
    } else if (inner && event.source === inner.contentWindow) {
      if (event.origin !== own) return;
      window.parent.postMessage(data, host);
    }
  });
  window.parent.postMessage({ jsonrpc: "2.0", method: "ui/notifications/sandbox-proxy-ready", params: {} }, host);
})();
</script>
</body>
</html>
"""


def _script_json(value: Any) -> str:
    # ``<`` escaped so no value can close the script element.
    return json.dumps(value).replace("<", "\\u003c")


def sandbox_page(hosts: Iterable[str]) -> str:
    """The sandbox proxy page: it accepts its view only from ``hosts`` and relays messages both ways.

    Args:
        hosts: The app origins allowed as its parent.

    Returns:
        The HTML.
    """
    permissions = {key: feature for key, feature in sorted(_PERMISSIONS.items())}
    return _SANDBOX_PAGE.replace("__HOSTS__", _script_json(list(hosts))).replace(
        "__PERMISSIONS__", _script_json(permissions)
    )
