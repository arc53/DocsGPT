from application.agents.tools.base import Tool


THINK_TOOL_ID = "think"

THINK_TOOL_ENTRY = {
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
                "description": (
                    "Use this tool to think through your reasoning step by step "
                    "before deciding on your next action. Always reason before "
                    "searching or answering."
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
