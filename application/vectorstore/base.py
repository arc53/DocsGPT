from abc import ABC, abstractmethod
import os, sys
import torch
from sentence_transformers import SentenceTransformer
from transformers import CLIPProcessor, CLIPModel
from langchain_openai import OpenAIEmbeddings
from application.core.settings import settings


class EmbeddingsWrapper:
    def __init__(self, model_name, *args, **kwargs):
        # self.model = SentenceTransformer(
        # model_name,
        # config_kwargs={"allow_dangerous_deserialization": True},
        # *args,
        # **kwargs
        # )
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.model = CLIPModel.from_pretrained(model_name)
        # self.dimension = self.model.get_sentence_embedding_dimension()
        if hasattr(self.model.config, "text_config"):
            self.dimension = self.model.config.text_config.hidden_size
        else:
            raise AttributeError("'text_config.hidden_size' not found in model configuration")


    def embed_query(self, query: str):
        if not self.model or not self.processor:
            raise ValueError(
                "Model or processor not initialized properly for query embedding."
            )
        input = self.processor(text=[query], return_tensors="pt", padding=True)
        with torch.no_grad():
            query_embedding = self.model.get_text_features(**input)
        return query_embedding.squeeze().tolist()

    def embed_documents(self, documents: list):
        if not self.model or not self.processor:
            raise ValueError("Model or processor not initialized properly for document embedding")
        inputs = self.processor(text=documents, return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            document_embeddings = self.model.get_text_features(**inputs)
        return document_embeddings.cpu().numpy()

    def embed_image(self, image_path: str):
        from PIL import Image
        if not self.model or not self.processor:
            raise ValueError("Model or processor not initialized properly for image embedding")
        image = Image.open(image_path).convert("RGB")
        inputs = self.processor(images=image, return_tensors="pt", padding=True)
        with torch.no_grad():
            image_embedding = self.model.get_image_features(**inputs)
        return image_embedding.squeeze().cpu().numpy()

    def __call__(self, text):
        if isinstance(text, str):
            return self.embed_query(text)
        elif isinstance(text, list):
            return self.embed_documents(text)
        else:
            raise ValueError("Input must be a string or a list of strings")


class EmbeddingsSingleton:
    _instances = {}

    @staticmethod
    def get_instance(embeddings_name, *args, **kwargs):
        if embeddings_name not in EmbeddingsSingleton._instances:
            EmbeddingsSingleton._instances[embeddings_name] = (
                EmbeddingsSingleton._create_instance(embeddings_name, *args, **kwargs)
            )
        return EmbeddingsSingleton._instances[embeddings_name]

    @staticmethod
    def _create_instance(embeddings_name, *args, **kwargs):
        embeddings_factory = {
            "openai_text-embedding-ada-002": OpenAIEmbeddings,
            "huggingface_sentence-transformers/all-mpnet-base-v2": lambda: EmbeddingsWrapper(
                "sentence-transformers/all-mpnet-base-v2"
            ),
            "huggingface_sentence-transformers-all-mpnet-base-v2": lambda: EmbeddingsWrapper(
                "sentence-transformers/all-mpnet-base-v2"
            ),
            "huggingface_hkunlp/instructor-large": lambda: EmbeddingsWrapper(
                "hkunlp/instructor-large"
            ),
            "openai/clip-vit-base-patch16": lambda: EmbeddingsWrapper(
                "openai/clip-vit-base-patch16"
            ),
        }

        if embeddings_name in embeddings_factory:
            return embeddings_factory[embeddings_name](*args, **kwargs)
        else:
            return EmbeddingsWrapper(embeddings_name, *args, **kwargs)


class BaseVectorStore(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def search(self, *args, **kwargs):
        pass

    def is_azure_configured(self):
        return (
            settings.OPENAI_API_BASE
            and settings.OPENAI_API_VERSION
            and settings.AZURE_DEPLOYMENT_NAME
        )

    def _get_embeddings(self, embeddings_name, embeddings_key=None):
        if embeddings_name == "openai_text-embedding-ada-002":
            if self.is_azure_configured():
                os.environ["OPENAI_API_TYPE"] = "azure"
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name, model=settings.AZURE_EMBEDDINGS_DEPLOYMENT_NAME
                )
            else:
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name, openai_api_key=embeddings_key
                )
        elif embeddings_name == "huggingface_sentence-transformers/all-mpnet-base-v2":
            if os.path.exists("./model/all-mpnet-base-v2"):
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name="./model/all-mpnet-base-v2",
                )
            else:
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name,
                )
        elif embeddings_name == "openai/clip-vit-base-patch16":
            if os.path.exists("./model/clip-vit-base-patch16"):
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name="./model/clip-vit-base-patch16",
                )
            else:
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name,
                )
        else:
            embedding_instance = EmbeddingsSingleton.get_instance(embeddings_name)

        return embedding_instance
