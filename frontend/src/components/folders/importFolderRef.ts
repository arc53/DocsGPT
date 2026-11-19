/** A folder entry of an agent import plan (`sources` with `type: folder`). */
export type ImportFolderEntry = {
  name: string;
  /** The entry's key in the file, or `folder-N` by its place. */
  key?: string | null;
  /** The names down to it joined with `/`, when the file carries them. */
  path_key?: string | null;
};

/**
 * The name each folder entry of an import plan goes by in
 * `resolution.folders`, the way the server reads it: its `key`, else its
 * `path_key`, else its name, whichever no other entry of the file shares (the
 * server ignores a mapping that fits two entries).
 *
 * Args:
 *   entries: The plan's folder entries, in order.
 *
 * Returns:
 *   One reference per entry, or null for an entry nothing names alone.
 */
export function importFolderRefs(
  entries: ImportFolderEntry[],
): (string | null)[] {
  const labels = (entry: ImportFolderEntry): string[] => [
    ...new Set(
      [entry.key, entry.path_key, entry.name].filter(
        (label): label is string => typeof label === 'string' && label !== '',
      ),
    ),
  ];
  const uses = new Map<string, number>();
  for (const entry of entries)
    for (const label of labels(entry))
      uses.set(label, (uses.get(label) ?? 0) + 1);
  return entries.map(
    (entry) => labels(entry).find((label) => uses.get(label) === 1) ?? null,
  );
}
