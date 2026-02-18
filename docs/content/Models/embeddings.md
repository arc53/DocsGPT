---
title: Understanding and Configuring Embedding Models in DocsGPT
description: Learn about embedding models, their importance in DocsGPT, and how to configure them for optimal performance.
---

# Understanding and Configuring Embedding Models in DocsGPT

Embedding models are a crucial component of DocsGPT, enabling its powerful document understanding and question-answering capabilities. This guide will explain what embedding models are, why they are essential for DocsGPT, and how to configure them.

## What are Embedding Models?

In simple terms, an embedding model is a type of language model that converts text into numerical vectors. These vectors, known as embeddings, capture the semantic meaning of the text.  Think of it as translating words and sentences into a language that computers can understand mathematically, where similar meanings are represented by vectors that are close to each other in vector space.

**Why are embedding models important for DocsGPT?**

DocsGPT uses embedding models for several key tasks:

*   **Semantic Search:** When you upload documents to DocsGPT, the application uses an embedding model to generate embeddings for each document chunk. These embeddings are stored in a vector store. When you ask a question, your query is also converted into an embedding. DocsGPT then performs a semantic search in the vector store, finding document chunks whose embeddings are most similar to your query embedding. This allows DocsGPT to retrieve relevant information based on the *meaning* of your question and documents, not just keyword matching.
*   **Document Understanding:**  Embeddings help DocsGPT understand the underlying meaning of your documents, enabling it to answer questions accurately and contextually, even if the exact keywords from your question are not present in the retrieved document chunks.

In essence, embedding models are the bridge that allows DocsGPT to understand the nuances of human language and connect your questions to the relevant information within your documents.

## Out-of-the-Box Embedding Model Support in DocsGPT

DocsGPT is designed to be flexible and supports a wide range of embedding models right out of the box. Currently, DocsGPT provides native support for models from two major sources:

*   **Sentence Transformers:** DocsGPT supports all models available through the [Sentence Transformers library](https://www.sbert.net/). This library offers a vast selection of pre-trained embedding models, known for their quality and efficiency in various semantic tasks.
*   **OpenAI Embeddings:** DocsGPT also supports using embedding models from OpenAI, specifically the `text-embedding-ada-002` model, which is a powerful and widely used embedding model from OpenAI's API.

## Configuring Sentence Transformer Models

To utilize Sentence Transformer models within DocsGPT, you need to follow these steps:

1.  **Download the Model:** Sentence Transformer models are typically hosted on Hugging Face Model Hub. You need to download your chosen model and place it in the `model/` folder in the root directory of your DocsGPT project.

    For example, to use the `all-mpnet-base-v2` model, you would set `EMBEDDINGS_NAME` as described below, and ensure that the model files are available locally (DocsGPT will attempt to download it if it's not found, but local download is recommended for development and offline use).

2.  **Set `EMBEDDINGS_NAME` in `.env` (or `settings.py`):**  You need to configure the `EMBEDDINGS_NAME` setting in your `.env` file (or `settings.py`) to point to the desired Sentence Transformer model.

    *   **Using a pre-downloaded model from `model/` folder:** You can specify a path to the downloaded model within the `model/` directory. For instance, if you downloaded `all-mpnet-base-v2` and it's in `model/all-mpnet-base-v2`, you could potentially use a relative path like (though direct path to the model name is usually sufficient):

        ```
        EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2
        ```
        or simply use the model identifier:
        ```
        EMBEDDINGS_NAME=sentence-transformers/all-mpnet-base-v2
        ```

    *   **Using a model directly from Hugging Face Model Hub:** You can directly specify the model identifier from Hugging Face Model Hub:

        ```
        EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2
        ```

## Using OpenAI Embeddings

To use OpenAI's `text-embedding-ada-002` embedding model, you need to set `EMBEDDINGS_NAME` to `openai_text-embedding-ada-002` and ensure you have your OpenAI API key configured correctly via `API_KEY` in your `.env` file (if you are not using Azure OpenAI).

**Example `.env` configuration for OpenAI Embeddings:**

```
LLM_PROVIDER=openai
API_KEY=YOUR_OPENAI_API_KEY # Your OpenAI API Key
EMBEDDINGS_NAME=openai_text-embedding-ada-002
```

## Adding Support for Other Embedding Models

If you wish to use an embedding model that is not supported out-of-the-box, a good starting point for adding custom embedding model support is to examine the `base.py` file located in the `application/vectorstore` directory.

Specifically, pay attention to the `EmbeddingsWrapper` and `EmbeddingsSingleton` classes. `EmbeddingsWrapper` provides a way to wrap different embedding model libraries into a consistent interface for DocsGPT. `EmbeddingsSingleton` manages the instantiation and retrieval of embedding model instances. By understanding these classes and the existing embedding model implementations, you can create your own custom integration for virtually any embedding model library you desire.