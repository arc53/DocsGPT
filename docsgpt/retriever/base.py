from abc import ABC, abstractmethod


class BaseRetriever(ABC):
    @property
    def _connector_labels(self):
        """Per-retriever memo of each source's connector ("From Google Drive")."""
        cache = self.__dict__.get("_connector_label_cache")
        if cache is None:
            from docsgpt.connectors.attribution import ConnectorLabelCache

            cache = ConnectorLabelCache()
            self.__dict__["_connector_label_cache"] = cache
        return cache

    def __init__(self):
        pass

    @abstractmethod
    def search(self, *args, **kwargs):
        pass
