import { X } from 'lucide-react';
import { useCallback, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { Button } from '../components/ui/button';

import {
  dismissShareNotification,
  selectDismissedShareNotifications,
  selectRecentEvents,
  type SSEEvent,
} from './notificationsSlice';

// Backlog replay on reload re-delivers up to ~24h of events; skip anything
// older than the stream-retention window so a stale share doesn't pop.
const MAX_AGE_MS = 24 * 60 * 60 * 1000;
// Informational toasts auto-dismiss after a beat (and persist the dismissal,
// so backlog replay won't re-pop them) — unlike the action-required tool
// approval toast, which stays until acted on.
const AUTO_DISMISS_MS = 8000;
const MAX_VISIBLE = 3;

const TEAM_NOTIFICATION_TYPES = new Set([
  'team.member_added',
  'resource.shared',
]);

/**
 * A single team-sharing toast that owns its OWN auto-dismiss timer, keyed on
 * its event id. Per-toast (rather than a shared parent timer) so a newly
 * arriving sibling toast can't reset an in-flight toast's countdown.
 */
function ShareToast({
  id,
  title,
  body,
  dismissLabel,
  onDismiss,
}: {
  id: string;
  title: string;
  body: string;
  dismissLabel: string;
  onDismiss: (id: string) => void;
}) {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(id), AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [id, onDismiss]);

  return (
    <div className="border-border bg-card shadow-toast w-[271px] overflow-hidden rounded-2xl border">
      <div className="bg-accent/50 dark:bg-muted flex items-center justify-between px-4 py-3">
        <h3 className="dark:text-foreground text-sm leading-[16.5px] font-medium text-black">
          {title}
        </h3>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={() => onDismiss(id)}
          className="h-8 w-8 p-0 text-black opacity-70 transition-opacity hover:bg-transparent hover:opacity-100 dark:text-white"
          aria-label={dismissLabel}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="px-5 py-3">
        <p className="dark:text-muted-foreground text-sm leading-[18px] font-normal text-black">
          {body}
        </p>
      </div>
    </div>
  );
}

/**
 * Transient toasts for team-sharing events (``team.member_added`` and
 * ``resource.shared``) delivered over the per-user SSE channel. Mirrors the
 * ToolApprovalToast surface, but auto-dismisses since these are purely
 * informational. Dismissal (manual or timed) is persisted so the SSE backlog
 * replay on reload doesn't re-surface an already-seen notification.
 */
export default function TeamNotificationToast() {
  const dispatch = useDispatch();
  const { t } = useTranslation();
  const events = useSelector(selectRecentEvents);
  const dismissed = useSelector(selectDismissedShareNotifications);
  const dismissedSet = useMemo(() => new Set(dismissed), [dismissed]);

  const onDismiss = useCallback(
    (id: string) => dispatch(dismissShareNotification(id)),
    [dispatch],
  );

  const now = Date.now();
  const visible: SSEEvent[] = [];
  const seen = new Set<string>();
  for (const event of events) {
    if (!TEAM_NOTIFICATION_TYPES.has(event.type)) continue;
    if (!event.id || dismissedSet.has(event.id) || seen.has(event.id)) continue;
    if (event.ts) {
      const age = now - Date.parse(event.ts);
      if (Number.isFinite(age) && age > MAX_AGE_MS) continue;
    }
    seen.add(event.id);
    visible.push(event);
    if (visible.length >= MAX_VISIBLE) break;
  }

  if (visible.length === 0) return null;

  const describe = (event: SSEEvent): { title: string; body: string } => {
    const p = (event.payload ?? {}) as Record<string, unknown>;
    if (event.type === 'team.member_added') {
      const team = (p.team_name as string) || (p.team_id as string) || '';
      const role =
        p.role === 'team_admin'
          ? t('settings.teams.roleAdmin')
          : t('settings.teams.roleMember');
      return {
        title: t('notifications.memberAddedTitle'),
        body: t('notifications.memberAddedBody', { team, role }),
      };
    }
    // resource.shared
    const type = t(`settings.teams.resourceType.${p.resource_type}`, {
      defaultValue: String(p.resource_type ?? 'resource'),
    });
    const access =
      p.access_level === 'editor'
        ? t('teamAccess.editor')
        : t('teamAccess.viewer');
    const name = (p.resource_name as string) || '';
    return {
      title: t('notifications.sharedTitle'),
      body: name
        ? t('notifications.sharedBody', { name, type, access })
        : t('notifications.sharedBodyNoName', { type, access }),
    };
  };

  return (
    // Standard bottom-right toast rail. UploadToast / ToolApprovalToast use the
    // same corner but rarely co-occur with team-share toasts.
    <div
      className="fixed right-4 bottom-4 z-50 flex max-w-md flex-col gap-2"
      onMouseDown={(e) => e.stopPropagation()}
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {visible.map((event) => {
        const { title, body } = describe(event);
        return (
          <ShareToast
            key={event.id}
            id={event.id as string}
            title={title}
            body={body}
            dismissLabel={t('notifications.dismiss')}
            onDismiss={onDismiss}
          />
        );
      })}
    </div>
  );
}
