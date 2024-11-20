from typing import List, Tuple, Union, Optional
from transformers import AutoTokenizer, AutoModel
from sentence_transformers import SentenceTransformer
import torch
import torch.nn as nn
from application.parser.schema.base import Document


class LateChunker:
    def __init__(self, model_name: str, late_tokens: int = 1000, **model_kwargs):
        """
        Initialize the LateChunker with a model, tokenizer, and late_tokens limit.
        Supports both transformers and sentence-transformers models.
        """
        self.late_tokens = late_tokens
        self.model_name = model_name

        # Load model based on type
        if "sentence-transformers" in model_name:
            self.model = SentenceTransformer(model_name, **model_kwargs)
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            self.wrapper_type = "sentence_transformers"
        else:
            self.model = AutoModel.from_pretrained(model_name, trust_remote_code=True, **model_kwargs)
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            self.wrapper_type = "transformers"

    def tokenize_with_offsets(self, text: str):
        """Tokenize text and return tokens with character offsets."""
        tokens = self.tokenizer.encode_plus(
            text, return_offsets_mapping=True, add_special_tokens=False
        )
        return tokens["input_ids"], tokens["offset_mapping"]

    def late_chunk_with_embeddings(
        self, documents: List[Document]
    ) -> List[Tuple[str, List[Tuple[int, int]], List[float]]]:
        """
        Combines documents into 'super chunks' that fit within `late_tokens` limit.
        Outputs each super chunk with span annotations and embeddings.
        """
        super_chunks = []
        current_super_chunk_text = []
        current_token_count = 0
        span_annotations = []

        for doc in documents:
            doc_text = doc.text
            input_ids, offsets = self.tokenize_with_offsets(doc_text)
            doc_token_count = len(input_ids)

            # Check if adding this document exceeds the late_tokens limit
            if current_token_count + doc_token_count > self.late_tokens:
                # Finalize the current super chunk
                combined_text = " ".join(current_super_chunk_text)
                embeddings = self.generate_embeddings(combined_text)

                super_chunks.append((combined_text, span_annotations, embeddings))

                # Reset for a new super chunk
                current_super_chunk_text = []
                span_annotations = []
                current_token_count = 0

            # Add document to the current super chunk
            start_token = current_token_count
            end_token = current_token_count + doc_token_count
            span_annotations.append((start_token, end_token))
            current_super_chunk_text.append(doc_text)
            current_token_count = end_token

        # Add the final super chunk if there are remaining documents
        if current_super_chunk_text:
            combined_text = " ".join(current_super_chunk_text)
            embeddings = self.generate_embeddings(combined_text)
            super_chunks.append((combined_text, span_annotations, embeddings))

        return super_chunks

    def generate_embeddings(self, text: str) -> List[float]:
        """Generate embeddings for a given text using the loaded model."""
        if self.wrapper_type == "sentence_transformers":
            # Sentence-Transformers
            embeddings = self.model.encode([text])
            return embeddings[0].tolist()

        elif self.wrapper_type == "transformers":
            # Transformers models
            inputs = self.tokenizer(text, return_tensors="pt")
            model_output = self.model(**inputs)
            return model_output.last_hidden_state.mean(dim=1).squeeze().tolist()

        else:
            raise ValueError("Unsupported model type for embedding generation.")
