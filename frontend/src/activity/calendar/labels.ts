import type { TFunction } from 'i18next';

import type { CalendarEvent, SyncEvent } from './types';

/** An event's name: a schedule's own, or "Daily sync" for a sync batch. */
export function eventTitle(event: CalendarEvent, t: TFunction): string {
  return event.kind === 'sync'
    ? t(`activity.now.syncBatch.${event.frequency}`)
    : (event.name ?? '');
}

/** "3 sources · 1 needs reconnecting": what a sync batch covers. */
export function syncSummary(event: SyncEvent, t: TFunction): string {
  const blocked = event.sources.filter((source) => source.blocked).length;
  return [
    t('activity.now.syncSources', { count: event.sources.length - blocked }),
    blocked > 0 && t('activity.now.syncBlocked', { count: blocked }),
  ]
    .filter(Boolean)
    .join(' · ');
}
