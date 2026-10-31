import isEqual from 'lodash/isEqual';
import { useCallback, useState } from 'react';

type BuilderDirtyOptions<T> = {
  /**
   * True once the payload is the one the builder opened with: a builder never
   * saved takes it as the baseline then. Leave false while a saved item
   * loads, and set its baseline with `markSaved` when it arrives.
   */
  ready?: boolean;
  /** How two payloads compare; deep equality by default. */
  equals?: (a: T, b: T) => boolean;
  /**
   * Unsaved changes kept outside the payload (a picked avatar, a takeover,
   * pending config): any of them makes the builder dirty.
   */
  extras?: boolean;
};

export type BuilderDirtyState<T> = {
  /** Whether saving now would store something, so leaving would lose it. */
  dirty: boolean;
  /**
   * Whether the baseline exists: the item loaded (or a new one opened). A
   * builder saves only then, or it would store what it shows while loading.
   */
  hasBaseline: boolean;
  /**
   * Records what is saved: after a load or any successful save (a draft save
   * too). Pass the payload that was sent, or a function of the current
   * baseline for a part saved on its own (an allowlist, a loaded default).
   */
  markSaved: (saved: T | ((baseline: T) => T)) => void;
};

/**
 * The one unsaved-changes rule for the agent and workflow builders: the save
 * payload now against the payload at load or at the last successful save,
 * draft saves included. A builder that was never saved compares with the
 * payload it opened with, so an untouched new agent or workflow is clean.
 *
 * Args:
 *   payload: What a save would send now, in a comparable shape.
 *   options: `ready`, `equals` and `extras` (see BuilderDirtyOptions).
 *
 * Returns:
 *   `dirty`, `hasBaseline` and `markSaved`.
 */
export function useBuilderDirtyState<T>(
  payload: T,
  {
    ready = false,
    equals = isEqual,
    extras = false,
  }: BuilderDirtyOptions<T> = {},
): BuilderDirtyState<T> {
  // Boxed, so a function payload is never called as a state updater.
  const [baseline, setBaseline] = useState<{ value: T } | null>(null);
  if (ready && baseline === null) {
    // The first payload once ready is what the builder opened with.
    setBaseline({ value: payload });
  }

  const markSaved = useCallback((saved: T | ((baseline: T) => T)) => {
    setBaseline((prev) => {
      if (typeof saved !== 'function') return { value: saved as T };
      return prev === null
        ? prev
        : { value: (saved as (baseline: T) => T)(prev.value) };
    });
  }, []);

  const dirty =
    baseline !== null && (extras || !equals(payload, baseline.value));
  return { dirty, hasBaseline: baseline !== null, markSaved };
}
