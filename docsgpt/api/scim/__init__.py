"""Flask blueprint for SCIM 2.0 user provisioning (/scim/v2)."""

from __future__ import annotations

from flask import Blueprint

from .routes import register as register_routes


scim_bp = Blueprint("scim", __name__)
register_routes(scim_bp)
