import type { RetryConfig, RetryOn } from '../types/workflow';

/** The bounds the backend enforces on a retry policy. */
export const RETRY_MAX_ATTEMPTS = 5;
export const RETRY_MAX_DELAY_SECONDS = 300;
export const RETRY_MAX_BACKOFF_ENTRIES = 10;

export const RETRY_ON_CHOICES: RetryOn[] = ['transient', 'invalid_output'];

/** What an unset field means when neither the node nor the workflow sets it. */
export const DEFAULT_RETRY: Required<RetryConfig> = {
  max_attempts: 1,
  backoff_seconds: [2, 10, 30],
  on: ['transient', 'invalid_output'],
};

function isAttemptCount(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= 1 &&
    value <= RETRY_MAX_ATTEMPTS
  );
}

function isDelay(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= RETRY_MAX_DELAY_SECONDS
  );
}

/**
 * A saved retry policy in the editor's shape: only the fields of the right
 * type are kept, so a policy made through the API still loads.
 *
 * Returns:
 *   The policy, or undefined when it sets nothing.
 */
export function normalizeRetryConfig(raw: unknown): RetryConfig | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined;
  const source = raw as Record<string, unknown>;
  const config: RetryConfig = {};
  if (typeof source.max_attempts === 'number') {
    config.max_attempts = source.max_attempts;
  }
  if (
    Array.isArray(source.backoff_seconds) &&
    source.backoff_seconds.every((entry) => typeof entry === 'number')
  ) {
    config.backoff_seconds = [...(source.backoff_seconds as number[])];
  }
  if (Array.isArray(source.on)) {
    config.on = RETRY_ON_CHOICES.filter((choice) =>
      (source.on as unknown[]).includes(choice),
    );
  }
  return Object.keys(config).length > 0 ? config : undefined;
}

/** Whether a policy is within the backend's bounds; an unset one is. */
export function isValidRetryConfig(
  config: RetryConfig | null | undefined,
): boolean {
  if (!config) return true;
  if (config.max_attempts !== undefined && !isAttemptCount(config.max_attempts))
    return false;
  if (
    config.backoff_seconds !== undefined &&
    (config.backoff_seconds.length === 0 ||
      config.backoff_seconds.length > RETRY_MAX_BACKOFF_ENTRIES ||
      !config.backoff_seconds.every(isDelay))
  )
    return false;
  if (config.on !== undefined && config.on.length === 0) return false;
  return true;
}

/**
 * The policy a node runs with: each field from the node, else the workflow's
 * defaults, else the built-in default.
 */
export function effectiveRetry(
  node?: RetryConfig | null,
  defaults?: RetryConfig | null,
): Required<RetryConfig> {
  return {
    max_attempts:
      node?.max_attempts ??
      defaults?.max_attempts ??
      DEFAULT_RETRY.max_attempts,
    backoff_seconds:
      node?.backoff_seconds ??
      defaults?.backoff_seconds ??
      DEFAULT_RETRY.backoff_seconds,
    on: node?.on ?? defaults?.on ?? DEFAULT_RETRY.on,
  };
}

/** A backoff list as typed in its field: `2, 10, 30`. */
export function formatBackoff(backoff: number[] | undefined): string {
  return (backoff ?? []).join(', ');
}

/**
 * Reads a backoff field: delays in seconds, separated by commas or spaces.
 * A trailing separator is fine, so the field can be typed into.
 *
 * Returns:
 *   The delays (undefined when the field is blank), or a locale key naming
 *   what is wrong.
 */
export function parseBackoff(text: string): {
  value?: number[];
  error?: string;
} {
  const entries = text
    .split(/[\s,]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
  if (entries.length === 0) return {};
  const value = entries.map(Number);
  if (!value.every(isDelay))
    return { error: 'agents.workflow.retry.backoffInvalid' };
  if (value.length > RETRY_MAX_BACKOFF_ENTRIES)
    return { error: 'agents.workflow.retry.backoffTooMany' };
  return { value };
}

/**
 * Sets one field of a policy; undefined clears it.
 *
 * Returns:
 *   The policy, or undefined once it sets nothing, so the key drops off.
 */
export function withRetryField<K extends keyof RetryConfig>(
  config: RetryConfig | null | undefined,
  key: K,
  value: RetryConfig[K] | undefined,
): RetryConfig | undefined {
  const next: RetryConfig = { ...(config ?? {}) };
  if (value === undefined) delete next[key];
  else next[key] = value;
  return Object.keys(next).length > 0 ? next : undefined;
}
