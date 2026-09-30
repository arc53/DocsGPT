import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useParams } from 'react-router-dom';

import userService from '../../api/services/userService';
import { Plus } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { LoadingState } from '@/components/ui/loading-state';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import schedulesService from '../../api/services/schedulesService';
import StatCard from '../../components/StatCard';
import { Button } from '../../components/ui/button';
import { Card } from '../../components/ui/card';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { ActiveState } from '../../models/misc';
import { selectToken } from '../../preferences/preferenceSlice';
import type { AppDispatch, RootState } from '../../store';
import { formatTokens } from '../../settings/traces/traceUtils';
import {
  formatDateOnly,
  formatDateTime,
  formatRelative,
} from '../../utils/dateTimeUtils';
import AgentPageToolbar, { LastUsedMeta } from '../components/AgentPageToolbar';
import SectionShell from '../../navigation/SectionShell';
import type { Agent } from '../types';
import type {
  Schedule,
  ScheduleCreatePayload,
  ScheduleRun,
  ScheduleStats,
} from '../types/schedule';
import RunDetailDrawer from './RunDetailDrawer';
import ScheduleFormModal from './ScheduleFormModal';
import ScheduleRow from './ScheduleRow';
import {
  approvalGatedTools,
  type AgentToolSummary,
  type ApprovalToolInfo,
} from './toolApproval';
import {
  createSchedule,
  deleteSchedule,
  loadSchedulesForAgent,
  runScheduleNow,
  selectSchedulesForAgent,
  setSchedulePaused,
  updateSchedule,
} from './schedulesSlice';

// Timezones and dates carry slashes: React escapes on render, so i18next
// must not escape them first.
const NO_ESCAPE = { interpolation: { escapeValue: false } } as const;

// The stat row's window, in days.
const STATS_DAYS = 30;

