# Context Compression

DocsGPT implements a smart context compression system to manage long conversations effectively. This feature prevents conversations from hitting the LLM's context window limit while preserving critical information and continuity.

## How It Works

The compression system operates on a "summarize and truncate" principle:

1.  **Threshold Check**: Before each request, the system calculates the total token count of the conversation history.
2.  **Trigger**: If the token count exceeds a configured threshold (default: 80% of the model's context limit), compression is triggered.
3.  **Summarization**: An LLM (potentially a different, cheaper/faster one) processes the older part of the conversation—including previous summaries, user messages, agent responses, and tool outputs.
4.  **Context Replacement**: The system generates a comprehensive summary of the older history. For subsequent requests, the LLM receives this **Summary + Recent Messages** instead of the full raw history.

### Key Features

*   **Recursive Summarization**: New summaries incorporate previous summaries, ensuring that information from the very beginning of a long chat is not lost.
*   **Tool Call Support**: The compression logic explicitly handles tool calls and their outputs (e.g., file readings, search results), summarizing their results so the agent retains knowledge of what it has already done.
*   **"Needle in a Haystack" Preservation**: The prompts are designed to identify and preserve specific, critical details (like passwords, keys, or specific user instructions) even when compressing large amounts of text.

## Configuration

You can configure the compression behavior in your `.env` file or `application/core/settings.py`:

| Setting | Default | Description |
| :--- | :--- | :--- |
| `ENABLE_CONVERSATION_COMPRESSION` | `True` | Master switch to enable/disable the feature. |
| `COMPRESSION_THRESHOLD_PERCENTAGE` | `0.8` | The fraction of the context window (0.0 to 1.0) that triggers compression. |
| `COMPRESSION_MODEL_OVERRIDE` | `None` | (Optional) Specify a different model ID to use specifically for the summarization task (e.g., using `gpt-3.5-turbo` to compress for `gpt-4`). |
| `COMPRESSION_MAX_HISTORY_POINTS` | `3` | The number of past compression points to keep in the database (older ones are discarded as they are incorporated into newer summaries). |

## Architecture

The system is modularized into several components:

*   **`CompressionThresholdChecker`**: Calculates token usage and decides when to compress.
*   **`CompressionService`**: Orchestrates the compression process, manages DB updates, and reconstructs the context (Summary + Recent Messages) for the LLM.
*   **`CompressionPromptBuilder`**: Constructs the specific prompts used to instruct the LLM to summarize the conversation effectively.
