"""OpenAI (and Azure OpenAI) embeddings built on the official ``openai`` SDK."""

from typing import List, Optional

from application.core.settings import settings

# openai >= 2.53 rejects a falsy api_key at construction; Azure authenticates
# through its own deployment credentials, so a placeholder keeps the client
# constructible when no key is configured.
NO_API_KEY = "sk-no-key"

DEFAULT_MODEL = "text-embedding-ada-002"


class OpenAIEmbeddings:
    """Embeddings client for OpenAI and Azure OpenAI.

    Mirrors the ``embed_query``/``embed_documents`` interface the vector
    stores expect, matching :class:`RemoteEmbeddings` and
    :class:`EmbeddingsWrapper`.
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Build the client, routing to Azure when the Azure settings are set.

        Args:
            openai_api_key: API key; falls back to ``EMBEDDINGS_KEY`` then
                ``OPENAI_API_KEY``.
            model: Model name, or the Azure deployment name when running
                against Azure.
        """
        api_key = (
            openai_api_key
            or settings.EMBEDDINGS_KEY
            or settings.OPENAI_API_KEY
            or NO_API_KEY
        )
        self.model = model or DEFAULT_MODEL
        self.dimension = None

        is_azure = bool(
            settings.OPENAI_API_BASE
            and settings.OPENAI_API_VERSION
            and settings.AZURE_DEPLOYMENT_NAME
        )
        if is_azure:
            from openai import AzureOpenAI

            self.client = AzureOpenAI(
                api_key=api_key,
                azure_endpoint=settings.OPENAI_API_BASE,
                api_version=settings.OPENAI_API_VERSION,
            )
        else:
            from openai import OpenAI

            base_url = settings.OPENAI_BASE_URL or None
            self.client = OpenAI(api_key=api_key, base_url=base_url)

    def _embed(self, inputs: List[str]) -> List[List[float]]:
        """Embed a batch, returning vectors in request order."""
        response = self.client.embeddings.create(model=self.model, input=inputs)
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = [item.embedding for item in ordered]
        if vectors and self.dimension is None:
            self.dimension = len(vectors[0])
        return vectors

    def embed_query(self, query: str) -> List[float]:
        """Embed a single query string."""
        return self._embed([query])[0]

    def embed_documents(self, documents: List[str]) -> List[List[float]]:
        """Embed a list of documents."""
        if not documents:
            return []
        return self._embed(list(documents))

    def __call__(self, text):
        if isinstance(text, str):
            return self.embed_query(text)
        elif isinstance(text, list):
            return self.embed_documents(text)
        raise ValueError("Input must be a string or a list of strings")
