import pytest
from application.agents.agent_creator import AgentCreator
from application.agents.classic_agent import ClassicAgent


@pytest.mark.unit
class TestAgentCreator:

    def test_create_classic_agent(self, agent_base_params):
        agent = AgentCreator.create_agent("classic", **agent_base_params)
        assert isinstance(agent, ClassicAgent)
        assert agent.endpoint == agent_base_params["endpoint"]
        assert agent.llm_name == agent_base_params["llm_name"]
        assert agent.model_id == agent_base_params["model_id"]

    def test_create_react_falls_back_to_classic(self, agent_base_params):
        agent = AgentCreator.create_agent("react", **agent_base_params)
        assert isinstance(agent, ClassicAgent)

    def test_create_agent_case_insensitive(self, agent_base_params):
        agent_upper = AgentCreator.create_agent("CLASSIC", **agent_base_params)
        agent_mixed = AgentCreator.create_agent("ClAsSiC", **agent_base_params)

        assert isinstance(agent_upper, ClassicAgent)
        assert isinstance(agent_mixed, ClassicAgent)

    def test_create_agent_invalid_type(self, agent_base_params):
        with pytest.raises(ValueError, match="No agent class found for type"):
            AgentCreator.create_agent("invalid_agent_type", **agent_base_params)

    def test_agent_registry_contains_expected_agents(self):
        assert "classic" in AgentCreator.agents
        assert "react" in AgentCreator.agents
        assert AgentCreator.agents["classic"] == ClassicAgent

    def test_create_agent_with_optional_params(self, agent_base_params):
        agent_base_params["user_api_key"] = "user_key_123"
        agent_base_params["chat_history"] = [{"prompt": "test", "response": "test"}]
        agent_base_params["json_schema"] = {"type": "object"}

        agent = AgentCreator.create_agent("classic", **agent_base_params)

        assert agent.user_api_key == "user_key_123"
        assert len(agent.chat_history) == 1
        assert agent.json_schema == {"type": "object"}

    def test_create_agent_with_attachments(self, agent_base_params):
        attachments = [{"name": "file.txt", "content": "test"}]
        agent_base_params["attachments"] = attachments

        agent = AgentCreator.create_agent("classic", **agent_base_params)
        assert agent.attachments == attachments
