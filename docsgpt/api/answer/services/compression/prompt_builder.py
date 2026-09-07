"""Compression prompt building logic."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CompressionPromptBuilder:
    """Builds prompts for LLM compression calls."""

    def __init__(self, version: str = "v1.0"):
        """
        Initialize prompt builder.

        Args:
            version: Prompt template version to use
        """
        self.version = version
        self.system_prompt = self._load_prompt(version)

    def _load_prompt(self, version: str) -> str:
        """
        Load prompt template from file.

        Args:
            version: Version string (e.g., 'v1.0')

        Returns:
            Prompt template content

        Raises:
            FileNotFoundError: If prompt template file doesn't exist
        """
        current_dir = Path(__file__).resolve().parents[4]
        prompt_path = current_dir / "prompts" / "compression" / f"{version}.txt"

        try:
            with open(prompt_path, "r") as f:
                return f.read()
        except FileNotFoundError:
            logger.error(f"Compression prompt template not found: {prompt_path}")
            raise FileNotFoundError(
                f"Compression prompt template '{version}' not found at {prompt_path}. "
                f"Please ensure the template file exists."
            )

    def build_prompt(
        self,
        queries: List[Dict[str, Any]],
        existing_compressions: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, str]]:
        """
        Build messages for compression LLM call.

        Args:
            queries: List of query objects to compress
            existing_compressions: List of previous compression points

        Returns:
            List of message dicts for LLM
        """
        # Build conversation text
        conversation_text = self._format_conversation(queries)

        # Add existing compression context if present
        existing_compression_context = ""
        if existing_compressions and len(existing_compressions) > 0:
            existing_compression_context = (
                "\n\nIMPORTANT: This conversation has been compressed before. "
                "Previous compression summaries:\n\n"
            )
            for i, comp in enumerate(existing_compressions):
                existing_compression_context += (
                    f"--- Compression {i + 1} (up to message {comp.get('query_index', 'unknown')}) ---\n"
                    f"{comp.get('compressed_summary', '')}\n\n"
                )
            existing_compression_context += (
                "Your task is to create a NEW summary that incorporates the context from "
                "previous compressions AND the new messages below. The final summary should "
                "be comprehensive and include all important information from both previous "
                "compressions and new messages.\n\n"
            )

        user_prompt = (
            f"{existing_compression_context}"
            f"Here is the conversation to summarize:\n\n"
            f"{conversation_text}"
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return messages

    def _format_conversation(self, queries: List[Dict[str, Any]]) -> str:
        """
        Format conversation queries into readable text for compression.

        Args:
            queries: List of query objects

        Returns:
            Formatted conversation text
        """
        conversation_lines = []

        for i, query in enumerate(queries):
            conversation_lines.append(f"--- Message {i + 1} ---")
            conversation_lines.append(f"User: {query.get('prompt', '')}")

            # Add tool calls if present
            tool_calls = query.get("tool_calls", [])
            if tool_calls:
                conversation_lines.append("\nTool Calls:")
                for tc in tool_calls:
                    tool_name = tc.get("tool_name", "unknown")
                    action_name = tc.get("action_name", "unknown")
                    arguments = tc.get("arguments", {})
                    result = tc.get("result", "")
                    if result is None:
                        result = ""
                    status = tc.get("status", "unknown")

                    # Include full tool result for complete compression context
                    conversation_lines.append(
                        f"  - {tool_name}.{action_name}({arguments}) "
                        f"[{status}] → {result}"
                    )

            # Add agent thought if present
            thought = query.get("thought", "")
            if thought:
                conversation_lines.append(f"\nAgent Thought: {thought}")

            # Add assistant response
            conversation_lines.append(f"\nAssistant: {query.get('response', '')}")

            # Add sources if present
            sources = query.get("sources", [])
            if sources:
                conversation_lines.append(f"\nSources Used: {len(sources)} documents")

            conversation_lines.append("")  # Empty line between messages

        return "\n".join(conversation_lines)
