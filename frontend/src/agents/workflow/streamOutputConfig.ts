/**
 * How a node's finished step reaches the chat stream (`stream_output`):
 * `summary` sends its output and state changes while the event is small and a
 * preview past the server's limit, `full` always sends them, `none` sends the
 * step's status only. The saved run keeps the full values in every case.
 */
export type StreamOutput = 'summary' | 'full' | 'none';

export const DEFAULT_STREAM_OUTPUT: StreamOutput = 'summary';

export const STREAM_OUTPUT_OPTIONS: { value: StreamOutput; label: string }[] = [
  { value: 'summary', label: 'Summary when large' },
  { value: 'full', label: 'Always full' },
  { value: 'none', label: 'Status only' },
];

/** Normalize an unknown stream_output value to a supported setting. */
export function normalizeStreamOutput(value: unknown): StreamOutput {
  return STREAM_OUTPUT_OPTIONS.some((option) => option.value === value)
    ? (value as StreamOutput)
    : DEFAULT_STREAM_OUTPUT;
}
