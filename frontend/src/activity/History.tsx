import {
  CalendarClock,
  Radar,
  SquareTerminal,
  Webhook,
  Workflow,
  type LucideIcon,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
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
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import TraceSheet from '../settings/traces/TraceSheet';
import type { TraceRef } from '../settings/types';
import type { AppDispatch } from '../store';
import { formatCount, intlLocale } from '../utils/dateTimeUtils';
import { selectActivityRevision } from './activitySlice';
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

/**
 * "8.2s", "2m 10s", "1h 4m" in English, with the units in the reader's
 * language; empty when unknown (a skipped run has none).
 */
export function formatDuration(
  ms: number | null | undefined,
  locale: string = intlLocale(),
): string {
  if (ms === null || ms === undefined || ms <= 0) return '';
  const unit = (value: number, name: string, digits = 0) =>
    new Intl.NumberFormat(locale, {
      style: 'unit',
      unit: name,
      unitDisplay: 'narrow',
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
  if (ms < 10_000) return unit(ms / 1000, 'second', 1);
  // Whole seconds before splitting, so 119.6 s reads 2m 0s, not 1m 60s.
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return unit(seconds, 'second');
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60)
    return `${unit(minutes, 'minute')} ${unit(seconds % 60, 'second')}`;
  return `${unit(Math.floor(minutes / 60), 'hour')} ${unit(minutes % 60, 'minute')}`;
}

/**
 * The runs of `page` not already in `listed`. Ids are unique per kind only.
 * Newer runs shift the server's offsets, so an overlapping refresh and
 * Load more can both bring the same run.
 */
function unseen(listed: HistoryRun[], page: HistoryRun[]): HistoryRun[] {
  const seen = new Set(listed.map((run) => `${run.kind}:${run.id}`));
  return page.filter((run) => !seen.has(`${run.kind}:${run.id}`));
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
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const revision = useSelector(selectActivityRevision);

  const [kind, setKind] = useState<(typeof KIND_FILTERS)[number]>('all');
  const [status, setStatus] = useState<(typeof STATUS_FILTERS)[number]>('all');
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>('30');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  // Rows and "more to load" change together: a refresh that finds a gap
  // replaces both, one that merges keeps the tail's `hasMore`.
  // The list remembers the filters it was loaded under: under others it is
  // not shown (a new filter loads, then fails, on its own), so a Retry starts
  // that filter over instead of appending to the last one's runs.
  const [list, setList] = useState<{
    key: string;
    runs: HistoryRun[];
    hasMore: boolean;
  } | null>(null);
  const filterKey = [kind, status, query, period].join('|');
  const shown = list?.key === filterKey ? list : null;
  const runs = shown?.runs ?? null;
  const hasMore = shown?.hasMore ?? false;
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

  const fetchPage = useCallback(
    (offset: number) =>
      activityService.history(
        {
          kind: kind === 'all' ? undefined : kind,
          status: status === 'all' ? undefined : status,
          q: query || undefined,
          days: Number(period),
          limit: PAGE_SIZE,
          offset,
        },
        token,
      ),
    [kind, status, query, period, token],
  );

  // Each first-page load starts a new generation; an answer from an older
  // one (a filter since changed, a superseded reload) is dropped.
  const generation = useRef(0);

  /** First page (`offset` 0) replaces the list; a later one appends. */
  const load = useCallback(
    async (offset: number) => {
      const gen = offset === 0 ? ++generation.current : generation.current;
      setLoading(true);
      setFailed(false);
      try {
        const page = await fetchPage(offset);
        if (gen !== generation.current) return;
        setList((current) => ({
          key: filterKey,
          runs:
            offset === 0 || current?.key !== filterKey
              ? page.runs
              : [...current.runs, ...unseen(current.runs, page.runs)],
          hasMore: page.has_more,
        }));
      } catch {
        if (gen === generation.current) setFailed(true);
      } finally {
        if (gen === generation.current) setLoading(false);
      }
    },
    [fetchPage, filterKey],
  );

  /**
   * Puts runs that finished since the last look on top, keeping the pages
   * already loaded. Quiet: no spinner, and a failure waits for the next one.
   */
  const listRef = useRef(list);
  listRef.current = list;
  const refreshHead = useCallback(async () => {
    const gen = generation.current;
    try {
      const page = await fetchPage(0);
      if (gen !== generation.current) return;
      const current = listRef.current;
      if (current !== null && current.key !== filterKey) return;
      // Nothing in common: more than a page landed (or nothing was listed),
      // so a merge would leave a gap. Start over from this page, as a new
      // generation: a Load more still out asked for an offset of the old
      // list, and its answer would skip the runs in between.
      if (
        current === null ||
        (page.runs.length > 0 &&
          unseen(current.runs, page.runs).length === page.runs.length)
      ) {
        generation.current += 1;
        setList({ key: filterKey, runs: page.runs, hasMore: page.has_more });
        setLoading(false);
        setFailed(false);
        return;
      }
      // Merged against the latest list: a page may have landed meanwhile.
      setList((latest) => {
        if (latest === null || latest.key !== filterKey) return latest;
        const fresh = unseen(latest.runs, page.runs);
        if (fresh.length === 0) return latest;
        return { ...latest, runs: [...fresh, ...latest.runs] };
      });
    } catch {
      // The next change in activity tries again.
    }
  }, [fetchPage, filterKey]);

  useEffect(() => {
    void load(0);
  }, [load]);

  // New runs land after the events that refetch the Now snapshot, which
  // moves `revision`. Only that acts here; filters reload through `load`.
  const seenRevision = useRef(revision);
  const loaded = shown !== null;
  useEffect(() => {
    if (revision === seenRevision.current) return;
    seenRevision.current = revision;
    if (loaded) void refreshHead();
    else void load(0);
  }, [revision, loaded, load, refreshHead]);

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
        dispatch(
          showActionToast({
            variant: 'destructive',
            message: t('activity.history.runLoadError'),
          }),
        );
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
          {formatDuration(run.duration_ms, intlLocale(i18n.language)) || '—'}
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