/** Standalone Schedules page for an agent: list, create, edit, pause, run, delete. */
export default function SchedulesView() {
  const { t } = useTranslation();
  const { agentId } = useParams();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);

  const [agent, setAgent] = useState<Agent | undefined>();
  const [loadingAgent, setLoadingAgent] = useState<boolean>(true);
  const [modalOpen, setModalOpen] = useState<boolean>(false);
  const [editing, setEditing] = useState<Schedule | null>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [activeRun, setActiveRun] = useState<ScheduleRun | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');
  const [scheduleToDelete, setScheduleToDelete] = useState<Schedule | null>(
    null,
  );

  const schedules = useSelector((state: RootState) =>
    selectSchedulesForAgent(state, agentId ?? ''),
  );
  // undefined while loading, null when the stats request failed.
  const [stats, setStats] = useState<ScheduleStats | null | undefined>(
    undefined,
  );

  // Refresh the totals whenever the list changes (a run finished, a
  // schedule was paused or removed): the SSE feed updates `schedules`.
  useEffect(() => {
    if (!agentId) return;
    let cancelled = false;
    schedulesService
      .statsForAgent(agentId, token, STATS_DAYS)
      .then((next) => {
        if (!cancelled) setStats(next);
      })
      .catch(() => {
        if (!cancelled) setStats(null);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, token, schedules]);

  useEffect(() => {
    if (!agentId) return;
    const fetchAgent = async () => {
      setLoadingAgent(true);
      try {
        const response = await userService.getAgent(agentId, token);
        if (!response.ok) throw new Error('Failed to fetch agent');
        const data = await response.json();
        setAgent(data);
      } catch (error) {
        console.error(error);
      } finally {
        setLoadingAgent(false);
      }
    };
    fetchAgent();
  }, [agentId, token]);

  useEffect(() => {
    if (!agentId) return;
    dispatch(loadSchedulesForAgent({ agentId, token }));
  }, [dispatch, agentId, token]);

  // The caller's tools with their actions, to tell which of the agent's
  // tools need approval. A failed read lists every tool as needing it.
  const [userTools, setUserTools] = useState<ApprovalToolInfo[]>([]);
  useEffect(() => {
    let cancelled = false;
    userService
      .getUserTools(token)
      .then((response: Response) => (response.ok ? response.json() : null))
      .then((data: { tools?: ApprovalToolInfo[] } | null) => {
        if (!cancelled) setUserTools(data?.tools ?? []);
      })
      .catch(() => {
        if (!cancelled) setUserTools([]);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const approvalTools = useMemo(() => {
    if (!agent) return [];
    const details: AgentToolSummary[] = agent.tool_details?.length
      ? agent.tool_details
      : (agent.tools ?? []).map((id) => ({ id, name: id }));
    return approvalGatedTools(details, userTools);
  }, [agent, userTools]);

  const recurring = useMemo(
    () => schedules.filter((s) => s.trigger_type === 'recurring'),
    [schedules],
  );
  const oneTime = useMemo(
    () => schedules.filter((s) => s.trigger_type === 'once'),
    [schedules],
  );

  const openCreate = () => {
    setEditing(null);
    setModalOpen(true);
  };

  const openEdit = (schedule: Schedule) => {
    setEditing(schedule);
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setEditing(null);
  };

  const requestDelete = (schedule: Schedule) => {
    setScheduleToDelete(schedule);
    setDeleteConfirmation('ACTIVE');
  };

  const confirmDelete = () => {
    if (!scheduleToDelete) return;
    dispatch(deleteSchedule({ id: scheduleToDelete.id, token }));
    setScheduleToDelete(null);
  };

  const handleSubmit = async (payload: ScheduleCreatePayload) => {
    if (!agentId) return;
    setSubmitting(true);
    try {
      if (editing?.id) {
        await dispatch(
          updateSchedule({ id: editing.id, payload, token }),
        ).unwrap();
      } else {
        await dispatch(createSchedule({ agentId, payload, token })).unwrap();
      }
      setModalOpen(false);
      setEditing(null);
    } catch (err) {
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  };

  const activeCount = schedules.filter((s) => s.status === 'active').length;
  const pausedCount = schedules.filter((s) => s.status === 'paused').length;
  const nextRunAt = schedules
    .filter((s) => s.status === 'active' && s.next_run_at)
    .map((s) => s.next_run_at as string)
    .sort()[0];
  // A next run in the past means the scheduler hasn't picked it up yet.
  const nextRunOverdue =
    Boolean(nextRunAt) && Date.parse(nextRunAt as string) < Date.now();
  const statsLoading = stats === undefined;
  const failedCount = stats?.failed ?? 0;
  const latestFailure = stats?.latest_failure;

  const newScheduleButton = (
    <Button type="button" size="field" shape="pill" onClick={openCreate}>
      <Plus />
      {t('agents.schedules.newRecurring')}
    </Button>
  );

  const renderList = (list: Schedule[], emptyKey: string) =>
    list.length === 0 ? (
      <Card variant="subtle" padding="lg">
        <EmptyState
          size="sm"
          illustration="none"
          title={t(emptyKey)}
          action={
            <Button
              type="button"
              variant="outline"
              size="sm"
              shape="pill"
              onClick={openCreate}
            >
              <Plus />
              {t('agents.schedules.newRecurring')}
            </Button>
          }
        />
      </Card>
    ) : (
      <ul className="flex flex-col gap-3">
        {list.map((schedule) => (
          <li key={schedule.id}>
            <ScheduleRow
              schedule={schedule}
              expanded={expanded === schedule.id}
              onToggleRuns={(id) => setExpanded(expanded === id ? null : id)}
              onEdit={openEdit}
              onSetPaused={(target, paused) =>
                dispatch(
                  setSchedulePaused({
                    id: target.id,
                    action: paused ? 'pause' : 'resume',
                    token,
                  }),
                )
              }
              onRunNow={(target) =>
                dispatch(runScheduleNow({ id: target.id, token }))
              }
              onDelete={requestDelete}
              onSelectRun={(run) => setActiveRun(run)}
            />
          </li>
        ))}
      </ul>
    );

  return (
    <SectionShell>
      {agent && (
        <AgentPageToolbar
          name={agent.name}
          meta={<LastUsedMeta lastUsedAt={agent.last_used_at} />}
          actions={newScheduleButton}
        />
      )}
      {loadingAgent ? (
        <LoadingState fill="block" />
      ) : (
        agent && (
          <div className="flex flex-col gap-8">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <StatCard
                label={t('agents.schedules.stats.active')}
                value={activeCount}
                sub={
                  pausedCount > 0
                    ? t('agents.schedules.stats.paused', {
                        count: pausedCount,
                      })
                    : undefined
                }
              />
              <StatCard
                label={t('agents.schedules.stats.nextRun')}
                value={
                  !nextRunAt
                    ? '—'
                    : nextRunOverdue
                      ? t('agents.schedules.stats.overdue')
                      : formatRelative(nextRunAt, { future: true })
                }
                valueTone={nextRunOverdue ? 'warning' : undefined}
                sub={nextRunAt ? formatDateTime(nextRunAt) : undefined}
              />
              <StatCard
                label={t('agents.schedules.stats.runs', { days: STATS_DAYS })}
                value={stats ? stats.runs : '—'}
                loading={statsLoading}
                sub={
                  stats
                    ? t('agents.schedules.stats.tokens', {
                        tokens: formatTokens(stats.tokens),
                      })
                    : undefined
                }
              />
              <StatCard
                label={t('agents.schedules.stats.failed', {
                  days: STATS_DAYS,
                })}
                value={stats ? failedCount : '—'}
                loading={statsLoading}
                tone={failedCount > 0 ? 'destructive' : 'default'}
                valueTone={failedCount > 0 ? 'destructive' : undefined}
                sub={
                  latestFailure
                    ? t('agents.schedules.stats.latestFailure', {
                        ...NO_ESCAPE,
                        status: t(
                          `agents.schedules.status.${latestFailure.status}`,
                        ),
                        date: formatDateOnly(latestFailure.scheduled_for),
                      })
                    : undefined
                }
              />
            </div>
            <Tabs defaultValue="recurring">
              <TabsList variant="underline">
                <TabsTrigger value="recurring" variant="underline">
                  {t('agents.schedules.recurring')}
                  <Badge variant="neutral">{recurring.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="once" variant="underline">
                  {t('agents.schedules.oneTime')}
                  <Badge variant="neutral">{oneTime.length}</Badge>
                </TabsTrigger>
              </TabsList>
              <TabsContent value="recurring" className="mt-4">
                {renderList(recurring, 'agents.schedules.noRecurring')}
              </TabsContent>
              <TabsContent value="once" className="mt-4">
                {renderList(oneTime, 'agents.schedules.noOneTime')}
              </TabsContent>
            </Tabs>
            <RunDetailDrawer
              run={activeRun}
              onClose={() => setActiveRun(null)}
            />
            {modalOpen && (
              <ScheduleFormModal
                key={editing?.id ?? 'create'}
                open={modalOpen}
                initial={editing}
                approvalTools={approvalTools}
                onClose={closeModal}
                onSubmit={handleSubmit}
                submitting={submitting}
              />
            )}
            <ConfirmationModal
              message={t('agents.schedules.deleteConfirm')}
              modalState={deleteConfirmation}
              setModalState={setDeleteConfirmation}
              submitLabel={t('agents.schedules.delete')}
              handleSubmit={confirmDelete}
              handleCancel={() => setScheduleToDelete(null)}
              variant="destructive"
            />
          </div>
        )
      )}
    </SectionShell>
  );
}
