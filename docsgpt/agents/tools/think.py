from docsgpt.agents.tools.base import Tool


THINK_TOOL_ID = "think"

# The executor loads a tool by its row ``id``; think has no DB row, so it
# carries its sentinel id or is dropped with ``tool_missing_row_id``.
THINK_TOOL_ENTRY = {
    "id": THINK_TOOL_ID,
    "name": "think",
    "actions": [
        {
            "name": "reason",
            "description": (
                "Use this tool to think through your reasoning step by step "
                "before deciding on your next action. Always reason before "
                "searching or answering."
            ),
            "active": True,
            "parameters": {
                "properties": {
                    "reasoning": {
                        "type": "string",
                        "description": "Your step-by-step reasoning and analysis",
                        "filled_by_llm": True,
                        "required": True,
                    }
                }
            },
        }
    ],
}


class ThinkTool(Tool):
    """Pseudo-tool that captures chain-of-thought reasoning.

    Returns a short acknowledgment so the LLM can continue.
    The reasoning content is captured in tool_call data for transparency.
    """

    internal = True

    def __init__(self, config=None):
        pass

    def execute_action(self, action_name: str, **kwargs):
        return "Continue."

    def get_actions_metadata(self):
        return [
            {
                "name": "reason",
                "access": "read",
                "description": (
                    "Use this tool to think through a complex step — analyze "
                    "tool results, weigh options, or plan multi-step work — "
                    "before taking your next action."
                ),
                "parameters": {
                    "properties": {
                        "reasoning": {
                            "type": "string",
                            "description": "Your step-by-step reasoning and analysis",
                            "filled_by_llm": True,
                            "required": True,
                        }
                    }
                },
            }
        ]

    def get_config_requirements(self):
        return {}
