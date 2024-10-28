from application.core.settings import settings
from pymongo import MongoClient


class MongoDB:
    _client = None

    @classmethod
    def get_client(cls):
        """
        Get the MongoDB client instance, creating it if necessary.
        """
        if cls._client is None:
            cls._client = MongoClient(settings.MONGO_URI)
        return cls._client

    @classmethod
    def close_client(cls):
        """
        Close the MongoDB client connection.
        """
        if cls._client is not None:
            cls._client.close()
            cls._client = None
