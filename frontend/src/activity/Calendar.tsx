import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import PageToolbar from '@/components/PageToolbar';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { IconButton } from '@/components/ui/icon-button';
import { LoadingState } from '@/components/ui/loading-state';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ToggleChip } from '@/components/ui/toggle-chip';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { cn } from '@/lib/utils';

import RunDetailDrawer from '../agents/schedules/RunDetailDrawer';
import { runScheduleNow } from '../agents/schedules/schedulesSlice';
import type { ScheduleRun } from '../agents/types/schedule';
import activityService from '../api/services/activityService';
import schedulesService from '../api/services/schedulesService';
import { useMediaQuery } from '../hooks';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import { intlLocale } from '../utils/dateTimeUtils';
import { selectActivityNow } from './activitySlice';
import AgendaList from './calendar/AgendaList';
import { addDays, stepAnchor, viewWindow } from './calendar/dates';
import EventPanel from './calendar/EventPanel';
import type { FrequentBlock } from './calendar/layout';
import { STATE_CLASS } from './calendar/layout';
import MonthGrid from './calendar/MonthGrid';
import type {
  CalendarEvent,
  CalendarView,
  MonitorRange,
  PlannedWindow,
} from './calendar/types';
import WeekGrid from './calendar/WeekGrid';
import { ACTIVITY_MONITORS_PATH } from './paths';

/** The agent filter's values besides an agent id. */
const ALL = 'all';
const CHAT = 'chat';

const LEGEND = [
  ['planned', 'planned'],
  ['running', 'running'],
  ['success', 'success'],
  ['failed', 'failed'],
  ['paused', 'paused'],
] as const;

/**
 * Activity › Calendar: planned runs (expanded from each schedule's cron),
 * past runs by status, monitors as ranges and knowledge syncs, as a day,
 * week, month or agenda. A slot opens its schedule; a past run opens its
 * details.
 */
