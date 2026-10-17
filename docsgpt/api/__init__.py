from flask import redirect, url_for
from flask_restx import Api

#: Where the Swagger UI is served. It sits under ``/api`` so the web UI the
#: API serves at ``/`` (docsgpt/ui.py) never shadows it; the spec itself stays
#: at ``/swagger.json``.
SWAGGER_UI_PATH = "/api/docs"


class DocsGPTApi(Api):
    """The flask-restx ``Api`` with root pointing at the Swagger UI."""

    def render_root(self):
        """Send ``/`` on the bare API (no web UI in front of it) to the Swagger UI.

        Returns:
            A redirect to the Swagger UI.
        """
        return redirect(url_for("doc"))


api = DocsGPTApi(
    version="1.0",
    title="DocsGPT API",
    description="API for DocsGPT",
    doc=SWAGGER_UI_PATH,
)
