import type { Model } from '../models/types';

// Bounds of `config.context_window_limit` and `config.history_token_limit`,
// as the server validates them (`docsgpt.guardrails.config`). A limit past
// the window of the agent's models is valid, only without effect, so the
// form notes it rather than refusing it.
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

const isUnset = (value?: number | null): value is null | undefined =>
  value === null || value === undefined;

/**
 * True when a limit is set and the server would reject it; unset is valid. A
 * switched-on field left empty is NaN, so it is invalid too.
 */
export function isContextLimitInvalid(value?: number | null): boolean {
  if (isUnset(value)) return false;
  return (
    !Number.isInteger(value) ||
    value < MIN_CONTEXT_WINDOW_LIMIT ||
    value > MAX_CONTEXT_WINDOW_LIMIT
  );
}

/** True when a valid context limit is past the model's window, where it has no effect. */
export function contextLimitAboveWindow(
  value: number | null | undefined,
  window: ModelWindow | null | undefined,
): boolean {
  if (!window || isUnset(value) || isContextLimitInvalid(value)) return false;
  return value > window.tokens;
}

/** What the context limit switches on at: the default, or the model's window when smaller. */
export function defaultContextLimit(window?: ModelWindow | null): number {
  if (!window) return DEFAULT_CONTEXT_WINDOW_LIMIT;
  return Math.min(
    DEFAULT_CONTEXT_WINDOW_LIMIT,
    Math.max(window.tokens, MIN_CONTEXT_WINDOW_LIMIT),
  );
}

/** The highest history limit the server takes: below a valid context limit, else its own bound. */
export function historyLimitMax(
  contextLimit: number | null | undefined,
): number {
  if (isUnset(contextLimit) || isContextLimitInvalid(contextLimit))
    return MAX_CONTEXT_WINDOW_LIMIT;
  return contextLimit - 1;
}

/** Like `isContextLimitInvalid`, for `config.history_token_limit`. */
export function isHistoryLimitInvalid(
  value: number | null | undefined,
  contextLimit: number | null | undefined,
): boolean {
  if (isUnset(value)) return false;
  return (
    !Number.isInteger(value) ||
    value < MIN_HISTORY_TOKEN_LIMIT ||
    value > historyLimitMax(contextLimit)
  );
}

/**
 * True when a history limit is at or past the model's window: the
 * conversation is summarized near the window first, so it has no effect.
 */
export function historyLimitAboveWindow(
  value: number | null | undefined,
  window: ModelWindow | null | undefined,
): boolean {
  if (!window || isUnset(value) || !Number.isInteger(value)) return false;
  return value >= window.tokens;
}

/** What the history limit switches on at: the default, kept below the context limit and the window. */
export function defaultHistoryLimit(
  contextLimit: number | null | undefined,
  window?: ModelWindow | null,
): number {
  const ceiling = Math.min(
    historyLimitMax(contextLimit),
    window ? window.tokens - 1 : Infinity,
  );
  return Math.max(
    MIN_HISTORY_TOKEN_LIMIT,
    Math.min(DEFAULT_HISTORY_TOKEN_LIMIT, ceiling),
  );
}

/** The limit an input's text stands for: null when empty, so the model's whole window is used. */
export function parseContextLimit(text: string): number | null {
  const trimmed = text.trim();
  return trimmed === '' ? null : Number(trimmed);
}
