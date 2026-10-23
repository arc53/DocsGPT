import type { Doc } from '../models/misc';

/**
 * What an opened source offers next to Test retrieval: how content gets in.
 * `addFile` for an upload, `addPages` for a website, `syncNow` for a source
 * synced from a connection or on a schedule, `none` for a wiki or a graph
 * (whose Files tab keeps its own action).
 */
export type SourcePrimary = 'addFile' | 'addPages' | 'syncNow' | 'none';

/** Whether the source is a wiki (edited in place, never synced). */
export const isWikiSource = (doc: Doc): boolean =>
  doc.config?.kind === 'wiki' || doc.type === 'wiki';

/** Whether the source is a GraphRAG source. */
export const isGraphSource = (doc: Doc): boolean =>
  doc.config?.kind === 'graphrag';

/**
 * The schedule the source syncs on, or null when it has none (unset or
 * `never`), or is a wiki.
 */
export const syncSchedule = (doc: Doc): string | null =>
  !isWikiSource(doc) && doc.syncFrequency && doc.syncFrequency !== 'never'
    ? doc.syncFrequency
    : null;

/**
 * Whether Sync now can run: the source reads from a connection, a connector,
 * or a remote loader (those store a schedule, `never` included). Never a
 * wiki: a sync would replace its pages.
 */
export const canSyncSource = (doc: Doc): boolean =>
  !isWikiSource(doc) &&
  (!!doc.connectionId ||
    !!doc.type?.startsWith('connector') ||
    !!doc.syncFrequency);

/**
 * Whether the source's content comes from a connection or a schedule,
 * whatever its stored type (an S3 or GitHub source is typed by its loader).
 * Such a source opens with the synced header: provider badge, schedule,
 * Sync now, and no Add file (a sync replaces the files).
 */
export const isSyncedSource = (doc: Doc): boolean =>
  !isWikiSource(doc) &&
  (!!doc.connectionId ||
    !!doc.type?.startsWith('connector') ||
    !!syncSchedule(doc));

/**
 * The opened source's primary action (see {@link SourcePrimary}). A website
 * keeps Add pages even when synced: its Sync now is in the ⋯.
 */
export function sourcePrimary(doc: Doc): SourcePrimary {
  if (isWikiSource(doc) || isGraphSource(doc)) return 'none';
  if (doc.website) return 'addPages';
  if (isSyncedSource(doc)) return 'syncNow';
  // A source without a file tree (an older, flat one) can't take a file.
  return doc.isNested ? 'addFile' : 'none';
}
