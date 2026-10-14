import {
  ArrowRight,
  Braces,
  CalendarClock,
  CalendarX2,
  Clock,
  FileUp,
  Globe,
  MessageSquare,
  Plug,
  Radar,
  RefreshCw,
  Repeat,
  SquareTerminal,
  UserCheck,
  Webhook,
  Workflow,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Link, useNavigate } from 'react-router-dom';

import PageToolbar from '@/components/PageToolbar';
import StatCard from '@/components/StatCard';
import { Avatar } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { LoadingState } from '@/components/ui/loading-state';
import { Progress } from '@/components/ui/progress';
import { SectionHeader } from '@/components/ui/section-header';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { cn } from '@/lib/utils';

import { agentLogsPath, agentSchedulesPath } from '../agents/paths';
import { setSchedulePaused } from '../agents/schedules/schedulesSlice';
import activityService from '../api/services/activityService';
import { cancelBackgroundJob } from '../backgroundJobs/backgroundSlice';
import {
  connectionNeedsSignIn,
  selectConnections,
} from '../connectors/connectorsSlice';
import { selectMonitors } from '../monitors/monitorsSlice';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import { formatRelative } from '../utils/dateTimeUtils';
import {
  loadActivityNow,
  selectActivityError,
  selectActivityNow,
} from './activitySlice';
import { useActivitySummary } from './ActivityNavBadge';
import { formatElapsed, formatRunTime, workflowStep } from './format';
import { useClock } from './useClock';
import {
  ACTIVITY_CALENDAR_PATH,
  ACTIVITY_MONITORS_PATH,
  ACTIVITY_SCHEDULES_PATH,
} from './paths';
import type {
  ApprovalItem,
  PausedScheduleItem,
  RunningItem,
  RunningKind,
  ScheduleUpNext,
  SyncUpNext,
  UpNextItem,
} from './types';

// Names and dates carry slashes: React escapes on render.
const NO_ESCAPE = { interpolation: { escapeValue: false } } as const;

type Filter = 'all' | 'chats' | 'automations' | 'knowledge';

const FILTER_KINDS: Record<Exclude<Filter, 'all'>, RunningKind[]> = {
  chats: ['chat', 'job'],
  automations: ['api', 'schedule', 'workflow', 'webhook'],
  knowledge: ['ingest'],
};

/** Rows of "Up next" and "Watching" before the "All …" link takes over. */
const SIDE_LIST_LIMIT = 6;

const KIND_ICON: Record<RunningKind, LucideIcon> = {
  chat: MessageSquare,
  api: Braces,
  job: Wrench,
  schedule: CalendarClock,
  workflow: Workflow,
  webhook: Webhook,
  ingest: FileUp,
};

/** A row's leading tile: the muted icon tile, or a status-tinted one. */
function KindIcon({
  icon: Icon,
  tone = 'muted',
}: {
  icon: LucideIcon;
  tone?: 'muted' | 'warning' | 'destructive';
}) {
  if (tone === 'muted') {
    return (
      <Avatar variant="icon" size="sm" shape="square">
        <Icon aria-hidden className="size-4" />
      </Avatar>
    );
  }
  return (
    <span
      className={cn(
        'grid size-8 shrink-0 place-items-center rounded-md',
        tone === 'warning'
          ? 'bg-warning/10 text-warning'
          : 'bg-destructive/10 text-destructive',
      )}
    >
      <Icon aria-hidden className="size-4" />
    </span>
  );
}

function RunningBadge({ label }: { label: string }) {
  return (
    <Badge variant="info">
      <span
        aria-hidden
        className="bg-info size-1.5 animate-pulse rounded-full motion-reduce:animate-none"
      />
      {label}
    </Badge>
  );
}

/** Joins the parts of a meta line with a middle dot, skipping empty ones. */
const meta = (...parts: (string | null | undefined | false)[]) =>
  parts.filter(Boolean).join(' · ');

