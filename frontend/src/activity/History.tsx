import {
  CalendarClock,
  Radar,
  SquareTerminal,
  Webhook,
  Workflow,
  type LucideIcon,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import PageToolbar from '@/components/PageToolbar';
import SearchInput from '@/components/SearchInput';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { LoadMoreStatus } from '@/components/ui/load-more-status';
import { LoadingState } from '@/components/ui/loading-state';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

import RunDetailDrawer from '../agents/schedules/RunDetailDrawer';
import type { ScheduleRun } from '../agents/types/schedule';
import activityService from '../api/services/activityService';
import schedulesService from '../api/services/schedulesService';
import { selectToken } from '../preferences/preferenceSlice';
import TraceSheet from '../settings/traces/TraceSheet';
import type { TraceRef } from '../settings/types';
import { formatCount, intlLocale } from '../utils/dateTimeUtils';
import { selectActivityNow } from './activitySlice';
import { addDays, dayKey, formatClock, startOfDay } from './calendar/dates';
import type { HistoryKind, HistoryRun, HistoryStatus } from './historyTypes';

const PAGE_SIZE = 50;
/** Typing settles this long before the list reloads. */
const SEARCH_DEBOUNCE_MS = 300;

const KIND_ICON: Record<HistoryKind, LucideIcon> = {
  schedule: CalendarClock,
  webhook: Webhook,
  workflow: Workflow,
  job: SquareTerminal,
  monitor: Radar,
};

const STATUS_BADGE: Record<
  HistoryStatus,
  'success' | 'destructive' | 'warning' | 'neutral'
> = {
  success: 'success',
  failed: 'destructive',
  timeout: 'destructive',
  skipped: 'warning',
  cancelled: 'neutral',
};

const KIND_FILTERS = [
  'all',
  'schedule',
  'webhook',
  'workflow',
  'job',
  'monitor',
] as const;
const STATUS_FILTERS = [
  'all',
  'failed',
  'success',
  'skipped',
  'cancelled',
] as const;
/** Look-back choices, in days (scheduled runs are kept 90 days by default). */
const PERIODS = ['7', '30', '90'] as const;

/** "8.2 s", "2 m 10 s", "1 h 4 m"; empty when unknown (a skipped run has none). */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || ms <= 0) return '';
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes} m ${Math.round((ms % 60_000) / 1000)} s`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} m`;
}

/**
 * Activity › History: finished runs of every kind, newest first, grouped by
 * day. A scheduled run opens its details, a webhook or workflow run its
 * trace, and a background job or monitor wake its chat. Settings › Logs
 * stays the raw, technical log.
 */
