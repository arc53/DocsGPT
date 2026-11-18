"""Admin > decision model: load status, identity, this machine's measured speed and every feature's verdict.

Behind ``@admin_required``: the speed profile describes the server's hardware and load, so it is not on the
public ``/api/config``, which carries only ``decision_available``. Read from this process; nothing loads.
"""

from __future__ import annotations

from flask import jsonify, make_response
from flask_restx import Resource

from docsgpt import decisions
from docsgpt.api.admin.routes import admin_ns
from docsgpt.api.user.authz import admin_required


@admin_ns.route("/admin/decisions")
class AdminDecisionsResource(Resource):
    @admin_required
    def get(self):
        """The decision model as this API process sees it."""
        return make_response(jsonify({"success": True, **decisions.status()}), 200)
