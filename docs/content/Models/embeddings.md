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

DocsGPT is designed to be flexible and supports a wide range of embedding models right out of the box:

*   **Sentence Transformers:** DocsGPT supports all models available through the [Sentence Transformers library](https://www.sbert.net/). This library offers a vast selection of pre-trained embedding models, known for their quality and efficiency in various semantic tasks. This is the default (`EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2`).
*   **OpenAI Embeddings:** DocsGPT supports OpenAI embedding models (for example `text-embedding-ada-002`, `text-embedding-3-small`, `text-embedding-3-large`) via the OpenAI API.
*   **Azure OpenAI Embeddings:** Set `AZURE_EMBEDDINGS_DEPLOYMENT_NAME` alongside your Azure OpenAI configuration.
*   **Remote OpenAI-compatible Embeddings:** Any server that exposes an OpenAI-compatible `/v1/embeddings` endpoint (for example llama.cpp, vLLM, TEI, or a hosted provider) by setting `EMBEDDINGS_BASE_URL`. See [Remote Embeddings](#remote-openai-compatible-embeddings) below.

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

## Remote (OpenAI-compatible) Embeddings

If you run your own embedding server, or use a provider that exposes an OpenAI-style embeddings API, point DocsGPT at it with `EMBEDDINGS_BASE_URL`. When this is set, all embedding calls (ingestion and querying) are sent to `{EMBEDDINGS_BASE_URL}/v1/embeddings` in OpenAI format instead of running a local model.

```env
EMBEDDINGS_BASE_URL=http://localhost:8080   # your OpenAI-compatible embeddings server
EMBEDDINGS_NAME=your-model-name             # sent as the "model" field in the request
EMBEDDINGS_KEY=YOUR_API_KEY                 # optional; sent as a Bearer token
```

- `EMBEDDINGS_BASE_URL` — base URL of the remote server. Setting it switches DocsGPT into remote-embeddings mode.
- `EMBEDDINGS_NAME` — forwarded as the `model` field in each request.
- `EMBEDDINGS_KEY` — optional bearer token. If you are using OpenAI directly you can copy `API_KEY` here.

### Guarding against oversized inputs

Some remote servers (notably llama.cpp) reject any single input larger than their physical batch size with a `500` error. Set `EMBEDDINGS_MAX_INPUT_TOKENS` to clip each input to a fixed number of tokens before it is sent:

```env
EMBEDDINGS_MAX_INPUT_TOKENS=512
```

When set, each input string is truncated to that many tokens and the overflow is dropped (lossy by design).

You usually do not need to set it. When `EMBEDDINGS_NAME` names a model DocsGPT knows, its context window is used automatically, and counting uses that model's own tokenizer, so the limit and the count are in the same unit. Set `EMBEDDINGS_MAX_INPUT_TOKENS` when your server serves a model DocsGPT does not know, or when you deliberately want a limit below the model's own.

Leaving `EMBEDDINGS_NAME` unset imposes no limit: the name is only forwarded as the `model` field in each request, so a default nobody chose is not taken as a description of your server. When no model tokenizer is available, counting falls back to tiktoken — pick a limit with headroom below the server's true limit to absorb the skew between the two tokenizers.

## Important: Embedding Dimensions Must Stay Consistent

Each embedding model produces vectors of a fixed dimension, and your vector store is created with that dimension. **Changing `EMBEDDINGS_NAME` to a model with a different dimension is not compatible with an existing index** — FAISS and LanceDB will raise a dimension-mismatch error, and pgvector/Qdrant tables are sized to the original dimension.

If you need to switch embedding models, you must re-ingest your sources so the index is rebuilt with the new dimension. This also applies to the [GraphRAG](/Sources/GraphRAG) graph tables, which are sized to the embedding dimension at creation time.

### A matching dimension is not a matching model

The dimension check is a guard against a corrupt index, not a guarantee that a swap is safe. Two models of the *same* width — `all-mpnet-base-v2` and `granite-embedding-311m-multilingual-r2` are both 768 — raise nothing at all, and every query is then embedded by a different model than the stored vectors were. Nothing fails; retrieval quality simply degrades.

Switching between same-width models therefore still requires re-embedding:

```bash
python -m application.scripts.reembed
```

Run it after changing `EMBEDDINGS_NAME` and before serving queries. See [Upgrading](/upgrading) for the granite migration specifically.

Changing to a model of a *different* width is supported for FAISS: the script rebuilds the index at the new width and keeps the existing chunk ids. For `pgvector` the vector column is sized at creation time, so a width change there still means re-ingesting those sources.

With `GRAPHRAG_ENABLED`, the script also rewrites `graph_nodes.name_embedding` on `pgvector`. Those vectors seed every graph traversal, and they share the chunk vectors' width, so leaving them behind degrades graph retrieval just as silently.

## Adding Support for Other Embedding Models

If you wish to use an embedding model that is not supported out-of-the-box, a good starting point for adding custom embedding model support is to examine the `base.py` file located in the `application/vectorstore` directory.

Specifically, pay attention to the `EmbeddingsWrapper` and `EmbeddingsSingleton` classes. `EmbeddingsWrapper` provides a way to wrap different embedding model libraries into a consistent interface for DocsGPT. `EmbeddingsSingleton` manages the instantiation and retrieval of embedding model instances. By understanding these classes and the existing embedding model implementations, you can create your own custom integration for virtually any embedding model library you desire.