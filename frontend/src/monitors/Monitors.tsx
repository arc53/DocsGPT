import { MessageSquare, Pause, Play, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import PageToolbar from '@/components/PageToolbar';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import {
  DescriptionItem,
  DescriptionList,
} from '@/components/ui/description-list';
import { ActionMenu, type MenuOption } from '@/components/ui/dropdown-menu';
import { EmptyState } from '@/components/ui/empty-state';
import { LoadingState } from '@/components/ui/loading-state';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import ConfirmationModal from '@/modals/ConfirmationModal';
import { ActiveState } from '@/models/misc';
import { selectToken } from '@/preferences/preferenceSlice';
import type { AppDispatch } from '@/store';
import {
  EMPTY_VALUE,
  formatCount,
  formatDateTime,
  formatRelative,
} from '@/utils/dateTimeUtils';

import {
  actOnMonitor,
  loadMonitors,
  selectMonitors,
  selectMonitorsState,
} from './monitorsSlice';
import type { Monitor, MonitorStatus } from './types';

const STATUS_VARIANT: Record<MonitorStatus, 'success' | 'warning' | 'neutral'> =
  {
    active: 'success',
    paused: 'warning',
    completed: 'neutral',
    cancelled: 'neutral',
  };

const LIVE: ReadonlySet<MonitorStatus> = new Set(['active', 'paused']);

/** Live monitors first, then finished ones; newest first within each. */
const ordered = (monitors: Monitor[]) => [
  ...monitors.filter((m) => LIVE.has(m.status)),
  ...monitors.filter((m) => !LIVE.has(m.status)),
];

export function MonitorStatusBadge({ status }: { status: MonitorStatus }) {
  const { t } = useTranslation();
  return (
    <Badge variant={STATUS_VARIANT[status] ?? 'neutral'} data-status={status}>
      {t(`monitors.status.${status}`)}
    </Badge>
  );
}

/**
 * Settings → Monitors: what each monitor watches, how often, when it last
 * checked, how many wakes it has left and when it expires, with pause,
 * resume and cancel. Kept current by `monitor.updated` events.
 */
export default function Monitors() {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const monitors = ordered(useSelector(selectMonitors));
  const { loaded, loading, error } = useSelector(selectMonitorsState);
  const [toCancel, setToCancel] = useState<Monitor | null>(null);
  const [cancelState, setCancelState] = useState<ActiveState>('INACTIVE');
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    void dispatch(loadMonitors({ token }));
  }, [dispatch, token]);

  const act = async (monitor: Monitor, action: 'pause' | 'resume') => {
    setActionError(null);
    const result = await dispatch(
      actOnMonitor({ id: monitor.monitor_id, action, token }),
    );
    if (actOnMonitor.rejected.match(result)) {
      setActionError(t('monitors.actionError'));
    }
  };

  const cancel = async () => {
    if (!toCancel) return;
    const result = await dispatch(
      actOnMonitor({ id: toCancel.monitor_id, action: 'cancel', token }),
    );
    if (actOnMonitor.rejected.match(result)) {
      throw new Error(t('monitors.actionError'));
    }
  };

  const sourceLabel = (monitor: Monitor) =>
    t(`monitors.source.${monitor.source_type}`);

  const cadence = (monitor: Monitor) =>
    monitor.interval
      ? t('monitors.every', {
          interval: monitor.interval,
          interpolation: { escapeValue: false },
        })
      : t('monitors.onEvent');

  const lastChecked = (monitor: Monitor) =>
    formatRelative(monitor.last_checked_at) ?? EMPTY_VALUE;

  const wakes = (monitor: Monitor) =>
    `${formatCount(monitor.wakes_left)} / ${formatCount(monitor.max_wakes)}`;

  const expires = (monitor: Monitor) =>
    monitor.expires_at ? formatDateTime(monitor.expires_at) : EMPTY_VALUE;

  const menu = (monitor: Monitor): MenuOption[] => {
    const options: MenuOption[] = [];
    if (monitor.conversation_id) {
      options.push({
        icon: MessageSquare,
        label: t('monitors.openConversation'),
        onClick: () => navigate(`/c/${monitor.conversation_id}`),
      });
    }
    if (monitor.status === 'active') {
      options.push({
        icon: Pause,
        label: t('monitors.pause'),
        onClick: () => void act(monitor, 'pause'),
      });
    }
    if (monitor.status === 'paused') {
      options.push({
        icon: Play,
        label: t('monitors.resume'),
        onClick: () => void act(monitor, 'resume'),
      });
    }
    if (LIVE.has(monitor.status)) {
      options.push({
        icon: Trash2,
        label: t('monitors.cancel'),
        variant: 'destructive',
        separatorBefore: options.length > 0,
        onClick: () => {
          setToCancel(monitor);
          setCancelState('ACTIVE');
        },
      });
    }
    return options;
  };

  const title = (monitor: Monitor) => (
    <div className="flex min-w-0 flex-col gap-0.5">
      <p
        className="text-foreground truncate text-sm font-medium"
        title={monitor.description}
      >
        {monitor.description || t('monitors.untitled')}
      </p>
      <p className="text-muted-foreground truncate text-xs">
        {sourceLabel(monitor)}
        {monitor.target ? (
          <>
            {' · '}
            <span className="font-mono" title={monitor.target}>
              {monitor.target}
            </span>
          </>
        ) : null}
      </p>
      {(monitor.paused_reason || monitor.last_error) && (
        <p
          className="text-muted-foreground text-xs wrap-break-word"
          title={monitor.last_error ?? undefined}
        >
          {monitor.status === 'paused' && monitor.paused_reason
            ? t('monitors.pausedBecause', {
                reason: monitor.paused_reason,
                interpolation: { escapeValue: false },
              })
            : t('monitors.lastError', {
                error: monitor.last_error,
                interpolation: { escapeValue: false },
              })}
        </p>
      )}
    </div>
  );

  const actions = (monitor: Monitor) => {
    const options = menu(monitor);
    return options.length ? (
      <ActionMenu
        options={options}
        triggerLabel={t('monitors.menu', {
          name: monitor.description,
          interpolation: { escapeValue: false },
        })}
      />
    ) : null;
  };

  let body: React.ReactNode;
  if (loading && !loaded) {
    body = <LoadingState fill="block" />;
  } else if (error && !loaded) {
    body = (
      <EmptyState
        tone="destructive"
        illustration="none"
        title={t('monitors.loadError')}
        onRetry={() => void dispatch(loadMonitors({ token }))}
      />
    );
  } else if (monitors.length === 0) {
    body = (
      <EmptyState
        title={t('monitors.empty')}
        description={t('monitors.emptyHint')}
      />
    );
  } else {
    body = (
      <>
        <TableContainer className="hidden lg:block">
          <Table>
            <TableHead>
              <TableRow>
                <TableHeader>{t('monitors.columns.monitor')}</TableHeader>
                <TableHeader>{t('monitors.columns.status')}</TableHeader>
                <TableHeader>{t('monitors.columns.interval')}</TableHeader>
                <TableHeader>{t('monitors.columns.lastChecked')}</TableHeader>
                <TableHeader>{t('monitors.columns.wakesLeft')}</TableHeader>
                <TableHeader>{t('monitors.columns.expires')}</TableHeader>
                <TableHeader align="right">
                  <span className="sr-only">
                    {t('monitors.columns.actions')}
                  </span>
                </TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {monitors.map((monitor) => (
                <TableRow key={monitor.monitor_id} data-status={monitor.status}>
                  <TableCell className="max-w-[320px]">
                    {title(monitor)}
                  </TableCell>
                  <TableCell>
                    <MonitorStatusBadge status={monitor.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground whitespace-nowrap">
                    {cadence(monitor)}
                  </TableCell>
                  <TableCell className="text-muted-foreground whitespace-nowrap">
                    {lastChecked(monitor)}
                  </TableCell>
                  <TableCell className="text-muted-foreground whitespace-nowrap tabular-nums">
                    {wakes(monitor)}
                  </TableCell>
                  <TableCell className="text-muted-foreground whitespace-nowrap">
                    {expires(monitor)}
                  </TableCell>
                  <TableCell align="right">{actions(monitor)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        <ul className="flex flex-col gap-4 lg:hidden">
          {monitors.map((monitor) => (
            <Card key={monitor.monitor_id} variant="filled" asChild>
              <li data-status={monitor.status}>
                <div className="flex items-start justify-between gap-3">
                  {title(monitor)}
                  <div className="flex shrink-0 items-center gap-2">
                    <MonitorStatusBadge status={monitor.status} />
                    {actions(monitor)}
                  </div>
                </div>
                <DescriptionList layout="justified" size="sm">
                  <DescriptionItem label={t('monitors.columns.interval')}>
                    {cadence(monitor)}
                  </DescriptionItem>
                  <DescriptionItem label={t('monitors.columns.lastChecked')}>
                    {lastChecked(monitor)}
                  </DescriptionItem>
                  <DescriptionItem label={t('monitors.columns.wakesLeft')}>
                    {wakes(monitor)}
                  </DescriptionItem>
                  <DescriptionItem label={t('monitors.columns.expires')}>
                    {expires(monitor)}
                  </DescriptionItem>
                </DescriptionList>
              </li>
            </Card>
          ))}
        </ul>
      </>
    );
  }

  return (
    <div className="flex flex-col">
      <PageToolbar intro={t('monitors.subtitle')} divider>
        {actionError && (
          <Alert variant="destructive" className="mb-6">
            {actionError}
          </Alert>
        )}
      </PageToolbar>
      {body}
      <ConfirmationModal
        message={t('monitors.cancelConfirm', {
          name: toCancel?.description ?? '',
          interpolation: { escapeValue: false },
        })}
        description={t('monitors.cancelConsequence')}
        modalState={cancelState}
        setModalState={setCancelState}
        handleSubmit={cancel}
        submitLabel={t('monitors.cancel')}
        error={t('monitors.actionError')}
        variant="destructive"
      />
    </div>
  );
}
