"""Flask blueprint for OIDC SSO (AUTH_TYPE=oidc)."""

from __future__ import annotations

from flask import Blueprint

from .routes import register as register_routes


oidc_bp = Blueprint("oidc", __name__)
register_routes(oidc_bp)
