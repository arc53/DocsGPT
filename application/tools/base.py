from abc import ABC, abstractmethod


class Tool(ABC):
    @abstractmethod
    def execute_action(self, action_name: str, **kwargs):
        pass

    @abstractmethod
    def get_actions_metadata(self):
        """
        Returns a list of JSON objects describing the actions supported by the tool.
        """
        pass

    @abstractmethod
    def get_config_requirements(self):
        """
        Returns a dictionary describing the configuration requirements for the tool.
        """
        pass
