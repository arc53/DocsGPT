// Bounds of `config.context_window_limit`, as the server validates them
// (`docsgpt.guardrails.config`).
export const MIN_CONTEXT_WINDOW_LIMIT = 16000;
export const MAX_CONTEXT_WINDOW_LIMIT = 10_000_000;

/** True when a limit is set and the server would reject it; unset is valid. */
export function isContextLimitInvalid(value?: number | null): boolean {
  if (value === null || value === undefined) return false;
  return (
    !Number.isInteger(value) ||
    value < MIN_CONTEXT_WINDOW_LIMIT ||
    value > MAX_CONTEXT_WINDOW_LIMIT
  );
}

/** The limit an input's text stands for: null when empty, so the model's whole window is used. */
export function parseContextLimit(text: string): number | null {
  const trimmed = text.trim();
  return trimmed === '' ? null : Number(trimmed);
}
