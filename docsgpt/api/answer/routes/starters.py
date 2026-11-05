"""An agent's starters, by its API key, for clients that chat with the key.

The chat widget lists them when the embedding site passes no questions of its
own. The key travels in the JSON body, as on ``/stream``, so it stays out of
URLs and access logs; an agent that restricts its origins refuses other
websites here too (``docsgpt/api/agent_origins.py``).
"""

from flask import make_response, request, Response
from flask_restx import fields, Resource

from docsgpt.api.answer.routes.base import answer_ns
from docsgpt.api.user.agents.starters import stored_starters
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.session import db_readonly


@answer_ns.route("/api/agent_starters")
class AgentStartersResource(Resource):
    """The starters of the agent an API key belongs to, and nothing else about it."""

    starters_model = answer_ns.model(
        "AgentStartersModel",
        {
            "api_key": fields.String(
                required=True, description="The agent's API key"
            ),
        },
    )

    @answer_ns.expect(starters_model)
    @answer_ns.doc(
        description=(
            "List the starters (suggested first questions) of the agent an API key belongs to. "
            'Returns {"starters": [...]}, empty when the agent has none.'
        ),
        responses={
            200: "The agent's starters",
            400: "api_key is missing",
            401: "Invalid API key",
        },
    )
    def post(self) -> Response:
        """Return the agent's starters.

        Returns:
            ``{"starters": [...]}`` with 200; 400 when ``api_key`` is missing
            and 401 when it belongs to no agent.
        """
        data = request.get_json(silent=True)
        api_key = data.get("api_key") if isinstance(data, dict) else None
        if not isinstance(api_key, str) or not api_key.strip():
            return make_response({"success": False, "message": "api_key is required"}, 400)

        with db_readonly() as conn:
            agent = AgentsRepository(conn).find_by_key(api_key.strip())
        if not agent:
            return make_response({"success": False, "message": "Invalid API key."}, 401)
        return make_response({"starters": stored_starters(agent)}, 200)
