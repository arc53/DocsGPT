"""Serve the built web UI from the API process.

The wheel ships the frontend build under ``docsgpt/static`` (produced by
``scripts/build_frontend.sh``). When that directory holds an ``index.html``
and ``SERVE_UI`` is on, the ASGI shell puts :class:`StaticUI` in front of
Flask: files are served as they are, paths that belong to the backend pass
through, and every other GET renders ``index.html`` for the client-side
router. ``/config.js`` is generated per request so the UI talks to the origin
it was loaded from, the same mechanism the nginx image uses.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Optional

from starlette.responses import FileResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from docsgpt.core.paths import package_dir

logger = logging.getLogger(__name__)

# Runtime values the page reads before the bundle loads. These default to the
# origin the page came from; a VITE_* variable in the process environment
# wins, so a deployment can still point the UI somewhere else.
_ORIGIN_KEYS = ("VITE_API_HOST", "VITE_BASE_URL")

# Types Python's mimetypes table may not know.
_MEDIA_TYPES = {".woff2": "font/woff2", ".woff": "font/woff", ".webmanifest": "application/manifest+json"}

_IMMUTABLE = "public, max-age=31536000, immutable"
_NO_CACHE = "no-cache"


def config_js(environ: Optional[Mapping[str, str]] = None) -> str:
    """The ``/config.js`` body: ``window.__DOCSGPT_ENV__`` from the VITE_* environment."""
    env = os.environ if environ is None else environ
    values = {key: value for key, value in env.items() if key.startswith("VITE_") and value}
    entries = [f"{json.dumps(key)}:window.location.origin" for key in _ORIGIN_KEYS if key not in values]
    entries += [f"{json.dumps(key)}:{json.dumps(value)}" for key, value in sorted(values.items())]
    return "window.__DOCSGPT_ENV__={" + ",".join(entries) + "};\n"


class StaticUI:
    """ASGI app: the built UI in front of the backend."""

    def __init__(self, static_dir: Path, backend: ASGIApp, backend_prefixes: Iterable[str]) -> None:
        self.static_dir = Path(static_dir).resolve()
        self.index = self.static_dir / "index.html"
        self.backend = backend
        self.backend_prefixes = frozenset(backend_prefixes)

    @classmethod
    def wrap(cls, backend: ASGIApp, url_map, static_dir: Optional[Path] = None, enabled: bool = True) -> ASGIApp:
        """``backend`` alone when there is no UI to serve (or it is switched off), else the UI in front of it.

        The backend's path prefixes come from Flask's URL map, so a new
        blueprint never needs registering here: any first path segment Flask
        routes stays Flask's, everything else is the UI's.
        """
        static_dir = Path(static_dir) if static_dir is not None else package_dir() / "static"
        if not enabled or not (static_dir / "index.html").is_file():
            return backend
        prefixes = {rule.rule.split("/")[1] for rule in url_map.iter_rules() if rule.rule != "/"}
        logger.info("Serving the web UI from %s", static_dir)
        return cls(static_dir, backend, prefixes)

    def _file(self, path: str) -> Optional[Path]:
        """The file under the static directory for ``path``, or None (never a path outside it)."""
        relative = path.lstrip("/")
        if not relative:
            return None
        try:
            resolved = (self.static_dir / relative).resolve()
        except OSError:
            return None
        if self.static_dir not in resolved.parents:
            return None
        return resolved if resolved.is_file() else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("GET", "HEAD"):
            await self.backend(scope, receive, send)
            return
        path = scope["path"]
        root = scope.get("root_path", "")
        if root and path.startswith(root):
            path = path[len(root):] or "/"
        if path == "/config.js":
            response = Response(config_js(), media_type="application/javascript", headers={"Cache-Control": "no-store"})
            await response(scope, receive, send)
            return
        first = path.split("/")[1] if len(path) > 1 else ""
        if first in self.backend_prefixes:
            await self.backend(scope, receive, send)
            return
        file = self._file(path)
        if file is None:
            file, cache = self.index, _NO_CACHE
        else:
            cache = _IMMUTABLE if first == "assets" else _NO_CACHE
        response = FileResponse(file, media_type=_MEDIA_TYPES.get(file.suffix), headers={"Cache-Control": cache})
        await response(scope, receive, send)
