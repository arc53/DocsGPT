import { ArrowRight, Play } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';
import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  DescriptionItem,
  DescriptionList,
} from '@/components/ui/description-list';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { SectionHeader } from '@/components/ui/section-header';
import {
  PanelBody,
  PanelFooter,
  PanelHeader,
  SidePanel,
} from '@/components/ui/side-panel';

import { agentSchedulesPath } from '../../agents/paths';
import { formatCron } from '../../agents/schedules/cronBuilder';
import { showActionToast } from '../../notifications/actionToastSlice';
import type { AppDispatch } from '../../store';
import {
  formatClock,
  formatCount,
  formatDateTime,
} from '../../utils/dateTimeUtils';
import { ACTIVITY_SCHEDULES_PATH } from '../paths';
import { blockCount, type FrequentBlock } from './layout';
import SyncPanel from './SyncPanel';
import type { CalendarEvent, EventState, ScheduleEvent } from './types';

const BADGE: Record<
  EventState,
  'default' | 'success' | 'destructive' | 'info' | 'neutral' | 'warning'
> = {
  planned: 'default',
  paused: 'neutral',
  skipped: 'neutral',
  pending: 'info',
  running: 'info',
  success: 'success',
  failed: 'destructive',
  timeout: 'destructive',
  missed: 'warning',
};

export type EventPanelProps = {
  /** A planned or paused slot, a knowledge sync, or a frequent schedule's day. */
  selection:
    | { kind: 'event'; event: CalendarEvent }
    | { kind: 'block'; block: FrequentBlock }
    | null;
  onClose: () => void;
  /** Runs the schedule once now; resolves once queued, rejects if refused. */
  onRunNow: (scheduleId: string) => Promise<void>;
  /** Opens a past run's details (a slot of a frequent schedule's day). */
  onOpenRun: (event: ScheduleEvent) => void;
};

/**
 * The calendar's side panel for a slot that hasn't run: when it runs, how it
 * repeats, whose it is, with Run now and the way to its schedule. For a
 * frequent schedule's day it lists every slot; a past one opens its run. A
 * knowledge sync opens its own panel (`SyncPanel`).
 */
export default function EventPanel({
  selection,
  onClose,
  onRunNow,
  onOpenRun,
}: EventPanelProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const [running, setRunning] = useState(false);
  const [queued, setQueued] = useState(false);
  if (!selection) return null;
  if (selection.kind === 'event' && selection.event.kind === 'sync') {
    return <SyncPanel event={selection.event} onClose={onClose} />;
  }
  const event: ScheduleEvent =
    selection.kind === 'block'
      ? selection.block.events[0]
      : (selection.event as ScheduleEvent);
  // A day block is paused when its schedule is: its slots all say so.
  const state: EventState =
    selection.kind === 'event'
      ? event.state
      : selection.block.events.some((slot) => slot.state === 'paused')
        ? 'paused'
        : 'planned';
  const schedulePath = event.agent_id
    ? agentSchedulesPath(event.agent_id)
    : ACTIVITY_SCHEDULES_PATH;
  const owner = event.agent_name
    ? event.agent_name
    : t('activity.schedules.createdInChat');

  const runNow = async () => {
    setRunning(true);
    try {
      await onRunNow(event.schedule_id);
      setQueued(true);
    } catch {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('activity.calendar.runNowError'),
        }),
      );
    } finally {
      setRunning(false);
    }
  };

  return (
    <SidePanel
      open
      onOpenChange={(open) => !open && onClose()}
      aria-describedby={undefined}
    >
      <PanelHeader
        title={event.name ?? ''}
        description={`${owner} · ${
          event.trigger_type === 'once'
            ? t('activity.calendar.oneTime')
            : t('activity.calendar.recurring')
        }`}
        actions={
          selection.kind === 'event' ? (
            <Badge variant={BADGE[state]}>
              {t(`activity.calendar.state.${state}`)}
            </Badge>
          ) : undefined
        }
      />
      <PanelBody>
        <DescriptionList size="sm">
          {selection.kind === 'event' && (
            <DescriptionItem label={t('activity.calendar.when')}>
              {formatDateTime(event.at)}
            </DescriptionItem>
          )}
          {event.trigger_type === 'recurring' && event.cron && (
            <DescriptionItem label={t('activity.calendar.repeats')}>
              {formatCron(event.cron, t)}
            </DescriptionItem>
          )}
          {event.timezone && (
            <DescriptionItem label={t('activity.calendar.timezone')}>
              {event.timezone}
            </DescriptionItem>
          )}
          {event.origin_conversation_id && (
            <DescriptionItem label={t('activity.calendar.fromChat')}>
              <Button variant="link" size="text" asChild>
                <Link to={`/c/${event.origin_conversation_id}`}>
                  {event.origin_conversation_name ||
                    t('activity.schedules.openChat')}
                </Link>
              </Button>
            </DescriptionItem>
          )}
        </DescriptionList>
        {state === 'paused' && (
          <p className="text-muted-foreground text-sm">
            {t('activity.calendar.pausedNote')}
          </p>
        )}
        {state === 'missed' && (
          <p className="text-muted-foreground text-sm">
            {t('activity.calendar.missedNote')}
          </p>
        )}
        {selection.kind === 'block' && (
          <section className="flex flex-col gap-2">
            <SectionHeader
              as="h3"
              size="xs"
              title={t('activity.calendar.dayRuns')}
              count={blockCount(selection.block)}
            />
            <Card variant="subtle" padding="none" className="overflow-hidden">
              <ListRows>
                {selection.block.events.map((slot) => {
                  const past = Boolean(slot.run_id);
                  // A summed-up day's row spans its first to its last slot.
                  return (
                    <ListRow
                      key={`${slot.at}-${slot.state}`}
                      interactive={past}
                      asChild={past}
                      title={
                        slot.until
                          ? `${formatClock(new Date(slot.at))}–${formatClock(new Date(slot.until))}`
                          : formatClock(new Date(slot.at))
                      }
                      description={
                        slot.count
                          ? t('activity.calendar.slotCount', {
                              count: slot.count,
                              formatted: formatCount(slot.count),
                            })
                          : undefined
                      }
                      trailing={
                        <Badge variant={BADGE[slot.state]}>
                          {t(`activity.calendar.state.${slot.state}`)}
                        </Badge>
                      }
                    >
                      {past ? (
                        <button type="button" onClick={() => onOpenRun(slot)} />
                      ) : undefined}
                    </ListRow>
                  );
                })}
              </ListRows>
            </Card>
          </section>
        )}
        {queued && (
          <p role="status" className="text-success text-sm">
            {t('activity.calendar.queued')}
          </p>
        )}
      </PanelBody>
      <PanelFooter>
        {state !== 'paused' && (
          <Button
            type="button"
            variant="outline"
            shape="pill"
            loading={running}
            disabled={queued}
            onClick={() => void runNow()}
          >
            <Play />
            {t('agents.schedules.runNow')}
          </Button>
        )}
        <Button shape="pill" asChild>
          <Link to={schedulePath}>
            {t('activity.calendar.openSchedule')}
            <ArrowRight aria-hidden />
          </Link>
        </Button>
      </PanelFooter>
    </SidePanel>
  );
}
