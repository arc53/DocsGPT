from abc import ABC, abstractmethod
import os, sys, base64, io
import torch
from sentence_transformers import SentenceTransformer
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
from langchain_openai import OpenAIEmbeddings
from application.core.settings import settings


class EmbeddingsWrapper:
    def __init__(self, model_name, *args, **kwargs):
        print(f"Initializing EmbeddingsWrapper with model_name={model_name}", file=sys.stderr)
        print("EmbeddingsWrapper initialized successfully", file=sys.stderr)
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.model = CLIPModel.from_pretrained(model_name)
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
        return query_embedding.squeeze().detach().cpu().numpy()

    def embed_documents(self, documents: list):
        try:
            if not self.model or not self.processor:
                raise ValueError("Model or processor not initialized properly for document embedding")
            inputs = self.processor(text=documents, return_tensors="pt", padding=True, truncation=True)
            with torch.no_grad():
                document_embeddings = self.model.get_text_features(**inputs)
            return document_embeddings.detach().cpu().numpy()
        except Exception as e:
            print(f"Error in embed_documents: {e}", file=sys.stderr)
            print(f"error line number: {sys.exc_info()[-1].tb_lineno}", file=sys.stderr)
            raise e

    def embed_image(self, image_path: str = None, image_base64: str = None):
        print(f"Image path: {image_path}", file=sys.stderr)
        print(f"Image base64: {image_base64[:50]}....", file=sys.stderr)
        if not self.model or not self.processor:
            raise ValueError("Model or processor not initialized properly for image embedding")
        if image_base64:
            img_data = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(img_data)).convert("RGB")
        elif image_path:
            image = Image.open(image_path).convert("RGB")
        else:
            raise ValueError("Image path or base64 data must be provided")

        inputs = self.processor(images=image, return_tensors="pt", padding=True)
        with torch.no_grad():
            image_embedding = self.model.get_image_features(**inputs)
        return image_embedding.squeeze().cpu().numpy()

    def __call__(self, text):
        if isinstance(text, str):
            if text.endswith((".jpg", ".jpeg", ".png")):
                return self.embed_image(text)
            else:
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
