import type { ToolCallsType } from './types';

/** One chip per file a completed tool call produced. */
export type ArtifactChip = {
  id: string;
  ref?: string;
  label: string;
  toolName: string;
  callId: string;
};

/** Display name for a tool, used when an artifact reported no filename. */
export function formatToolName(toolName: string | undefined): string {
  if (!toolName) return '';
  // Display-name overrides for tools whose label differs from the formatted key.
  const overrides: Record<string, string> = {
    artifact_generator: 'Artifact',
  };
  if (overrides[toolName]) return overrides[toolName];
  return toolName
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

/**
 * One entry per artifact, not per tool call: a single call (``run_code``) can
 * write several files, and only the first was reachable before.
 *
 * Lives here rather than inside ``ConversationBubble`` so the regression test
 * exercises this function instead of a copy of it.
 */
export function deriveArtifactChips(
  toolCalls: ToolCallsType[] | undefined,
): ArtifactChip[] {
  return (toolCalls ?? [])
    .filter((toolCall) => toolCall.status === 'completed')
    .flatMap((toolCall) => {
      const produced = toolCall.artifacts?.length
        ? toolCall.artifacts
        : toolCall.artifact_id
          ? [{ id: toolCall.artifact_id, filename: undefined, ref: undefined }]
          : [];
      return produced.map((artifact) => ({
        id: artifact.id,
        ref: artifact.ref ?? undefined,
        // The file's own name is what the user recognises; the tool that made
        // it ("Code Executor") tells them nothing about which file this is.
        label:
          artifact.filename || formatToolName(toolCall.tool_name) || 'Artifact',
        toolName: toolCall.tool_name,
        callId: toolCall.call_id,
      }));
    });
}
