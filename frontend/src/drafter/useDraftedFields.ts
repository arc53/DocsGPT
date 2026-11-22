import isEqual from 'lodash/isEqual';
import { useCallback, useEffect, useRef, useState } from 'react';

type Marker = {
  previous: unknown;
  applied: unknown;
  /** The linked fields' values (comparable) as the drafter last left them. */
  linked: Record<string, unknown>;
};

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
  /**
   * Put a field's previous value back and drop its mark, and the same for
   * the fields linked with it.
   */
  undo: (field: K) => void;
  /**
   * What undo would put back for a marked field (from before its first
   * draft, in the form's own shape); null for an unmarked field.
   */
  undoValue: (field: K) => { previous: unknown } | null;
  /**
   * Drop the marks, keeping the values (after a save). With `saved`, the
   * values a save sent (in the shape of `values`), only the marks whose
   * value went with it: a field drafted while the save was out keeps its,
   * and so do the marked fields linked with it.
   */
  clear: (saved?: Partial<Record<K, unknown>>) => void;
};

/**
 * Per-field "Drafted" marks for a form the drafter filled. Each mark holds
 * the value from before the draft, so undo restores it through
 * `restore`, and the value the draft set, so a field the user then edits by
 * hand loses its mark (compared with `values` after each render).
 *
 * Fields one control shows (the knowledge picker's sources and folders) can
 * be linked: a hand edit to any of them, marked or not, drops the marks of
 * all, and undo of one puts back every marked one.
 *
 * Args:
 *   values: Each markable field's current value, in a comparable shape.
 *   restore: Writes a previous value back into the form.
 *   linked: Groups of fields that share one control.
 *
 * Returns:
 *   The marks and their actions.
 */
export function useDraftedFields<K extends string>(
  values: Record<K, unknown>,
  restore: (field: K, previous: unknown) => void,
  linked: readonly (readonly K[])[] = [],
): DraftedFields<K> {
  const [markers, setMarkers] = useState<Map<K, Marker>>(() => new Map());
  const restoreRef = useRef(restore);
  restoreRef.current = restore;
  const markersRef = useRef(markers);
  markersRef.current = markers;
  const valuesRef = useRef(values);
  valuesRef.current = values;
  const linkedRef = useRef(linked);
  linkedRef.current = linked;
  /** The field and the fields linked with it. */
  const withLinked = useCallback(
    (field: K): readonly K[] =>
      linkedRef.current.find((group) => group.includes(field)) ?? [field],
    [],
  );

  /**
   * After the drafter set `field` to `value`, the marked fields linked with
   * it expect that value, so it doesn't read as a hand edit.
   */
  const relink = useCallback(
    (next: Map<K, Marker>, field: K, value: unknown) =>
      withLinked(field).forEach((each) => {
        const marker = next.get(each);
        if (each !== field && marker)
          next.set(each, {
            ...marker,
            linked: { ...marker.linked, [field]: value },
          });
      }),
    [withLinked],
  );

  // A field whose value, or a linked field's, moved off what the drafter
  // left was edited by hand.
  useEffect(() => {
    const edited = [...markers.entries()].filter(
      ([field, marker]) =>
        !isEqual(values[field], marker.applied) ||
        Object.entries(marker.linked).some(
          ([each, value]) => !isEqual(values[each as K], value),
        ),
    );
    if (edited.length === 0) return;
    setMarkers((prev) => {
      const next = new Map(prev);
      edited.forEach(([field]) =>
        withLinked(field).forEach((each) => next.delete(each)),
      );
      return next;
    });
  }, [markers, values, withLinked]);

  const mark = useCallback(
    (field: K, previous: unknown, applied: unknown) => {
      // Compared as `values` has it, not as the form holds it (`previous`).
      const now = valuesRef.current[field];
      setMarkers((prev) => {
        const next = new Map(prev);
        const earlier = prev.get(field);
        // A linked field marked in the same draft holds what it set; any
        // other holds its value now.
        const linkedValues = Object.fromEntries(
          withLinked(field)
            .filter((each) => each !== field)
            .map((each) => [
              each,
              next.has(each)
                ? next.get(each)!.applied
                : valuesRef.current[each],
            ]),
        );
        // Drafted again: undo still goes back to before the first draft.
        const first =
          earlier && isEqual(now, earlier.applied)
            ? earlier.previous
            : previous;
        next.set(field, { previous: first, applied, linked: linkedValues });
        relink(next, field, applied);
        return next;
      });
    },
    [withLinked, relink],
  );

  const follow = useCallback(
    (field: K, applied: unknown) => {
      setMarkers((prev) => {
        const earlier = prev.get(field);
        // An unmarked field stays unmarked; marked ones linked with it
        // expect its new value.
        const linkedMarked = withLinked(field).some(
          (each) => each !== field && prev.has(each),
        );
        if (!earlier && !linkedMarked) return prev;
        const next = new Map(prev);
        if (earlier) next.set(field, { ...earlier, applied });
        relink(next, field, applied);
        return next;
      });
    },
    [withLinked, relink],
  );

  const undo = useCallback(
    (field: K) => {
      const fields = withLinked(field).filter((each) =>
        markersRef.current.has(each),
      );
      if (fields.length === 0) return;
      fields.forEach((each) =>
        restoreRef.current(each, markersRef.current.get(each)!.previous),
      );
      setMarkers((prev) => {
        const next = new Map(prev);
        fields.forEach((each) => next.delete(each));
        return next;
      });
    },
    [withLinked],
  );

  const undoValue = useCallback((field: K) => {
    const marker = markersRef.current.get(field);
    return marker ? { previous: marker.previous } : null;
  }, []);

  const clear = useCallback(
    (saved?: Partial<Record<K, unknown>>) => {
      if (!saved) {
        setMarkers(new Map());
        return;
      }
      setMarkers((prev) => {
        // A mark kept keeps the marks linked with it: undo restores them
        // together.
        const kept = new Set(
          [...prev]
            .filter(([field, marker]) => !isEqual(saved[field], marker.applied))
            .flatMap(([field]) => withLinked(field)),
        );
        return new Map([...prev].filter(([field]) => kept.has(field)));
      });
    },
    [withLinked],
  );

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
