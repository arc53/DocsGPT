import type { ToolCallsType } from './types';

/** One chip per file a completed tool call produced. */
export type ArtifactChip = {
  id: string;
  ref?: string;
  label: string;
  /** The artifact's title, when its tool reported one. */
  title?: string;
  /** The file's name; unset for a note or todo. */
  filename?: string;
  /** The version the latest call produced. */
  version?: number;
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
 * write several files, and only the first was reachable before. An artifact
 * that several calls saved (each save adds a version) gets one chip, placed
 * where it first appeared and described by the latest call.
 *
 * Lives here rather than inside ``ConversationBubble`` so the regression test
 * exercises this function instead of a copy of it.
 */
export function deriveArtifactChips(
  toolCalls: ToolCallsType[] | undefined,
  jobArtifacts?: JobArtifact[],
): ArtifactChip[] {
  const chips = new Map<string, ArtifactChip>();
  for (const chip of collectArtifactChips(toolCalls)) chips.set(chip.id, chip);
  // A file a tool call on this turn also reported keeps that call's details.
  for (const chip of jobArtifactChips(jobArtifacts)) {
    if (!chips.has(chip.id)) chips.set(chip.id, chip);
  }
  return [...chips.values()];
}

/**
 * A file a background job wrote, listed on the reply that reports the job
 * (``metadata.job_artifacts``); the turn that started the job keeps it too.
 */
export type JobArtifact = {
  id: string;
  filename?: string;
  ref?: string;
  tool_name?: string;
  job_id?: string;
};

/** ``metadata.job_artifacts`` as stored, keeping only well-formed entries. */
export function readJobArtifacts(value: unknown): JobArtifact[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const text = (entry: Record<string, unknown>, key: string) =>
    typeof entry[key] === 'string' && entry[key] ? entry[key] : undefined;
  const files = value.flatMap((raw): JobArtifact[] => {
    if (!raw || typeof raw !== 'object') return [];
    const entry = raw as Record<string, unknown>;
    const id = text(entry, 'id');
    if (!id) return [];
    return [
      {
        id,
        filename: text(entry, 'filename'),
        ref: text(entry, 'ref'),
        tool_name: text(entry, 'tool_name'),
        job_id: text(entry, 'job_id'),
      },
    ];
  });
  return files.length ? files : undefined;
}

function jobArtifactChips(
  jobArtifacts: JobArtifact[] | undefined,
): ArtifactChip[] {
  return (jobArtifacts ?? []).map((artifact) => ({
    id: artifact.id,
    ref: artifact.ref,
    label:
      artifact.filename || formatToolName(artifact.tool_name) || 'Artifact',
    filename: artifact.filename,
    toolName: artifact.tool_name ?? '',
    callId: artifact.job_id ?? '',
  }));
}

/**
 * Every artifact in a conversation, once each, where it first appeared: a
 * job's file is on both the turn that started the job and the reply that
 * reported it.
 */
export function conversationArtifactChips(
  queries: { tool_calls?: ToolCallsType[]; job_artifacts?: JobArtifact[] }[],
): ArtifactChip[] {
  const chips = new Map<string, ArtifactChip>();
  for (const query of queries) {
    for (const chip of deriveArtifactChips(
      query.tool_calls,
      query.job_artifacts,
    )) {
      if (!chips.has(chip.id)) chips.set(chip.id, chip);
    }
  }
  return [...chips.values()];
}

function collectArtifactChips(
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
        title:
          'title' in artifact && artifact.title ? artifact.title : undefined,
        filename: artifact.filename || undefined,
        version:
          'version' in artifact && typeof artifact.version === 'number'
            ? artifact.version
            : undefined,
        toolName: toolCall.tool_name,
        callId: toolCall.call_id,
      }));
    });
}
