---
title: DocsGPT Settings
description: Configure your DocsGPT application by understanding the basic settings.
---

# DocsGPT Settings

DocsGPT is highly configurable, allowing you to tailor it to your specific needs and preferences. You can control various aspects of the application, from choosing the Large Language Model (LLM) provider to selecting embedding models and vector stores.

This document will guide you through the basic settings you can configure in DocsGPT. These settings determine how DocsGPT interacts with LLMs and processes your data.

## Configuration Methods

There are two primary ways to configure DocsGPT settings:

### 1. Configuration via `.env` file (Recommended)

The easiest and recommended way to configure basic settings is by using a `.env` file. This file should be located in the **root directory** of your DocsGPT project (the same directory where `setup.sh` is located).

**Example `.env` file structure:**

```
LLM_NAME=openai
API_KEY=YOUR_OPENAI_API_KEY
MODEL_NAME=gpt-4o
```

### 2. Configuration via `settings.py` file (Advanced)

For more advanced configurations or if you prefer to manage settings directly in code, you can modify the `settings.py` file. This file is located in the `application/core` directory of your DocsGPT project.

While modifying `settings.py` offers more flexibility, it's generally recommended to use the `.env` file for basic settings and reserve `settings.py` for more complex adjustments or when you need to configure settings programmatically.

**Location of `settings.py`:** `application/core/settings.py`

## Basic Settings Explained

Here are some of the most fundamental settings you'll likely want to configure:

- **`LLM_NAME`**: This setting determines which Large Language Model (LLM) provider DocsGPT will use.  It tells DocsGPT which API to interact with.

    - **Common values:**
        - `docsgpt`:  Use the DocsGPT Public API Endpoint (simple and free, as offered in `setup.sh` option 1).
        - `openai`: Use OpenAI's API (requires an API key).
        - `google`: Use Google's Vertex AI or Gemini models.
        - `anthropic`: Use Anthropic's Claude models.
        - `groq`: Use Groq's models.
        - `huggingface`: Use HuggingFace Inference API.
        - `azure_openai`: Use Azure OpenAI Service.
        - `openai` (when using local inference engines like Ollama, Llama.cpp, TGI, etc.):  This signals DocsGPT to use an OpenAI-compatible API format, even if the actual LLM is running locally.

- **`MODEL_NAME`**:  Specifies the specific model to use from the chosen LLM provider. The available models depend on the `LLM_NAME` you've selected.

    - **Examples:**
        - For `LLM_NAME=openai`: `gpt-4o`
        - For `LLM_NAME=google`: `gemini-2.0-flash`
        - For local models (e.g., Ollama): `llama3.2:1b` (or any model name available in your setup).

- **`EMBEDDINGS_NAME`**:  This setting defines which embedding model DocsGPT will use to generate vector embeddings for your documents. Embeddings are numerical representations of text that allow DocsGPT to understand the semantic meaning of your documents for efficient search and retrieval.

    - **Default value:** `huggingface_sentence-transformers/all-mpnet-base-v2` (a good general-purpose embedding model).
    - **Other options:** You can explore other embedding models from Hugging Face Sentence Transformers or other providers if needed.

- **`API_KEY`**:  Required for most cloud-based LLM providers.  This is your authentication key to access the LLM provider's API. You'll need to obtain this key from your chosen provider's platform.

- **`OPENAI_BASE_URL`**:  Specifically used when `LLM_NAME` is set to `openai` but you are connecting to a local inference engine (like Ollama, Llama.cpp, etc.) that exposes an OpenAI-compatible API.  This setting tells DocsGPT where to find your local LLM server.

## Configuration Examples

Let's look at some concrete examples of how to configure these settings in your `.env` file.

### Example for Cloud API Provider (OpenAI)

To use OpenAI's `gpt-4o` model, you would configure your `.env` file like this:

```
LLM_NAME=openai
API_KEY=YOUR_OPENAI_API_KEY  # Replace with your actual OpenAI API key
MODEL_NAME=gpt-4o
```

Make sure to replace `YOUR_OPENAI_API_KEY` with your actual OpenAI API key.

### Example for Local Deployment

To use a local Ollama server with the `llama3.2:1b` model, you would configure your `.env` file like this:

```
LLM_NAME=openai # Using OpenAI compatible API format for local models
API_KEY=None      # API Key is not needed for local Ollama
MODEL_NAME=llama3.2:1b
OPENAI_BASE_URL=http://host.docker.internal:11434/v1 # Default Ollama API URL within Docker
EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2 # You can also run embeddings locally if needed
```

In this case, even though you are using Ollama locally, `LLM_NAME` is set to `openai` because Ollama (and many other local inference engines) are designed to be API-compatible with OpenAI.  `OPENAI_BASE_URL` points DocsGPT to the local Ollama server.

## Exploring More Settings

These are just the basic settings to get you started. The `settings.py` file contains many more advanced options that you can explore to further customize DocsGPT, such as:

- Vector store configuration (`VECTOR_STORE`, Qdrant, Milvus, LanceDB settings)
- Retriever settings (`RETRIEVERS_ENABLED`)
- Cache settings (`CACHE_REDIS_URL`)
- And many more!

For a complete list of available settings and their descriptions, refer to the `settings.py` file in `application/core`. Remember to restart your Docker containers after making changes to your `.env` file or `settings.py` for the changes to take effect.