import isEqual from 'lodash/isEqual';
import { useCallback, useEffect, useRef, useState } from 'react';

type Marker = { previous: unknown; applied: unknown };

export type DraftedFields<K extends string> = {
  /** The drafted fields, in the order they were marked. */
  fields: K[];
  isDrafted: (field: K) => boolean;
  /**
   * Mark a field the drafter changed. `previous` is what undo puts back, in
   * the form's own shape; a field drafted again while it still holds what
   * the last draft set keeps the value from before the first draft.
   * `applied` is the value it now holds, in the comparable shape of
   * `values`: once the field's value differs, the user edited it by hand
   * and the mark goes.
   */
  mark: (field: K, previous: unknown, applied: unknown) => void;
  /**
   * The drafter rewrote a field a step at a time (a review deciding its
   * changes one by one): a marked field keeps its mark and undo, now
   * holding `applied`, so the step isn't read as a hand edit. An unmarked
   * field stays unmarked.
   */
  follow: (field: K, applied: unknown) => void;
  /** Put a field's previous value back and drop its mark. */
  undo: (field: K) => void;
  /**
   * What undo would put back for a marked field (from before its first
   * draft, in the form's own shape); null for an unmarked field.
   */
  undoValue: (field: K) => { previous: unknown } | null;
  /**
   * Drop the marks, keeping the values (after a save). With `saved`, the
   * values a save sent (in the shape of `values`), only the marks whose
   * value went with it: a field drafted while the save was out keeps its.
   */
  clear: (saved?: Partial<Record<K, unknown>>) => void;
};

/**
 * Per-field "Drafted" marks for a form the drafter filled. Each mark holds
 * the value from before the draft, so undo restores it through
 * `restore`, and the value the draft set, so a field the user then edits by
 * hand loses its mark (compared with `values` after each render).
 *
 * Args:
 *   values: Each markable field's current value, in a comparable shape.
 *   restore: Writes a previous value back into the form.
 *
 * Returns:
 *   The marks and their actions.
 */
export function useDraftedFields<K extends string>(
  values: Record<K, unknown>,
  restore: (field: K, previous: unknown) => void,
): DraftedFields<K> {
  const [markers, setMarkers] = useState<Map<K, Marker>>(() => new Map());
  const restoreRef = useRef(restore);
  restoreRef.current = restore;
  const markersRef = useRef(markers);
  markersRef.current = markers;
  const valuesRef = useRef(values);
  valuesRef.current = values;

  // A field whose value moved off what the draft set was edited by hand.
  useEffect(() => {
    const edited = [...markers.entries()].filter(
      ([field, marker]) => !isEqual(values[field], marker.applied),
    );
    if (edited.length === 0) return;
    setMarkers((prev) => {
      const next = new Map(prev);
      edited.forEach(([field]) => next.delete(field));
      return next;
    });
  }, [markers, values]);

  const mark = useCallback((field: K, previous: unknown, applied: unknown) => {
    // Compared as `values` has it, not as the form holds it (`previous`).
    const now = valuesRef.current[field];
    setMarkers((prev) => {
      const next = new Map(prev);
      const earlier = prev.get(field);
      if (earlier && isEqual(now, earlier.applied)) {
        // Drafted again: undo still goes back to before the first draft.
        next.set(field, { previous: earlier.previous, applied });
      } else next.set(field, { previous, applied });
      return next;
    });
  }, []);

  const follow = useCallback((field: K, applied: unknown) => {
    setMarkers((prev) => {
      const earlier = prev.get(field);
      if (!earlier) return prev;
      const next = new Map(prev);
      next.set(field, { previous: earlier.previous, applied });
      return next;
    });
  }, []);

  const undo = useCallback((field: K) => {
    const marker = markersRef.current.get(field);
    if (!marker) return;
    restoreRef.current(field, marker.previous);
    setMarkers((prev) => {
      const next = new Map(prev);
      next.delete(field);
      return next;
    });
  }, []);

  const undoValue = useCallback((field: K) => {
    const marker = markersRef.current.get(field);
    return marker ? { previous: marker.previous } : null;
  }, []);

  const clear = useCallback((saved?: Partial<Record<K, unknown>>) => {
    if (!saved) {
      setMarkers(new Map());
      return;
    }
    setMarkers(
      (prev) =>
        new Map(
          [...prev].filter(
            ([field, marker]) => !isEqual(saved[field], marker.applied),
          ),
        ),
    );
  }, []);

  const isDrafted = useCallback((field: K) => markers.has(field), [markers]);

  return {
    fields: [...markers.keys()],
    isDrafted,
    mark,
    follow,
    undo,
    undoValue,
    clear,
  };
}
