import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useParams } from 'react-router-dom';

import userService from '../../api/services/userService';
import Spinner from '../../components/Spinner';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { ActiveState } from '../../models/misc';
import { selectToken } from '../../preferences/preferenceSlice';
import type { AppDispatch, RootState } from '../../store';
import AgentPageHeader from '../AgentPageHeader';
import type { Agent } from '../types';
import type {
  Schedule,
  ScheduleCreatePayload,
  ScheduleRun,
} from '../types/schedule';
import RunDetailDrawer from './RunDetailDrawer';
import RunLog from './RunLog';
import ScheduleFormModal from './ScheduleFormModal';
import ScheduleStatusBadge from './StatusBadge';
import { formatCron } from './cronBuilder';
import {
  createSchedule,
  deleteSchedule,
  loadSchedulesForAgent,
  runScheduleNow,
  selectSchedulesForAgent,
  setSchedulePaused,
  updateSchedule,
} from './schedulesSlice';

const formatTimestamp = (value?: string | null): string => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
};

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

  const agentToolIds = useMemo<string[]>(() => {
    if (!agent) return [];
    const fromDetails = (agent.tool_details ?? []).map((d) => d.id);
    if (fromDetails.length > 0) return fromDetails;
    return agent.tools ?? [];
  }, [agent]);

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
    if (submitting) return;
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

  const agentEditPath =
    agent?.agent_type === 'workflow'
      ? `/agents/workflow/edit/${agentId}`
      : `/agents/edit/${agentId}`;

  return (
    <div className="p-4 md:p-12">
      <AgentPageHeader
        agentId={agentId}
        agentName={agent?.name}
        agentEditPath={agentEditPath}
        currentPage="schedules"
        className="px-4"
      />
      <div className="mt-6 flex flex-col gap-3 px-4">
        {agent && (
          <div className="flex flex-col gap-1">
            <p className="text-foreground">{agent.name}</p>
            <p className="text-muted-foreground text-xs">
              {agent.last_used_at
                ? t('agents.logs.lastUsedAt') +
                  ' ' +
                  new Date(agent.last_used_at).toLocaleString()
                : t('agents.logs.noUsageHistory')}
            </p>
          </div>
        )}
      </div>
      {loadingAgent ? (
        <div className="flex h-[55vh] w-full items-center justify-center">
          <Spinner />
        </div>
      ) : (
        agent && (
          <div className="flex flex-col gap-4 p-4">
            <header className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">
                {t('agents.schedules.heading')}
              </h2>
              <button
                type="button"
                onClick={openCreate}
                className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-md px-3 py-1 text-sm"
              >
                {t('agents.schedules.newRecurring')}
              </button>
            </header>
            <section>
              <h3 className="text-muted-foreground mb-2 text-sm font-semibold uppercase">
                {t('agents.schedules.recurring')} ({recurring.length})
              </h3>
              {recurring.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  {t('agents.schedules.noRecurring')}
                </p>
              ) : (
                <ul className="flex flex-col gap-3">
                  {recurring.map((schedule) => (
                    <li
                      key={schedule.id}
                      className="border-border bg-card rounded-lg border p-3"
                    >
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="flex items-center gap-2">
                            <p className="font-semibold">
                              {schedule.name ||
                                schedule.instruction.slice(0, 80)}
                            </p>
                            <ScheduleStatusBadge status={schedule.status} />
                          </div>
                          <p className="text-muted-foreground text-xs">
                            {formatCron(schedule.cron)} · tz:{' '}
                            {schedule.timezone} · next:{' '}
                            {formatTimestamp(schedule.next_run_at)}
                          </p>
                        </div>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => openEdit(schedule)}
                            className="border-primary text-primary hover:bg-primary/90 rounded-full border border-solid px-5 py-1 text-sm transition-colors hover:text-white"
                          >
                            {t('agents.schedules.edit')}
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              dispatch(
                                setSchedulePaused({
                                  id: schedule.id,
                                  action:
                                    schedule.status === 'active'
                                      ? 'pause'
                                      : 'resume',
                                  token,
                                }),
                              )
                            }
                            className="border-primary text-primary hover:bg-primary/90 rounded-full border border-solid px-5 py-1 text-sm transition-colors hover:text-white"
                          >
                            {schedule.status === 'active'
                              ? t('agents.schedules.pause')
                              : t('agents.schedules.resume')}
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              dispatch(
                                runScheduleNow({ id: schedule.id, token }),
                              )
                            }
                            className="border-primary text-primary hover:bg-primary/90 rounded-full border border-solid px-5 py-1 text-sm transition-colors hover:text-white"
                          >
                            {t('agents.schedules.runNow')}
                          </button>
                          <button
                            type="button"
                            onClick={() => requestDelete(schedule)}
                            className="rounded-full border border-solid border-red-500 px-5 py-1 text-sm text-red-500 transition-colors hover:bg-red-500 hover:text-white"
                          >
                            {t('agents.schedules.delete')}
                          </button>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() =>
                          setExpanded(
                            expanded === schedule.id ? null : schedule.id,
                          )
                        }
                        className="text-primary mt-2 text-xs underline"
                      >
                        {expanded === schedule.id
                          ? t('agents.schedules.hideRuns')
                          : t('agents.schedules.showRuns')}
                      </button>
                      {expanded === schedule.id && (
                        <div className="mt-2">
                          <RunLog
                            scheduleId={schedule.id}
                            onSelect={(run) => setActiveRun(run)}
                          />
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section>
              <h3 className="text-muted-foreground mb-2 text-sm font-semibold uppercase">
                {t('agents.schedules.oneTime')} ({oneTime.length})
              </h3>
              {oneTime.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  {t('agents.schedules.noOneTime')}
                </p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {oneTime.map((schedule) => (
                    <li
                      key={schedule.id}
                      className="border-border bg-card rounded-lg border p-3 text-sm"
                    >
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="flex items-center gap-2">
                            <p className="font-semibold">
                              {schedule.name ||
                                schedule.instruction.slice(0, 80)}
                            </p>
                            <ScheduleStatusBadge status={schedule.status} />
                          </div>
                          <p className="text-muted-foreground text-xs">
                            runs at {formatTimestamp(schedule.run_at)}
                          </p>
                        </div>
                        <div className="flex gap-2">
                          {schedule.status === 'active' && (
                            <button
                              type="button"
                              onClick={() => openEdit(schedule)}
                              className="border-primary text-primary hover:bg-primary/90 rounded-full border border-solid px-5 py-1 text-sm transition-colors hover:text-white"
                            >
                              {t('agents.schedules.edit')}
                            </button>
                          )}
                          {schedule.status === 'active' && (
                            <button
                              type="button"
                              onClick={() => requestDelete(schedule)}
                              className="rounded-full border border-solid border-red-500 px-5 py-1 text-sm text-red-500 transition-colors hover:bg-red-500 hover:text-white"
                            >
                              {t('agents.schedules.cancel')}
                            </button>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <RunDetailDrawer
              run={activeRun}
              onClose={() => setActiveRun(null)}
            />
            {modalOpen && (
              <ScheduleFormModal
                key={editing?.id ?? 'create'}
                open={modalOpen}
                initial={editing}
                agentToolIds={agentToolIds}
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
              variant="danger"
            />
          </div>
        )
      )}
    </div>
  );
}
