from application.agents.classic_agent import ClassicAgent


class AgentCreator:
    agents = {
        "classic": ClassicAgent,
    }

    @classmethod
    def create_agent(cls, type, *args, **kwargs):
        agent_class = cls.agents.get(type.lower())
        if not agent_class:
            raise ValueError(f"No agent class found for type {type}")
        config = kwargs.pop('config', None)
        if isinstance(config, dict) and 'proxy_id' in config and 'proxy_id' not in kwargs:
            kwargs['proxy_id'] = config['proxy_id']
        return agent_class(*args, **kwargs)
