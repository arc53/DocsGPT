import { useTranslation } from 'react-i18next';

import devicesService, { AuditEntry } from '../api/services/devicesService';
import { Button } from '../components/ui/button';
import { LoadMoreStatus } from '../components/ui/load-more-status';
import { useLoadMore } from '../hooks/useLoadMore';
import { formatDateTime } from '../utils/dateTimeUtils';

/** Commands per request; older ones load as the list's end scrolls into view. */
const AUDIT_PAGE_SIZE = 50;

type DeviceAuditListProps = {
  deviceId: string;
  token: string | null;
};

/**
 * A paired device's command history, newest first. It mounts when the
 * "Recent activity" accordion opens (so the first fetch stays lazy), and
 * scrolls inside a capped inner box so the page keeps its length.
 */
export default function DeviceAuditList({
  deviceId,
  token,
}: DeviceAuditListProps) {
  const { t } = useTranslation();
  const feed = useLoadMore<AuditEntry, number>({
    resetKey: deviceId,
    load: async (offset) => {
      const from = offset ?? 0;
      const res = await devicesService.listAudit(
        deviceId,
        token,
        AUDIT_PAGE_SIZE,
        from,
      );
      const entries = res.entries || [];
      return {
        items: entries,
        next: entries.length < AUDIT_PAGE_SIZE ? null : from + entries.length,
      };
    },
  });
  const entries = feed.items;

  if (entries.length === 0) {
    if (feed.loading) {
      return (
        <p className="text-muted-foreground py-2 text-sm">
          {t('settings.devices.auditLoading')}
        </p>
      );
    }
    if (feed.error) {
      return (
        <div className="flex items-center gap-3 py-2">
          <p className="text-destructive text-sm">
            {t('pagination.olderFailed')}
          </p>
          <Button variant="outline" size="sm" onClick={feed.retry}>
            {t('retry')}
          </Button>
        </div>
      );
    }
    return (
      <p className="text-muted-foreground py-2 text-sm">
        {t('settings.devices.auditEmpty')}
      </p>
    );
  }

  return (
    <>
      <div className="scrollbar-overlay max-h-[45svh] overflow-y-auto">
        <ul className="flex flex-col gap-2">
          {entries.map((entry) => (
            <li
              key={entry.id}
              className="bg-muted flex flex-col gap-1 rounded-md px-3 py-2 text-xs"
            >
              <code className="text-foreground block font-mono wrap-anywhere whitespace-pre-wrap">
                {entry.command}
              </code>
              <div className="text-muted-foreground flex flex-wrap gap-3">
                <span>
                  {t('settings.devices.auditDecision')}: {entry.decision}
                </span>
                <span>
                  {t('settings.devices.auditExit')}: {entry.exit_code ?? '-'}
                </span>
                <span>
                  {t('settings.devices.auditDuration')}:{' '}
                  {t('settings.devices.auditDurationValue', {
                    value: entry.duration_ms ?? '-',
                  })}
                </span>
                <span>
                  {entry.created_at ? formatDateTime(entry.created_at) : '-'}
                </span>
              </div>
            </li>
          ))}
        </ul>
        <div ref={feed.sentinelRef} aria-hidden="true" className="h-px" />
      </div>
      {entries.length >= AUDIT_PAGE_SIZE ? (
        <LoadMoreStatus
          loading={feed.loading}
          error={feed.error}
          done={feed.done}
          onRetry={feed.retry}
        />
      ) : null}
    </>
  );
}
