from pydantic import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    LLM_NAME: str = "openai_chat"
    EMBEDDINGS_NAME: str = "openai_text-embedding-ada-002"
    openai_token: str
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str
    MONGO_URI: str

    API_KEY: str = None
    EMBEDDINGS_KEY: str = None


path = Path(__file__).parent.parent.absolute()
settings = Settings(_env_file=path.joinpath(".env"), _env_file_encoding="utf-8")
