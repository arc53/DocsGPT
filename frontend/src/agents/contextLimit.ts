import type { Model } from '../models/types';

// Bounds of `config.context_window_limit` and `config.history_token_limit`,
// as the server validates them (`docsgpt.guardrails.config`). The server's
// ceiling is only a sanity bound; the form holds the limit to the window of
// the agent's models.
export const MIN_CONTEXT_WINDOW_LIMIT = 16000;
export const MAX_CONTEXT_WINDOW_LIMIT = 10_000_000;
export const MIN_HISTORY_TOKEN_LIMIT = 4000;

// What a switched-on limit starts from.
export const DEFAULT_CONTEXT_WINDOW_LIMIT = 100_000;
export const DEFAULT_HISTORY_TOKEN_LIMIT = 8000;

/** The largest context window among an agent's models, and the model that has it. */
export interface ModelWindow {
  tokens: number;
  name: string;
}

/** The largest window among `ids`; null when none of them reports one. */
export function largestModelWindow(
  models: Model[],
  ids: Iterable<string>,
): ModelWindow | null {
  const wanted = new Set(ids);
  let largest: ModelWindow | null = null;
  for (const model of models) {
    if (!wanted.has(model.id) || !(model.context_window > 0)) continue;
    if (!largest || model.context_window > largest.tokens)
      largest = { tokens: model.context_window, name: model.display_name };
  }
  return largest;
}

/** The highest context limit worth setting: the model's window, or the server's bound when it is unknown. */
export function contextLimitMax(window?: ModelWindow | null): number {
  if (!window) return MAX_CONTEXT_WINDOW_LIMIT;
  return Math.min(
    Math.max(window.tokens, MIN_CONTEXT_WINDOW_LIMIT),
    MAX_CONTEXT_WINDOW_LIMIT,
  );
}

const isUnset = (value?: number | null): value is null | undefined =>
  value === null || value === undefined;

/**
 * True when a limit is set and out of range; unset is valid. A switched-on
 * field left empty is NaN, so it is invalid too.
 */
export function isContextLimitInvalid(
  value?: number | null,
  window?: ModelWindow | null,
): boolean {
  if (isUnset(value)) return false;
  return (
    !Number.isInteger(value) ||
    value < MIN_CONTEXT_WINDOW_LIMIT ||
    value > contextLimitMax(window)
  );
}

/** The highest history limit: below the context limit, or below the window without a valid one. */
export function historyLimitMax(
  contextLimit: number | null | undefined,
  window?: ModelWindow | null,
): number {
  const ceiling =
    isUnset(contextLimit) || isContextLimitInvalid(contextLimit, window)
      ? contextLimitMax(window)
      : contextLimit;
  return ceiling - 1;
}

/** Like `isContextLimitInvalid`, for `config.history_token_limit`. */
export function isHistoryLimitInvalid(
  value: number | null | undefined,
  contextLimit: number | null | undefined,
  window?: ModelWindow | null,
): boolean {
  if (isUnset(value)) return false;
  return (
    !Number.isInteger(value) ||
    value < MIN_HISTORY_TOKEN_LIMIT ||
    value > historyLimitMax(contextLimit, window)
  );
}

/** The limit an input's text stands for: null when empty, so the model's whole window is used. */
export function parseContextLimit(text: string): number | null {
  const trimmed = text.trim();
  return trimmed === '' ? null : Number(trimmed);
}
