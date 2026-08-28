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

*   **Local models (FastEmbed / ONNX Runtime):** DocsGPT runs local embeddings through [FastEmbed](https://github.com/qdrant/fastembed). Any of FastEmbed's built-in models works, as does any Hugging Face repository that ships an ONNX export at `onnx/model.onnx` — which covers most popular sentence-transformers repos. A repository with PyTorch weights only will not load; serve those over `EMBEDDINGS_BASE_URL` instead. New installs default to `ibm-granite/granite-embedding-311m-multilingual-r2`; existing ones stay on `huggingface_sentence-transformers/all-mpnet-base-v2` until re-embedded.
*   **OpenAI Embeddings:** DocsGPT supports OpenAI embedding models (for example `text-embedding-ada-002`, `text-embedding-3-small`, `text-embedding-3-large`) via the OpenAI API.
*   **Azure OpenAI Embeddings:** Set `AZURE_EMBEDDINGS_DEPLOYMENT_NAME` alongside your Azure OpenAI configuration.
*   **Remote OpenAI-compatible Embeddings:** Any server that exposes an OpenAI-compatible `/v1/embeddings` endpoint (for example llama.cpp, vLLM, TEI, or a hosted provider) by setting `EMBEDDINGS_BASE_URL`. See [Remote Embeddings](#remote-openai-compatible-embeddings) below.

## Configuring a Local Model

Set `EMBEDDINGS_NAME` in your `.env` to a registry name or a Hugging Face repository id:

```
EMBEDDINGS_NAME=ibm-granite/granite-embedding-311m-multilingual-r2
```

The model is downloaded on first use and cached; set `EMBEDDINGS_CACHE_DIR` to control where. There is no `model/` folder to populate by hand, and a filesystem path is not accepted as a model name.

DocsGPT knows the pooling, vector width and context window of the models in its registry (`all-mpnet-base-v2`, `granite-embedding-311m-multilingual-r2`, `granite-embedding-97m-multilingual-r2`). For any other repository it reads those from the repository's own `1_Pooling/config.json` and `modules.json`. If a repository declares neither, mean pooling with L2 normalization is assumed and a warning is logged — pin the real values with `EMBEDDINGS_POOLING` (`cls` or `mean`) and `EMBEDDINGS_NORMALIZE`.

Models with a Dense projection layer (for example `sentence-transformers/LaBSE`) are refused at startup: FastEmbed cannot apply the projection, so the vectors would be the wrong width and in a different space.

For an offline or air-gapped install, pre-fetch the model at build or setup time:

```bash
python -m application.scripts.prefetch_models
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

## Where the model runs

A local embedding model costs a few hundred megabytes of resident memory per process, and the API embeds every query it serves — so by default it would hold its own copy alongside the worker's.

`EMBEDDINGS_DELEGATE_TO_WORKER` (on by default) moves that work to the Celery worker: the API sends the text over the broker and gets the vector back, holding no model. Measured on a default install, the API process drops from ~657 MB to ~284 MB, and query embedding costs one broker round trip (~60 ms on a prefork worker).

Retrieval then depends on a worker consuming `EMBEDDINGS_QUEUE` (`embeddings` by default). A bare `celery worker` with no `-Q` consumes it along with everything else. **A worker started with an explicit `-Q` must list it** — the bundled Compose and Kubernetes manifests run `-Q docsgpt,parsing,embeddings` for exactly this reason. Omit it and every search blocks for `EMBEDDINGS_DELEGATE_TIMEOUT` and then returns an answer with no retrieved context, without raising.

Sharing one worker also shares its concurrency with ingest, so a query can queue behind a long parse. Run a dedicated worker to isolate query latency:

```bash
celery -A application.app.celery worker -Q embeddings
```

Set `EMBEDDINGS_DELEGATE_TO_WORKER=false` if you run the API without a worker; it will load the model in-process instead.

For production, prefer `EMBEDDINGS_BASE_URL`. A real embedding service removes the model from *both* the API and the worker, and replaces the broker round trip with a network call.

## Batch sizes

Two separate knobs, easily confused:

- `EMBEDDINGS_BATCH_SIZE` (default 32) — chunks per store transaction, and per request to a remote embeddings API. Larger means fewer round trips and fewer transactions.
- `EMBEDDINGS_MODEL_BATCH_SIZE` (default 1) — documents per forward pass of a *local* model.

For the local model, bigger batches are not faster. ONNX needs a rectangular tensor, so every input in a pass is padded up to the longest one in it, and that waste grows with the square of chunk length. Measured on a 30-document ingest at the 1250-token default chunk size:

| `EMBEDDINGS_MODEL_BATCH_SIZE` | embed time | peak RSS |
| --- | --- | --- |
| 32 | 154 s | 7.7 GB |
| 8 | 76 s | 5.0 GB |
| 4 | 76 s | 3.6 GB |
| 2 | 74 s | 2.3 GB |
| 1 | 53 s | 1.5 GB |

Raise it only if your chunks are short and uniform in length.

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

To teach DocsGPT about a new model — so it carries a known pooling, width and context window rather than being inferred — add an `EmbeddingModel` entry to `MODELS` in `application/vectorstore/model_registry.py`. That registry is the single source of truth the local runner, the remote client, the schema bootstrap and the chunker all read.

Specifically, pay attention to the `EmbeddingsWrapper` and `EmbeddingsSingleton` classes. `EmbeddingsWrapper` provides a way to wrap different embedding model libraries into a consistent interface for DocsGPT. `EmbeddingsSingleton` manages the instantiation and retrieval of embedding model instances. By understanding these classes and the existing embedding model implementations, you can create your own custom integration for virtually any embedding model library you desire.