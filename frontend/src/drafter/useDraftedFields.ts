import isEqual from 'lodash/isEqual';
import { useCallback, useEffect, useRef, useState } from 'react';

type Marker = { previous: unknown; applied: unknown };

export type DraftedFields<K extends string> = {
  /** The drafted fields, in the order they were marked. */
  fields: K[];
  isDrafted: (field: K) => boolean;
  /**
   * Mark a field the drafter changed. `previous` is what undo puts back; a
   * field drafted twice keeps the value from before the first draft.
   * `applied` is the value it now holds: once the field's value differs, the
   * user edited it by hand and the mark goes.
   */
  mark: (field: K, previous: unknown, applied: unknown) => void;
  /** Put a field's previous value back and drop its mark. */
  undo: (field: K) => void;
  /** Undo every drafted field, last marked first. */
  undoAll: () => void;
  /** Drop every mark, keeping the values (after a save). */
  clear: () => void;
};

/**
 * Per-field "Drafted" marks for a form the drafter filled. Each mark holds
 * the value from before the draft, so undo and undo-all restore it through
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
    setMarkers((prev) => {
      const next = new Map(prev);
      const earlier = prev.get(field);
      if (earlier && isEqual(previous, earlier.applied)) {
        // Drafted again: undo still goes back to before the first draft.
        next.set(field, { previous: earlier.previous, applied });
      } else next.set(field, { previous, applied });
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

  const undoAll = useCallback(() => {
    const entries = [...markersRef.current.entries()].reverse();
    entries.forEach(([field, marker]) =>
      restoreRef.current(field, marker.previous),
    );
    setMarkers(new Map());
  }, []);

  const clear = useCallback(() => setMarkers(new Map()), []);

  const isDrafted = useCallback((field: K) => markers.has(field), [markers]);

  return {
    fields: [...markers.keys()],
    isDrafted,
    mark,
    undo,
    undoAll,
    clear,
  };
}
