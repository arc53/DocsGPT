"""Flask blueprint for the Remote Device feature."""

from __future__ import annotations

from flask import Blueprint

from .routes import register as register_routes


devices_bp = Blueprint("devices", __name__)
register_routes(devices_bp)
