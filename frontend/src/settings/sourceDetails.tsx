import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';

import { Badge } from '../components/ui/badge';
import type { Connection } from '../connectors/types';
import type { Doc } from '../models/misc';
import {
  EMPTY_VALUE,
  formatCount,
  formatDate,
  formatRelative,
} from '../utils/dateTimeUtils';
import { syncSchedule } from './sourceKinds';

/**
 * A source's token count as its Knowledge card prints it: two decimals at
 * most, with k, m or b ("13.08k", "2.47m").
 */
export const formatTokens = (tokens: number): string => {
  const round = (num: number): string =>
    (Math.round((num + Number.EPSILON) * 100) / 100).toString();
  if (tokens >= 1_000_000_000) return round(tokens / 1_000_000_000) + 'b';
  if (tokens >= 1_000_000) return round(tokens / 1_000_000) + 'm';
  if (tokens >= 1_000) return round(tokens / 1_000) + 'k';
  return tokens.toString();
};

/** Where a website source reads from: its one host, or "N sites". */
export const websiteHostsLabel = (
  t: TFunction,
  website: NonNullable<Doc['website']>,
): string =>
  website.hosts.length === 1
    ? website.hosts[0]
    : t('settings.sources.website.sites', { count: website.hosts.length });

/** "via <connection>", with its file count when the list knows it. */
export const connectionLabel = (
  t: TFunction,
  connection: Pick<Connection, 'name'>,
  files?: number | null,
): string =>
  files
    ? t('settings.sources.viaConnectionFiles', {
        name: connection.name,
        count: files,
        files: formatCount(files),
        interpolation: { escapeValue: false },
      })
    : t('settings.sources.viaConnection', {
        name: connection.name,
        interpolation: { escapeValue: false },
      });

/** The schedule a source syncs on, named ("Weekly"), or null with none. */
export const scheduleLabel = (t: TFunction, doc: Doc): string | null => {
  const schedule = syncSchedule(doc);
  return schedule ? t(`settings.sources.syncFrequency.${schedule}`) : null;
};

/**
 * A source's line in a knowledge picker: the facts its Knowledge card shows,
 * joined with " · ", so rows with the same name can be told apart. A
 * website: its host (or "N sites"), pages and schedule. One from the
 * caller's connection: "via <connection> · N files" and the schedule.
 * Anything else: its schedule, else its date with the time, then its
 * tokens. What the list doesn't say is left out.
 *
 * Args:
 *   t: The translator.
 *   doc: The source.
 *   connection: The caller's connection it syncs from, when they can see it.
 *
 * Returns:
 *   The line, or "" when nothing is known.
 */
export const sourceDetailLine = (
  t: TFunction,
  doc: Doc,
  connection?: Pick<Connection, 'name'>,
): string => {
  const schedule = scheduleLabel(t, doc);
  const parts: (string | null | undefined)[] = doc.website
    ? [
        websiteHostsLabel(t, doc.website),
        t('settings.sources.website.pageCount', { count: doc.website.pages }),
        schedule,
      ]
    : connection
      ? [connectionLabel(t, connection, doc.files), schedule]
      : [
          schedule ?? (doc.date ? formatDate(doc.date) : null),
          doc.tokens
            ? t('settings.sources.tokenCount', {
                tokens: formatTokens(+doc.tokens),
              })
            : null,
        ];
  return parts.filter(Boolean).join(' · ');
};

/**
 * A source's detail line on its Knowledge card: the picker's line
 * (`sourceDetailLine`) with the last sync added to the schedule ("Weekly,
 * synced 2 days ago"), and without the token count, which the card's meta
 * line carries.
 *
 * Args:
 *   t: The translator.
 *   doc: The source.
 *   connection: The caller's connection it syncs from, when they can see it.
 *
 * Returns:
 *   The line, or "" when nothing is known.
 */
export const sourceCardLine = (
  t: TFunction,
  doc: Doc,
  connection?: Pick<Connection, 'name'>,
): string => {
  const frequency = scheduleLabel(t, doc);
  const schedule = frequency
    ? t('settings.sources.website.synced', {
        frequency,
        when: formatRelative(doc.date) ?? EMPTY_VALUE,
      })
    : null;
  const parts: (string | null | undefined)[] = doc.website
    ? [
        websiteHostsLabel(t, doc.website),
        t('settings.sources.website.pageCount', { count: doc.website.pages }),
        schedule,
      ]
    : connection
      ? [connectionLabel(t, connection, doc.files), schedule]
      : [schedule ?? (doc.date ? formatDate(doc.date) : null)];
  return parts.filter(Boolean).join(' · ');
};

/** The caller's connection a source syncs from, if it is among theirs. */
export const connectionOf = (
  doc: Doc,
  connections: Connection[],
): Connection | undefined =>
  doc.connectionId
    ? connections.find((c) => c.id === doc.connectionId)
    : undefined;

/** Whether a source is still indexing or failed to, from the lists' `ingestStatus`. */
export const ingestState = (doc: Doc): 'processing' | 'failed' | null =>
  doc.ingestStatus === 'failed' || doc.ingestStatus === 'processing'
    ? doc.ingestStatus
    : null;

/** A source's ingest still running, or failed. */
export function IngestBadge({ status }: { status: 'processing' | 'failed' }) {
  const { t } = useTranslation();
  return status === 'failed' ? (
    <Badge variant="destructive">{t('settings.sources.ingestFailed')}</Badge>
  ) : (
    <Badge variant="neutral">{t('settings.sources.ingestProcessing')}</Badge>
  );
}
