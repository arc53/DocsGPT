---
title: Context Compression
description: How DocsGPT summarizes long conversations to stay within the model's context window, and the settings that control it.
---

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

You can configure the compression behavior in your `.env` file or `docsgpt/core/settings/agents.py`:

| Setting | Default | Description |
| :--- | :--- | :--- |
| `ENABLE_CONVERSATION_COMPRESSION` | `True` | Master switch to enable/disable the feature. |
| `COMPRESSION_THRESHOLD_PERCENTAGE` | `0.8` | The fraction of the context window (0.0 to 1.0) that triggers compression. |
| `COMPRESSION_MODEL_OVERRIDE` | `None` | (Optional) A different model to write the summaries, for example a cheaper one such as `gpt-5.4-mini` while `gpt-5.5` answers. It must be a registered model id (from the [model catalog](https://github.com/arc53/DocsGPT/tree/main/docsgpt/core/models) or a custom model YAML); an unknown id makes compression fail, and the failure is only logged. |
| `COMPRESSION_MAX_HISTORY_POINTS` | `3` | The number of past compression points to keep in the database (older ones are discarded as they are incorporated into newer summaries). |
| `COMPRESSION_RECENT_FIELD_MAX_TOKENS` | `8000` | Cap, in tokens, on each prompt, response and tool result in the messages after the last compression point, which are otherwise kept verbatim. One very large message there can undo the compression. `0` turns the cap off. |
| `COMPRESSION_PROMPT_VERSION` | `v1.0` | Which summarization prompt to use, read from `docsgpt/prompts/compression/<version>.txt`. |

## Architecture

The system is modularized into several components in `docsgpt/api/answer/services/compression/`:

*   **`CompressionOrchestrator`** (`orchestrator.py`): Entry point. Checks the threshold before each request, and also during a tool loop, when tool results fill the context mid-answer; then it runs the compression and hands back the rebuilt context.
*   **`CompressionThresholdChecker`** (`threshold_checker.py`): Calculates token usage and decides when to compress.
*   **`TokenCounter`** (`token_counter.py`): Counts the tokens of a conversation or message list, including an estimate for attached images.
*   **`CompressionService`** (`service.py`): Runs the summarization, manages DB updates, and reconstructs the context (Summary + Recent Messages) for the LLM.
*   **`MessageBuilder`** (`message_builder.py`): Builds the message list from a summary and the recent messages, including after a mid-loop compression so tool execution can continue.
*   **`CompressionPromptBuilder`** (`prompt_builder.py`): Constructs the specific prompts used to instruct the LLM to summarize the conversation effectively.
