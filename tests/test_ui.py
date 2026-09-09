"""The web UI shipped in the package is served in front of the API (docsgpt.ui)."""

import pytest
from a2wsgi import WSGIMiddleware
from flask import Flask
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from docsgpt.ui import StaticUI, config_js


@pytest.fixture
def static_dir(tmp_path):
    (tmp_path / "index.html").write_text('<html><head><script src="/config.js"></script></head><body>ui</body></html>')
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log('bundle')")
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / "inter.woff2").write_bytes(b"\x00\x01")
    (tmp_path / "favicon.ico").write_bytes(b"\x00")
    return tmp_path


def _backend() -> Flask:
    app = Flask("backend")

    @app.route("/")
    def home():
        return "backend home"

    @app.route("/api/health")
    def health():
        return {"status": "ok"}

    @app.route("/api/echo", methods=["POST"])
    def echo():
        return "posted"

    return app


@pytest.fixture
def client(static_dir):
    flask_app = _backend()
    ui = StaticUI.wrap(WSGIMiddleware(flask_app), flask_app.url_map, static_dir=static_dir)
    assert isinstance(ui, StaticUI)
    return TestClient(Starlette(routes=[Mount("/", app=ui)]))


class TestRouting:
    def test_root_is_the_ui_not_the_backend_home(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "ui" in response.text and "backend home" not in response.text
        assert response.headers["cache-control"] == "no-cache"

    def test_client_side_routes_render_index(self, client):
        assert client.get("/agents/123/edit").text == client.get("/").text

    def test_hashed_assets_are_immutable(self, client):
        response = client.get("/assets/index-abc123.js")
        assert response.status_code == 200
        assert "bundle" in response.text
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert "javascript" in response.headers["content-type"]

    def test_font_has_a_media_type(self, client):
        assert client.get("/fonts/inter.woff2").headers["content-type"] == "font/woff2"

    def test_backend_prefixes_pass_through(self, client):
        assert client.get("/api/health").json() == {"status": "ok"}
        missing = client.get("/api/does-not-exist")
        assert missing.status_code == 404
        assert "ui" not in missing.text, "an unknown API path is the backend's 404, not the UI"

    def test_writes_never_hit_the_ui(self, client):
        assert client.post("/api/echo").text == "posted"
        assert client.post("/settings").status_code in (404, 405)

    def test_head_works(self, client):
        response = client.head("/")
        assert response.status_code == 200
        assert response.content == b""


class TestConfigJs:
    def test_defaults_to_the_page_origin(self, client):
        response = client.get("/config.js")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert '"VITE_API_HOST":window.location.origin' in response.text
        assert '"VITE_BASE_URL":window.location.origin' in response.text

    def test_environment_values_win_and_are_escaped(self):
        body = config_js({"VITE_API_HOST": "https://api.example.com", "VITE_NOTE": 'say "hi"\\', "OTHER": "x", "VITE_EMPTY": ""})
        assert '"VITE_API_HOST":"https://api.example.com"' in body
        assert '"VITE_BASE_URL":window.location.origin' in body
        assert '"VITE_NOTE":"say \\"hi\\"\\\\"' in body
        assert "OTHER" not in body and "VITE_EMPTY" not in body
        assert body.startswith("window.__DOCSGPT_ENV__={") and body.endswith("};\n")


class TestSafety:
    def test_paths_outside_the_static_dir_are_never_served(self, static_dir):
        flask_app = _backend()
        ui = StaticUI.wrap(WSGIMiddleware(flask_app), flask_app.url_map, static_dir=static_dir)
        (static_dir.parent / "secret.txt").write_text("nope")
        assert ui._file("/../secret.txt") is None
        assert ui._file("/assets/../../secret.txt") is None
        assert ui._file("/") is None
        assert ui._file("/assets") is None, "directories are not files"


class TestWrap:
    def test_no_build_means_the_backend_alone(self, tmp_path):
        flask_app = _backend()
        backend = WSGIMiddleware(flask_app)
        assert StaticUI.wrap(backend, flask_app.url_map, static_dir=tmp_path) is backend

    def test_switched_off_means_the_backend_alone(self, static_dir):
        flask_app = _backend()
        backend = WSGIMiddleware(flask_app)
        assert StaticUI.wrap(backend, flask_app.url_map, static_dir=static_dir, enabled=False) is backend
