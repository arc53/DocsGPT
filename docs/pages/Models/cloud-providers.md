---
title: Connecting DocsGPT to LLM Providers
description: Explore the different Large Language Model (LLM) providers you can connect to DocsGPT, from cloud APIs to local inference engines.
---

# Connecting DocsGPT to LLM Providers

DocsGPT is designed to be flexible and work with a variety of Large Language Model (LLM) providers. Whether you prefer the simplicity of a public API, the power of cloud-based models, or the control of local inference engines, DocsGPT can be configured to meet your needs.

This guide will introduce you to the LLM providers that DocsGPT natively supports and explain how to connect to them.

## Supported LLM Providers

DocsGPT offers built-in support for the following LLM providers, selectable during the `setup.sh` script execution:

**Cloud API Providers:**

*   **DocsGPT Public API**
*   **OpenAI**
*   **Google (Vertex AI, Gemini)**
*   **Anthropic (Claude)**
*   **Groq**
*   **HuggingFace Inference API**
*   **Azure OpenAI**

## Configuration via `.env` file

Connecting DocsGPT to an LLM provider is primarily configured through environment variables set in the `.env` file located in the root directory of your DocsGPT project.

**Basic Configuration Parameters:**

*   **`LLM_NAME`**: This setting is crucial and specifies the provider you want to use.  The values correspond to the provider names listed above (e.g., `docsgpt`, `openai`, `google`, `ollama`, etc.).
*   **`MODEL_NAME`**:  Determines the specific model to be used from the chosen provider (e.g., `gpt-4o`, `gemini-2.0-flash`, `llama3.2:1b`). Refer to the provider's documentation for available model names.
*   **`API_KEY`**:  Required for most cloud API providers. Obtain this key from your provider's platform and set it in the `.env` file.
*   **`OPENAI_BASE_URL`**:  Specifically used when connecting to a local inference engine that is OpenAI API compatible. This setting points DocsGPT to the address of your local server.

## Configuration Examples

Here are examples of `.env` configurations for different LLM providers.

**Example for OpenAI:**

To use OpenAI's `gpt-4o` model, your `.env` file would look like this:

```
LLM_NAME=openai
API_KEY=YOUR_OPENAI_API_KEY # Replace with your actual OpenAI API key
MODEL_NAME=gpt-4o
```

**Example for Local Ollama:**

To connect to a local Ollama instance running `llama3.2:1b`, configure your `.env` as follows:

```
LLM_NAME=openai # Using OpenAI compatible API format for local models
API_KEY=None      # API Key is not needed for local Ollama
MODEL_NAME=llama3.2:1b
OPENAI_BASE_URL=http://host.docker.internal:11434/v1 # Default Ollama API URL within Docker
```

**Example for OpenAI-Compatible API (DeepSeek):**

Many LLM providers offer APIs that are compatible with the OpenAI API format. DeepSeek is one such example. To connect to DeepSeek, you would still use `LLM_NAME=openai` and point `OPENAI_BASE_URL` to the DeepSeek API endpoint.

```
LLM_NAME=openai
API_KEY=YOUR_DEEPSEEK_API_KEY # Your DeepSeek API key
MODEL_NAME=deepseek-chat # Or your desired DeepSeek model name
OPENAI_BASE_URL=https://api.deepseek.com/v1 # DeepSeek API base URL
```

**Important Note:**  When using OpenAI-compatible APIs, you might need to adjust other settings as well, depending on the specific API's requirements.  Always consult the provider's API documentation and the [DocsGPT Settings Guide](/Deploying/DocsGPT-Settings) for detailed configuration options.

## Exploring More Providers and Advanced Settings

The providers listed above are those with direct support in `setup.sh`. However, DocsGPT's flexible design allows you to connect to virtually any LLM provider that offers an API, especially those compatible with the OpenAI API standard.

For a comprehensive list of all configurable settings, including advanced options for each provider and details on how to connect to other LLMs, please refer to the [DocsGPT Settings Guide](/Deploying/DocsGPT-Settings). This guide provides in-depth information on customizing your DocsGPT setup to work with a wide range of LLM providers and tailor the application to your specific needs.