export default function Calendar() {
  const { t, i18n } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  // Refetch whenever the Now snapshot does: it follows the same events.
  const snapshot = useSelector(selectActivityNow);
  const { isMobile } = useMediaQuery();

  const [view, setView] = useState<CalendarView>(isMobile ? 'agenda' : 'week');
  const [anchor, setAnchor] = useState(() => new Date());
  const [agent, setAgent] = useState<string>(ALL);
  const [showMonitors, setShowMonitors] = useState(true);
  const [showSyncs, setShowSyncs] = useState(true);
  const [hidePast, setHidePast] = useState(false);
  const [data, setData] = useState<PlannedWindow | null>(null);
  const [failed, setFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const [selection, setSelection] = useState<
    | { kind: 'event'; event: CalendarEvent }
    | { kind: 'block'; block: FrequentBlock }
    | null
  >(null);
  const [activeRun, setActiveRun] = useState<ScheduleRun | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // A phone has no room for a time grid: it shows the agenda or the month.
  // The media query settles after the first render, so follow it.
  useEffect(() => {
    if (isMobile && (view === 'day' || view === 'week')) setView('agenda');
  }, [isMobile, view]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const { start, end, days } = useMemo(
    () => viewWindow(view, anchor),
    [view, anchor],
  );

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    activityService
      .planned(start, end, token)
      .then((next) => {
        if (!cancelled) setData(next);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [start, end, token, snapshot, reload]);

  // Agents that have a slot in the window, for the filter.
  const agents = useMemo(() => {
    const byId = new Map<string, string>();
    let chat = false;
    for (const event of data?.events ?? []) {
      if (event.agent_id) byId.set(event.agent_id, event.agent_name ?? '');
      else chat = true;
    }
    return {
      list: [...byId.entries()].sort((a, b) => a[1].localeCompare(b[1])),
      chat,
    };
  }, [data]);

  const events = useMemo(
    () =>
      (data?.events ?? []).filter((event) => {
        if (agent === CHAT && event.agent_id) return false;
        if (agent !== ALL && agent !== CHAT && event.agent_id !== agent)
          return false;
        if (hidePast && Date.parse(event.at) < now) return false;
        return true;
      }),
    [data, agent, hidePast, now],
  );
  const monitors = showMonitors ? (data?.monitors ?? []) : [];
  const syncs = showSyncs ? (data?.syncs ?? []) : [];

  const locale = intlLocale(i18n.language);
  const rangeLabel = (() => {
    if (view === 'day') {
      return new Intl.DateTimeFormat(locale, {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
        year: 'numeric',
      }).format(start);
    }
    if (view === 'month') {
      return new Intl.DateTimeFormat(locale, {
        month: 'long',
        year: 'numeric',
      }).format(anchor);
    }
    const format = new Intl.DateTimeFormat(locale, {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
    return format.formatRange(start, addDays(end, -1));
  })();

  const openEvent = async (event: CalendarEvent) => {
    if (event.run_id) {
      try {
        const { run } = await schedulesService.getRun(
          event.schedule_id,
          event.run_id,
          token,
        );
        setActiveRun(run);
      } catch {
        setFailed(true);
      }
      return;
    }
    setSelection({ kind: 'event', event });
  };

  const openMonitor = (monitor: MonitorRange) =>
    navigate(
      monitor.conversation_id
        ? `/c/${monitor.conversation_id}`
        : ACTIVITY_MONITORS_PATH,
    );

  const views: CalendarView[] = isMobile
    ? ['month', 'agenda']
    : ['day', 'week', 'month', 'agenda'];

  const body = !data ? (
    failed ? (
      <EmptyState
        tone="destructive"
        title={t('activity.calendar.loadError')}
        onRetry={() => setReload((n) => n + 1)}
      />
    ) : (
      <LoadingState fill="block" />
    )
  ) : view === 'month' ? (
    <MonthGrid
      days={days}
      month={anchor.getMonth()}
      events={events}
      now={now}
      onSelectEvent={(event) => void openEvent(event)}
      onSelectBlock={(block) => setSelection({ kind: 'block', block })}
      onOpenDay={(day) => {
        setAnchor(day);
        setView(isMobile ? 'agenda' : 'day');
      }}
    />
  ) : view === 'agenda' ? (
    <AgendaList
      days={days}
      events={events}
      monitors={monitors}
      now={now}
      onSelectEvent={(event) => void openEvent(event)}
      onSelectBlock={(block) => setSelection({ kind: 'block', block })}
      onSelectMonitor={openMonitor}
    />
  ) : (
    <WeekGrid
      days={days}
      events={events}
      monitors={monitors}
      syncs={syncs}
      now={now}
      onSelectEvent={(event) => void openEvent(event)}
      onSelectBlock={(block) => setSelection({ kind: 'block', block })}
      onSelectMonitor={openMonitor}
    />
  );

  return (
    <>
      <PageToolbar intro={t('activity.calendar.subtitle')} />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            shape="pill"
            onClick={() => setAnchor(new Date())}
          >
            {t('activity.calendar.todayButton')}
          </Button>
          <IconButton
            label={t('activity.calendar.previous')}
            variant="ghost-muted"
            size="icon-sm"
            onClick={() => setAnchor((a) => stepAnchor(view, a, -1))}
          >
            <ChevronLeft aria-hidden />
          </IconButton>
          <IconButton
            label={t('activity.calendar.next')}
            variant="ghost-muted"
            size="icon-sm"
            onClick={() => setAnchor((a) => stepAnchor(view, a, 1))}
          >
            <ChevronRight aria-hidden />
          </IconButton>
          <h2 className="text-foreground ms-1 truncate text-lg font-semibold">
            {rangeLabel}
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={agent} onValueChange={setAgent}>
            <SelectTrigger
              className="w-[180px]"
              size="field"
              shape="pill"
              aria-label={t('activity.calendar.agentFilter')}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>
                {t('activity.calendar.allAgents')}
              </SelectItem>
              {agents.list.map(([id, name]) => (
                <SelectItem key={id} value={id}>
                  {name || t('agents.pageHeader.fallbackName')}
                </SelectItem>
              ))}
              {agents.chat && (
                <SelectItem value={CHAT}>
                  {t('activity.schedules.createdInChat')}
                </SelectItem>
              )}
            </SelectContent>
          </Select>
          <ToggleGroup
            type="single"
            size="sm"
            value={view}
            aria-label={t('activity.calendar.viewLabel')}
            onValueChange={(next) => next && setView(next as CalendarView)}
          >
            {views.map((value) => (
              <ToggleGroupItem key={value} value={value}>
                {t(`activity.calendar.views.${value}`)}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <ToggleChip pressed={showMonitors} onPressedChange={setShowMonitors}>
          {t('activity.calendar.monitors')}
        </ToggleChip>
        {view !== 'month' && view !== 'agenda' && (
          <ToggleChip pressed={showSyncs} onPressedChange={setShowSyncs}>
            {t('activity.calendar.knowledgeSyncs')}
          </ToggleChip>
        )}
        <ToggleChip pressed={hidePast} onPressedChange={setHidePast}>
          {t('activity.calendar.hidePast')}
        </ToggleChip>
        <ul className="text-muted-foreground ms-auto hidden flex-wrap items-center gap-x-3 gap-y-1 text-xs md:flex">
          {LEGEND.map(([key, state]) => (
            <li key={key} className="inline-flex items-center gap-1.5">
              <span
                aria-hidden
                className={cn('h-3 w-4 rounded-sm', STATE_CLASS[state])}
              />
              {t(`activity.calendar.legend.${key}`)}
            </li>
          ))}
        </ul>
      </div>
      {data && data.truncated.length > 0 && (
        <p className="text-muted-foreground mb-3 text-xs">
          {t('activity.calendar.truncated')}
        </p>
      )}
      {body}
      <EventPanel
        selection={selection}
        onClose={() => setSelection(null)}
        onRunNow={async (scheduleId) => {
          await dispatch(runScheduleNow({ id: scheduleId, token })).unwrap();
          setReload((n) => n + 1);
        }}
        onOpenRun={(event) => {
          setSelection(null);
          void openEvent(event);
        }}
      />
      <RunDetailDrawer run={activeRun} onClose={() => setActiveRun(null)} />
    </>
  );
}
