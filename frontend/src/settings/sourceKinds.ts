import type { Doc } from '../models/misc';

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
 * Whether the caller's own connector source has lost its connection (the
 * account was removed; the list says `connectionId: null`): its sync has no
 * account to read with, and the server refuses it (`connection_missing`). A
 * team editor's sync uses the owner's account, which only the server sees.
 */
const lostConnection = (doc: Doc): boolean =>
  !!doc.type?.startsWith('connector') &&
  doc.connectionId === null &&
  doc.access === 'owner';

/**
 * Whether Sync now can run: the source reads from a connection, a connector,
 * or a remote loader (those store a schedule, `never` included). Never a
 * wiki: a sync would replace its pages; never a connector source of the
 * caller's whose connection is gone.
 */
export const canSyncSource = (doc: Doc): boolean =>
  !isWikiSource(doc) &&
  !lostConnection(doc) &&
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
 * Whether Sync now is the opened source's primary action, next to Test
 * retrieval, rather than in its ⋯: a source synced from a connection or on a
 * schedule. Not a graph (its Files tab keeps its own action) nor a website,
 * which keeps Add pages even when synced.
 */
export const syncNowIsPrimary = (doc: Doc): boolean =>
  !isGraphSource(doc) && !doc.website && isSyncedSource(doc);

/** The Knowledge filter's values: All, the four content kinds, and Shared. */
export const SOURCE_KINDS = [
  'all',
  'files',
  'websites',
  'synced',
  'wikis',
  'shared',
] as const;
export type SourceKindFilter = (typeof SOURCE_KINDS)[number];

/** The four content kinds; every source is exactly one of them. */
export type SourceKind = Exclude<SourceKindFilter, 'all' | 'shared'>;

/**
 * Which content kind a source is, as the backend's `source_kind` decides it
 * (`docsgpt/api/user/sources/routes.py`), so the counts the Knowledge page
 * gets from the server match the ones a picker counts itself. A source that
 * fits more than one takes the first:
 *
 * 1. `wikis`: `isWikiSource`; a wiki never syncs, whatever schedule it kept.
 * 2. `websites`: the list sends a `website` summary (a Website source, or one
 *    made by the url, crawler or sitemap loaders), scheduled or not.
 * 3. `synced`: `isSyncedSource` (a connection, a connector type, a schedule).
 * 4. `files`: the rest: uploads, a graph source, a loader that never syncs.
 *
 * Args:
 *   doc: The source, from either list.
 *
 * Returns:
 *   Its kind.
 */
export const sourceKindOf = (doc: Doc): SourceKind => {
  if (isWikiSource(doc)) return 'wikis';
  if (doc.website) return 'websites';
  if (isSyncedSource(doc)) return 'synced';
  return 'files';
};

/**
 * Whether a source passes a Knowledge filter: All; Shared, a team's source of
 * any kind (so the counts don't sum to All); otherwise its content kind.
 */
export const matchesKind = (kind: SourceKindFilter, doc: Doc): boolean => {
  if (kind === 'all') return true;
  if (kind === 'shared') return doc.ownership === 'team';
  return sourceKindOf(doc) === kind;
};

/** How many sources each Knowledge filter keeps. */
export const kindCounts = (docs: Doc[]): Record<SourceKindFilter, number> =>
  Object.fromEntries(
    SOURCE_KINDS.map((kind) => [
      kind,
      docs.filter((doc) => matchesKind(kind, doc)).length,
    ]),
  ) as Record<SourceKindFilter, number>;
