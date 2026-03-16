"""
Local embeddings using SentenceTransformer.
This module is only imported when EMBEDDINGS_BASE_URL is not set,
to avoid loading SentenceTransformer into memory when using remote embeddings.
"""

import logging

from sentence_transformers import SentenceTransformer


class EmbeddingsWrapper:
    def __init__(self, model_name, *args, **kwargs):
        logging.info(f"Initializing EmbeddingsWrapper with model: {model_name}")
        try:
            kwargs.setdefault("trust_remote_code", True)
            self.model = SentenceTransformer(
                model_name,
                config_kwargs={"allow_dangerous_deserialization": True},
                *args,
                **kwargs,
            )
            if self.model is None or self.model._first_module() is None:
                raise ValueError(
                    f"SentenceTransformer model failed to load properly for: {model_name}"
                )
            self.dimension = self.model.get_sentence_embedding_dimension()
            logging.info(f"Successfully loaded model with dimension: {self.dimension}")
        except Exception as e:
            logging.error(
                f"Failed to initialize SentenceTransformer with model {model_name}: {str(e)}",
                exc_info=True,
            )
            raise

    def embed_query(self, query: str):
        return self.model.encode(query).tolist()

    def embed_documents(self, documents: list):
        return self.model.encode(documents).tolist()

    def __call__(self, text):
        if isinstance(text, str):
            return self.embed_query(text)
        elif isinstance(text, list):
            return self.embed_documents(text)
        else:
            raise ValueError("Input must be a string or a list of strings")