/**
 * Activity › Now: what runs this minute, what waits for the user, what runs
 * in the next day and what the assistant is watching. The snapshot is kept
 * loaded app-wide (`useActivityLoader`) and refetched after the events that
 * change it.
 */
export default function Now() {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const snapshot = useSelector(selectActivityNow);
  const failed = useSelector(selectActivityError);
  const connections = useSelector(selectConnections);
  const monitors = useSelector(selectMonitors);
  const summary = useActivitySummary();
  const clock = useClock();
  const [filter, setFilter] = useState<Filter>('all');
  // Rows whose Stop / Cancel / Resume is on its way.
  const [pending, setPending] = useState<Record<string, true>>({});
  const [stopError, setStopError] = useState<string | null>(null);

  const busy = (id: string) => Boolean(pending[id]);
  const withPending = async (id: string, work: () => Promise<unknown>) => {
    setPending((current) => ({ ...current, [id]: true }));
    try {
      await work();
    } finally {
      setPending((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
    }
  };

  if (!snapshot) {
    return failed ? (
      <EmptyState
        tone="destructive"
        title={t('activity.now.loadError')}
        onRetry={() => dispatch(loadActivityNow())}
      />
    ) : (
      <LoadingState fill="block" />
    );
  }

  const reconnects = (connections ?? []).filter(connectionNeedsSignIn);
  const watching = monitors.filter((monitor) => monitor.status === 'active');
  const running =
    filter === 'all'
      ? snapshot.running
      : snapshot.running.filter((item) =>
          FILTER_KINDS[filter].includes(item.kind),
        );
  const firstApproval = snapshot.needs_you.find(
    (item): item is ApprovalItem => item.kind === 'approval',
  );
  const background = snapshot.running.filter(
    (item) => item.kind === 'job',
  ).length;
  // The first run still ahead: an overdue one is due now, not next.
  const next = snapshot.up_next.find(
    (item) => Date.parse(item.next_run_at) >= clock,
  );

  const stop = (item: RunningItem) =>
    withPending(item.id, async () => {
      setStopError(null);
      try {
        await activityService.stopMessage(item.message_id as string, token);
      } catch {
        setStopError(t('activity.now.stopFailed'));
      }
    });

  const runningTitle = (item: RunningItem) =>
    item.title ||
    item.agent_name ||
    t(`activity.kind.${item.kind}`, { defaultValue: item.kind });

  /** "Step 3 of 5", "Draft reply": a workflow run's step, last on the meta line. */
  const stepParts = (item: RunningItem): string[] | null => {
    const step = workflowStep(item.workflow_progress);
    if (!step) return null;
    return [
      step.total
        ? t('activity.now.stepOf', { step: step.step, total: step.total })
        : t('activity.now.step', { step: step.step }),
      step.title ?? '',
    ];
  };

  const runningMeta = (item: RunningItem): string => {
    const kind = t(`activity.kind.${item.kind}`);
    const step = stepParts(item);
    switch (item.kind) {
      case 'chat':
        return meta(
          item.workflow ? t('activity.kind.workflow') : kind,
          item.agent_name,
          ...(step ?? [
            item.status === 'pending'
              ? t('activity.now.thinking')
              : t('activity.now.writing'),
          ]),
        );
      case 'api':
        return meta(
          kind,
          item.workflow ? t('activity.kind.workflow') : null,
          t('activity.now.apiRequests', { count: item.count ?? 1 }),
        );
      case 'job':
        return meta(
          item.job_kind === 'code_exec' ? t('activity.kind.code') : kind,
          item.tool_label ?? item.tool_name,
          item.agent_name,
        );
      case 'schedule':
        return meta(
          kind,
          item.agent_name,
          ...(step ?? [
            item.trigger_source === 'manual'
              ? t('activity.now.ranByHand')
              : item.scheduled_for &&
                t('activity.now.due', {
                  ...NO_ESCAPE,
                  time: formatRunTime(item.scheduled_for, clock),
                }),
          ]),
        );
      case 'ingest':
        return meta(
          kind,
          item.operation &&
            t(`activity.now.operation.${item.operation}`, {
              defaultValue: '',
            }),
          item.stage === 'reading'
            ? t('activity.now.reading')
            : item.total_chunks
              ? t('activity.now.chunks', {
                  done: item.embedded_chunks ?? 0,
                  total: item.total_chunks,
                })
              : null,
        );
      default:
        return meta(
          kind,
          item.workflow ? t('activity.kind.workflow') : null,
          ...(step ?? []),
        );
    }
  };

  const openRunning = (item: RunningItem) => {
    switch (item.kind) {
      case 'chat':
      case 'job':
        if (item.conversation_id) navigate(`/c/${item.conversation_id}`);
        break;
      case 'schedule':
        navigate(
          item.agent_id
            ? agentSchedulesPath(item.agent_id)
            : ACTIVITY_SCHEDULES_PATH,
        );
        break;
      case 'ingest':
        navigate('/settings/knowledge');
        break;
      default:
        if (item.agent_id) navigate(agentLogsPath(item.agent_id));
    }
  };

  const canOpen = (item: RunningItem) =>
    item.kind === 'chat' || item.kind === 'job'
      ? Boolean(item.conversation_id)
      : item.kind === 'workflow' ||
          item.kind === 'webhook' ||
          item.kind === 'api'
        ? Boolean(item.agent_id)
        : true;

  const ghostButton = (
    label: string,
    onClick: () => void,
    options: { destructive?: boolean; disabled?: boolean } = {},
  ) => (
    <Button
      type="button"
      variant={options.destructive ? 'ghost-destructive' : 'ghost-muted'}
      size="sm"
      shape="pill"
      disabled={options.disabled}
      onClick={onClick}
    >
      {label}
    </Button>
  );

  const runningRow = (item: RunningItem) => {
    const Icon =
      item.kind === 'job' && item.job_kind === 'code_exec'
        ? SquareTerminal
        : KIND_ICON[item.kind];
    const percent =
      typeof item.progress === 'number'
        ? Math.round(item.progress * 100)
        : null;
    // A workflow's bar says which step it is on; the meta line already
    // counts the steps, so it has no percentage beside it.
    const progress =
      percent ?? workflowStep(item.workflow_progress)?.percent ?? null;
    const tail =
      item.kind === 'job' && (item.status_message || item.output_tail);
    return (
      <li
        key={`${item.kind}:${item.id}`}
        data-kind={item.kind}
        className="flex items-start gap-3 px-4 py-3"
      >
        <KindIcon icon={Icon} />
        <div className="min-w-0 flex-1">
          <p className="text-foreground truncate text-sm font-medium">
            {runningTitle(item)}
          </p>
          <p className="text-muted-foreground truncate text-xs">
            {runningMeta(item)}
          </p>
          {(progress !== null || tail) && (
            <div className="mt-2 flex items-center gap-3">
              {progress !== null && (
                <Progress size="sm" value={progress} className="max-w-48" />
              )}
              {tail ? (
                <span className="text-muted-foreground truncate font-mono text-xs">
                  {String(tail).split('\n').filter(Boolean).pop()}
                </span>
              ) : (
                percent !== null && (
                  <span className="text-muted-foreground text-xs tabular-nums">
                    {percent}%
                  </span>
                )
              )}
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-muted-foreground hidden w-12 text-right text-xs tabular-nums sm:inline">
            {formatElapsed(item.started_at, clock)}
          </span>
          {item.kind === 'job' ? (
            <Badge variant="neutral" className="hidden sm:inline-flex">
              {t('activity.now.background')}
            </Badge>
          ) : item.kind !== 'ingest' ? (
            <span className="hidden sm:inline-flex">
              <RunningBadge label={t('activity.now.running')} />
            </span>
          ) : null}
          {item.kind === 'chat' &&
            item.message_id &&
            ghostButton(t('activity.now.stop'), () => void stop(item), {
              destructive: true,
              disabled: busy(item.id),
            })}
          {item.kind === 'job' &&
            item.job_id &&
            ghostButton(
              t('activity.now.cancel'),
              () =>
                void withPending(item.id, () =>
                  dispatch(cancelBackgroundJob(item.job_id as string)),
                ),
              {
                destructive: true,
                disabled: busy(item.id) || item.cancel_requested,
              },
            )}
          {canOpen(item) &&
            ghostButton(t('activity.now.open'), () => openRunning(item))}
        </div>
      </li>
    );
  };

  const outlineButton = (
    label: ReactNode,
    onClick: () => void,
    disabled = false,
  ) => (
    <Button
      type="button"
      variant="outline"
      size="sm"
      shape="pill"
      disabled={disabled}
      onClick={onClick}
    >
      {label}
    </Button>
  );

  const approvalRow = (item: ApprovalItem) => (
    <ListRow
      key={item.id}
      leading={<KindIcon icon={UserCheck} tone="warning" />}
      title={
        item.tools.length
          ? t('activity.now.approve', {
              ...NO_ESCAPE,
              tools: item.tools.join(', '),
            })
          : t('activity.now.approveAction')
      }
      description={meta(
        item.title,
        item.agent_name,
        item.expires_at &&
          t('activity.now.expires', {
            ...NO_ESCAPE,
            time: formatRelative(item.expires_at, { future: true }),
          }),
      )}
      trailing={
        <div className="flex shrink-0 items-center gap-2">
          <Badge variant="warning" className="hidden sm:inline-flex">
            {t('activity.now.approval')}
          </Badge>
          {outlineButton(t('activity.now.review'), () =>
            navigate(`/c/${item.conversation_id}`),
          )}
        </div>
      }
    />
  );

  const pausedRow = (item: PausedScheduleItem) => (
    <ListRow
      key={item.id}
      leading={<KindIcon icon={CalendarX2} tone="destructive" />}
      title={t('activity.now.pausedAfter', {
        ...NO_ESCAPE,
        name: item.title ?? '',
        count: item.failures,
      })}
      description={meta(
        item.agent_name,
        item.last_error_type
          ? t(`activity.now.errorType.${item.last_error_type}`, {
              defaultValue: item.last_error_type,
            })
          : null,
        item.last_failed_at && formatRelative(item.last_failed_at),
      )}
      trailing={
        <div className="flex shrink-0 items-center gap-2">
          <span className="hidden sm:inline-flex">
            {ghostButton(t('activity.now.viewRuns'), () =>
              navigate(
                item.agent_id
                  ? agentSchedulesPath(item.agent_id)
                  : ACTIVITY_SCHEDULES_PATH,
              ),
            )}
          </span>
          {outlineButton(
            t('agents.schedules.resume'),
            () =>
              void withPending(item.id, async () => {
                await dispatch(
                  setSchedulePaused({
                    id: item.schedule_id,
                    action: 'resume',
                    token,
                  }),
                );
                await dispatch(loadActivityNow());
              }),
            busy(item.id),
          )}
        </div>
      }
    />
  );

  /** When an Up next item runs: its time, or "Overdue" when the scheduler is behind. */
  const upNextLeading = (item: UpNextItem) =>
    Date.parse(item.next_run_at) < clock ? (
      <span className="text-warning w-16 shrink-0 text-xs font-medium">
        {t('agents.schedules.stats.overdue')}
      </span>
    ) : (
      <span className="text-foreground w-16 shrink-0 text-xs font-medium tabular-nums">
        {formatRunTime(item.next_run_at, clock)}
      </span>
    );

  const upNextName = (item: UpNextItem) =>
    item.kind === 'sync'
      ? t(`activity.now.syncBatch.${item.frequency}`)
      : (item.name ?? '');

  const scheduleUpNextRow = (item: ScheduleUpNext) => (
    <ListRow
      key={item.id}
      interactive
      asChild
      leading={upNextLeading(item)}
      title={item.name ?? ''}
      description={meta(
        item.agent_name ??
          (item.origin_conversation_name
            ? t('activity.now.fromChat', {
                ...NO_ESCAPE,
                name: item.origin_conversation_name,
              })
            : t('activity.schedules.createdInChat')),
        item.runs_in_window > 1
          ? t('activity.now.timesToday', { count: item.runs_in_window })
          : item.trigger_type === 'once'
            ? t('activity.now.oneTime')
            : null,
      )}
      trailing={
        item.trigger_type === 'once' ? (
          <Clock aria-hidden className="text-muted-foreground size-3.5" />
        ) : (
          <Repeat aria-hidden className="text-muted-foreground size-3.5" />
        )
      }
    >
      <Link
        to={
          item.agent_id
            ? agentSchedulesPath(item.agent_id)
            : ACTIVITY_SCHEDULES_PATH
        }
      />
    </ListRow>
  );

  // "Daily sync · 4 sources" over the source names (D4).
  const syncUpNextRow = (item: SyncUpNext) => (
    <ListRow
      key={item.id}
      interactive
      asChild
      leading={upNextLeading(item)}
      title={meta(
        upNextName(item),
        t('activity.now.syncSources', { count: item.sources.length }),
      )}
      description={meta(
        item.sources.join(', '),
        item.blocked.length > 0 &&
          t('activity.now.syncBlocked', { count: item.blocked.length }),
      )}
      trailing={
        <RefreshCw aria-hidden className="text-muted-foreground size-3.5" />
      }
    >
      <Link to="/settings/knowledge" />
    </ListRow>
  );

  const upNextRow = (item: UpNextItem) =>
    item.kind === 'sync' ? syncUpNextRow(item) : scheduleUpNextRow(item);

  const sideHeader = (title: string, to: string, link: string) => (
    <SectionHeader
      className="mb-3"
      title={title}
      actions={
        <Button variant="link" size="sm" className="-mr-3" asChild>
          <Link to={to}>
            {link}
            <ArrowRight aria-hidden className="size-3" />
          </Link>
        </Button>
      }
    />
  );

  return (
    <>
      <PageToolbar intro={t('activity.now.subtitle')} />
      <div className="flex flex-col gap-10">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard
            label={t('activity.now.stats.running')}
            value={summary.running}
            sub={
              background > 0
                ? t('activity.now.stats.background', { count: background })
                : undefined
            }
          />
          <StatCard
            label={t('activity.now.stats.needsYou')}
            value={summary.needsYou}
            valueTone={summary.needsYou > 0 ? 'warning' : undefined}
            sub={
              firstApproval?.expires_at
                ? t('activity.now.stats.approvalExpires', {
                    ...NO_ESCAPE,
                    time: formatRelative(firstApproval.expires_at, {
                      future: true,
                    }),
                  })
                : undefined
            }
          />
          <StatCard
            label={t('activity.now.stats.next24h')}
            value={snapshot.stats.next_24h}
            sub={
              next
                ? t('activity.now.stats.nextAt', {
                    ...NO_ESCAPE,
                    time: formatRunTime(next.next_run_at, clock),
                    name: upNextName(next),
                  })
                : undefined
            }
          />
          <StatCard
            label={t('activity.now.stats.failed')}
            value={snapshot.stats.failed_24h}
            tone={snapshot.stats.failed_24h > 0 ? 'destructive' : 'default'}
            valueTone={
              snapshot.stats.failed_24h > 0 ? 'destructive' : undefined
            }
          />
        </div>

        {summary.needsYou > 0 && (
          <section>
            <SectionHeader
              className="mb-3"
              title={t('activity.now.needsYou')}
              count={summary.needsYou}
            />
            <Card variant="subtle" padding="none" className="overflow-hidden">
              <ListRows>
                {snapshot.needs_you.map((item) =>
                  item.kind === 'approval'
                    ? approvalRow(item)
                    : pausedRow(item),
                )}
                {reconnects.map((connection) => (
                  <ListRow
                    key={connection.id}
                    leading={<KindIcon icon={Plug} tone="warning" />}
                    title={t('activity.now.reconnect', {
                      ...NO_ESCAPE,
                      name: connection.display_name || connection.name,
                    })}
                    description={connection.account_label}
                    trailing={outlineButton(
                      t('activity.now.reconnectAction'),
                      () => navigate('/settings/connectors'),
                    )}
                  />
                ))}
              </ListRows>
            </Card>
          </section>
        )}

        <section>
          <SectionHeader
            className="mb-3"
            title={t('activity.now.runningTitle')}
            count={snapshot.running.length}
            actions={
              <ToggleGroup
                type="single"
                size="xs"
                value={filter}
                aria-label={t('activity.now.filter')}
                onValueChange={(value) => value && setFilter(value as Filter)}
              >
                {(['all', 'chats', 'automations', 'knowledge'] as const).map(
                  (value) => (
                    <ToggleGroupItem key={value} value={value}>
                      {t(`activity.now.filters.${value}`)}
                    </ToggleGroupItem>
                  ),
                )}
              </ToggleGroup>
            }
          />
          {stopError && (
            <p role="alert" className="text-destructive mb-3 text-sm">
              {stopError}
            </p>
          )}
          <Card variant="subtle" padding="none" className="overflow-hidden">
            {running.length === 0 ? (
              <EmptyState
                size="sm"
                illustration="none"
                title={t('activity.now.nothingRunning')}
              />
            ) : (
              <ul className="divide-border divide-y">
                {running.map(runningRow)}
              </ul>
            )}
          </Card>
        </section>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section>
            {sideHeader(
              t('activity.now.upNext'),
              ACTIVITY_CALENDAR_PATH,
              t('activity.now.openCalendar'),
            )}
            <Card variant="subtle" padding="none" className="overflow-hidden">
              {snapshot.up_next.length === 0 ? (
                <EmptyState
                  size="sm"
                  illustration="none"
                  title={t('activity.now.nothingPlanned')}
                />
              ) : (
                <ListRows>
                  {snapshot.up_next.slice(0, SIDE_LIST_LIMIT).map(upNextRow)}
                </ListRows>
              )}
            </Card>
          </section>
          <section>
            {sideHeader(
              t('activity.now.watching'),
              ACTIVITY_MONITORS_PATH,
              t('activity.now.allMonitors'),
            )}
            <Card variant="subtle" padding="none" className="overflow-hidden">
              {watching.length === 0 ? (
                <EmptyState
                  size="sm"
                  illustration="none"
                  title={t('activity.now.nothingWatched')}
                />
              ) : (
                <ListRows>
                  {watching.slice(0, SIDE_LIST_LIMIT).map((monitor) => (
                    <ListRow
                      key={monitor.monitor_id}
                      interactive={Boolean(monitor.conversation_id)}
                      asChild={Boolean(monitor.conversation_id)}
                      leading={
                        <KindIcon
                          icon={
                            monitor.source_type === 'webpage'
                              ? Globe
                              : monitor.source_type === 'webhook'
                                ? Webhook
                                : monitor.source_type === 'approval'
                                  ? UserCheck
                                  : monitor.source_type === 'ingest'
                                    ? RefreshCw
                                    : Radar
                          }
                        />
                      }
                      title={monitor.description || t('monitors.untitled')}
                      description={meta(
                        t(`monitors.source.${monitor.source_type}`),
                        monitor.interval
                          ? t('monitors.every', {
                              ...NO_ESCAPE,
                              interval: monitor.interval,
                            })
                          : t('monitors.onEvent'),
                        monitor.last_checked_at &&
                          t('activity.now.checked', {
                            ...NO_ESCAPE,
                            time: formatRelative(monitor.last_checked_at),
                          }),
                      )}
                    >
                      {monitor.conversation_id ? (
                        <Link to={`/c/${monitor.conversation_id}`} />
                      ) : undefined}
                    </ListRow>
                  ))}
                </ListRows>
              )}
            </Card>
          </section>
        </div>
      </div>
    </>
  );
}