export default function History() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  // New runs land after the events that refetch the Now snapshot.
  const snapshot = useSelector(selectActivityNow);

  const [kind, setKind] = useState<(typeof KIND_FILTERS)[number]>('all');
  const [status, setStatus] = useState<(typeof STATUS_FILTERS)[number]>('all');
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>('30');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [runs, setRuns] = useState<HistoryRun[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [activeRun, setActiveRun] = useState<ScheduleRun | null>(null);
  const [trace, setTrace] = useState<{
    ref: TraceRef;
    agentId?: string;
  } | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  const load = useCallback(
    async (offset: number) => {
      setLoading(true);
      setFailed(false);
      try {
        const page = await activityService.history(
          {
            kind: kind === 'all' ? undefined : kind,
            status: status === 'all' ? undefined : status,
            q: query || undefined,
            days: Number(period),
            limit: PAGE_SIZE,
            offset,
          },
          token,
        );
        setRuns((current) =>
          offset === 0 ? page.runs : [...(current ?? []), ...page.runs],
        );
        setHasMore(page.has_more);
      } catch {
        setFailed(true);
      } finally {
        setLoading(false);
      }
    },
    [kind, status, query, period, token],
  );

  useEffect(() => {
    void load(0);
  }, [load, snapshot]);

  const open = async (run: HistoryRun) => {
    if (run.kind === 'schedule' && run.schedule_id) {
      try {
        const { run: detail } = await schedulesService.getRun(
          run.schedule_id,
          run.id,
          token,
        );
        setActiveRun(detail);
      } catch {
        setFailed(true);
      }
    } else if (run.kind === 'webhook' && run.trace_id) {
      setTrace({
        ref: { field: 'id', value: run.trace_id },
        agentId: run.agent_id ?? undefined,
      });
    } else if (run.kind === 'workflow' && run.workflow_run_id) {
      setTrace({
        ref: { field: 'workflow_run_id', value: run.workflow_run_id },
      });
    } else if (run.conversation_id) {
      navigate(`/c/${run.conversation_id}`);
    }
  };

  const canOpen = (run: HistoryRun) =>
    (run.kind === 'schedule' && Boolean(run.schedule_id)) ||
    (run.kind === 'webhook' && Boolean(run.trace_id)) ||
    (run.kind === 'workflow' && Boolean(run.workflow_run_id)) ||
    Boolean(run.conversation_id);

  const today = startOfDay(new Date());
  const dayLabel = (date: Date) => {
    const day = startOfDay(date);
    if (dayKey(day) === dayKey(today)) return t('activity.calendar.today');
    if (dayKey(day) === dayKey(addDays(today, -1)))
      return t('activity.history.yesterday');
    return new Intl.DateTimeFormat(intlLocale(i18n.language), {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
    }).format(day);
  };

  const trigger = (run: HistoryRun) =>
    run.trigger
      ? t(`activity.history.trigger.${run.trigger}`, {
          defaultValue: run.trigger,
        })
      : '—';

  const rows: React.ReactNode[] = [];
  let lastDay = '';
  for (const run of runs ?? []) {
    const at = new Date(run.at);
    const key = dayKey(at);
    if (key !== lastDay) {
      lastDay = key;
      rows.push(
        <TableRow key={`day:${key}`}>
          <TableCell
            colSpan={8}
            className="text-muted-foreground text-xs font-semibold"
          >
            {dayLabel(at)}
          </TableCell>
        </TableRow>,
      );
    }
    const Icon = KIND_ICON[run.kind];
    const clickable = canOpen(run);
    rows.push(
      <TableRow
        key={`${run.kind}:${run.id}`}
        data-kind={run.kind}
        onClick={clickable ? () => void open(run) : undefined}
      >
        <TableCell className="text-muted-foreground tabular-nums">
          {formatClock(at)}
        </TableCell>
        <TableCell className="font-medium">
          <span className="line-clamp-1">
            {run.title ||
              (run.kind === 'job'
                ? t('activity.kind.job')
                : t(`activity.history.kind.${run.kind}`))}
          </span>
        </TableCell>
        <TableCell className="text-muted-foreground">
          <span className="line-clamp-1">
            {[run.agent_name, run.conversation_name]
              .filter(Boolean)
              .join(' · ') || '—'}
          </span>
        </TableCell>
        <TableCell>
          <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
            <Icon aria-hidden className="text-muted-foreground size-3.5" />
            {t(`activity.history.kind.${run.kind}`)}
          </span>
        </TableCell>
        <TableCell className="text-muted-foreground whitespace-nowrap">
          {trigger(run)}
        </TableCell>
        <TableCell>
          <Badge variant={STATUS_BADGE[run.status]}>
            {t(`activity.history.status.${run.status}`)}
          </Badge>
        </TableCell>
        <TableCell align="right" className="whitespace-nowrap tabular-nums">
          {formatDuration(run.duration_ms) || '—'}
        </TableCell>
        <TableCell
          align="right"
          className="text-muted-foreground whitespace-nowrap tabular-nums"
        >
          {run.tokens ? formatCount(run.tokens) : '—'}
        </TableCell>
      </TableRow>,
    );
  }

  return (
    <>
      <PageToolbar
        intro={t('activity.history.subtitle')}
        search={
          <SearchInput
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('activity.history.search')}
          />
        }
        action={
          <div className="flex flex-wrap gap-2">
            <Select
              value={period}
              onValueChange={(value) =>
                setPeriod(value as (typeof PERIODS)[number])
              }
            >
              <SelectTrigger
                className="w-[170px]"
                size="field"
                shape="pill"
                aria-label={t('activity.history.periodFilter')}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PERIODS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {t('activity.history.period', { count: Number(value) })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={status}
              onValueChange={(value) =>
                setStatus(value as (typeof STATUS_FILTERS)[number])
              }
            >
              <SelectTrigger
                className="w-[160px]"
                size="field"
                shape="pill"
                aria-label={t('activity.history.statusFilter')}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_FILTERS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {t(`activity.history.statusFilters.${value}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        }
      />
      <div className="mb-4 overflow-x-auto">
        <ToggleGroup
          type="single"
          size="sm"
          value={kind}
          aria-label={t('activity.history.kindFilter')}
          onValueChange={(value) =>
            value && setKind(value as (typeof KIND_FILTERS)[number])
          }
        >
          {KIND_FILTERS.map((value) => (
            <ToggleGroupItem key={value} value={value}>
              {t(`activity.history.kindFilters.${value}`)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      {runs === null ? (
        failed ? (
          <EmptyState
            tone="destructive"
            title={t('activity.history.loadError')}
            onRetry={() => void load(0)}
          />
        ) : (
          <LoadingState fill="block" />
        )
      ) : runs.length === 0 ? (
        <EmptyState
          title={
            query || kind !== 'all' || status !== 'all'
              ? t('activity.history.noMatches')
              : t('activity.history.empty')
          }
          description={t('activity.history.emptyHint')}
        />
      ) : (
        <>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader>
                    {t('activity.history.columns.when')}
                  </TableHeader>
                  <TableHeader>{t('activity.history.columns.run')}</TableHeader>
                  <TableHeader>
                    {t('activity.history.columns.owner')}
                  </TableHeader>
                  <TableHeader>
                    {t('activity.history.columns.kind')}
                  </TableHeader>
                  <TableHeader>
                    {t('activity.history.columns.trigger')}
                  </TableHeader>
                  <TableHeader>
                    {t('activity.history.columns.status')}
                  </TableHeader>
                  <TableHeader align="right">
                    {t('activity.history.columns.duration')}
                  </TableHeader>
                  <TableHeader align="right">
                    {t('activity.history.columns.tokens')}
                  </TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>{rows}</TableBody>
            </Table>
          </TableContainer>
          <LoadMoreStatus
            loading={loading}
            error={failed}
            done={!hasMore}
            onRetry={() => void load(runs.length)}
          />
          {hasMore && !loading && !failed && (
            <div className="mt-2 flex justify-center">
              <Button
                type="button"
                variant="link"
                size="sm"
                onClick={() => void load(runs.length)}
              >
                {t('activity.history.loadMore')}
              </Button>
            </div>
          )}
          <p className="text-muted-foreground mt-3 text-xs">
            {t('activity.history.retention')}
          </p>
        </>
      )}
      <RunDetailDrawer run={activeRun} onClose={() => setActiveRun(null)} />
      <TraceSheet
        traceRef={trace?.ref ?? null}
        agentId={trace?.agentId}
        onClose={() => setTrace(null)}
      />
    </>
  );
}
