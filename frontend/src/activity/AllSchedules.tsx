import { ArrowRight, MessageSquare, Plus, Users } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import PageToolbar from '@/components/PageToolbar';
import SearchInput from '@/components/SearchInput';
import { Avatar } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Combobox } from '@/components/ui/combobox';
import { EmptyState } from '@/components/ui/empty-state';
import { FormField } from '@/components/ui/form-field';
import { LoadingState } from '@/components/ui/loading-state';
import { SectionHeader } from '@/components/ui/section-header';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { canAgent } from '../agents/agentAccess';
import { agentSchedulesPath } from '../agents/paths';
import RunDetailDrawer from '../agents/schedules/RunDetailDrawer';
import ScheduleFormModal from '../agents/schedules/ScheduleFormModal';
import ScheduleRow from '../agents/schedules/ScheduleRow';
import {
  createSchedule,
  deleteSchedule,
  loadAllSchedules,
  runScheduleNow,
  selectAllSchedules,
  selectAllSchedulesError,
  selectAllSchedulesLoading,
  setSchedulePaused,
  updateSchedule,
} from '../agents/schedules/schedulesSlice';
import useScheduleAgentContext from '../agents/schedules/useScheduleAgentContext';
import type {
  Schedule,
  ScheduleCreatePayload,
  ScheduleRun,
  UserSchedule,
} from '../agents/types/schedule';
import ConfirmationModal from '../modals/ConfirmationModal';
import type { ActiveState } from '../models/misc';
import { selectAgents, selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';

/** The group key of schedules made in a chat without an agent. */
const CHAT_GROUP = 'chat';

type ScheduleGroup = {
  key: string;
  agentId: string | null;
  name: string;
  image?: string | null;
  /** A teammate's agent the caller manages through a team. */
  team: boolean;
  schedules: UserSchedule[];
};

/**
 * Activity › Schedules: every schedule the caller owns, across agents,
 * grouped by agent, with the agentless ones the assistant made in a chat
 * last. Rows work as on an agent's Schedules page.
 */
export default function AllSchedules() {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const schedules = useSelector(selectAllSchedules);
  const loading = useSelector(selectAllSchedulesLoading);
  const failed = useSelector(selectAllSchedulesError);
  const agents = useSelector(selectAgents);

  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [activeRun, setActiveRun] = useState<ScheduleRun | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Schedule | null>(null);
  // The agent picked in the form while creating; editing uses the schedule's.
  const [newAgentId, setNewAgentId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deleteState, setDeleteState] = useState<ActiveState>('INACTIVE');
  const [toDelete, setToDelete] = useState<Schedule | null>(null);

  const formAgentId = editing ? editing.agent_id : newAgentId;
  const formContext = useScheduleAgentContext(modalOpen ? formAgentId : null);

  useEffect(() => {
    dispatch(loadAllSchedules({ token }));
  }, [dispatch, token]);

  const agentNames = useMemo(
    () => new Map((agents ?? []).map((agent) => [agent.id, agent.name])),
    [agents],
  );

  // Agents the caller may add a schedule to.
  const agentOptions = useMemo(
    () =>
      (agents ?? [])
        .filter((agent) => agent.id && canAgent(agent, 'manage_schedules'))
        .map((agent) => ({
          value: agent.id as string,
          label: agent.name,
          leading: (
            <Avatar
              src={agent.image}
              alt=""
              size="xs"
              shape="circle"
              imgClassName="size-6 object-contain"
            />
          ),
        })),
    [agents],
  );

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return schedules ?? [];
    return (schedules ?? []).filter((schedule) =>
      [
        schedule.name,
        schedule.instruction,
        schedule.agent_name,
        schedule.origin_conversation_name,
      ].some((value) => value?.toLowerCase().includes(needle)),
    );
  }, [schedules, search]);

  const groupsFor = (list: UserSchedule[]): ScheduleGroup[] => {
    const byKey = new Map<string, ScheduleGroup>();
    for (const schedule of list) {
      const key = schedule.agent_id ?? CHAT_GROUP;
      let group = byKey.get(key);
      if (!group) {
        group = {
          key,
          agentId: schedule.agent_id,
          name: schedule.agent_id
            ? schedule.agent_name ||
              agentNames.get(schedule.agent_id) ||
              t('agents.pageHeader.fallbackName')
            : t('activity.schedules.createdInChat'),
          image: schedule.agent_image,
          team: Boolean(schedule.team),
          schedules: [],
        };
        byKey.set(key, group);
      }
      group.schedules.push(schedule);
    }
    return [...byKey.values()].sort((a, b) => {
      if (a.key === CHAT_GROUP) return 1;
      if (b.key === CHAT_GROUP) return -1;
      return a.name.localeCompare(b.name);
    });
  };

  const recurring = filtered.filter((s) => s.trigger_type === 'recurring');
  const oneTime = filtered.filter((s) => s.trigger_type === 'once');

  const openCreate = () => {
    setEditing(null);
    setNewAgentId(null);
    setModalOpen(true);
  };

  const openEdit = (schedule: Schedule) => {
    setEditing(schedule);
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setEditing(null);
    setNewAgentId(null);
  };

  const handleSubmit = async (payload: ScheduleCreatePayload) => {
    setSubmitting(true);
    try {
      if (editing?.id) {
        await dispatch(
          updateSchedule({ id: editing.id, payload, token }),
        ).unwrap();
      } else if (newAgentId) {
        await dispatch(
          createSchedule({ agentId: newAgentId, payload, token }),
        ).unwrap();
      }
      closeModal();
    } finally {
      setSubmitting(false);
    }
  };

  // Returned to ConfirmationModal: it stays pending while the delete runs.
  const confirmDelete = async () => {
    if (!toDelete) return;
    await dispatch(deleteSchedule({ id: toDelete.id, token })).unwrap();
    setToDelete(null);
  };

  const newButton = (
    <Button type="button" size="field" shape="pill" onClick={openCreate}>
      <Plus />
      {t('agents.schedules.newRecurring')}
    </Button>
  );

  const renderGroups = (list: UserSchedule[], emptyKey: string) => {
    if (list.length === 0) {
      return (
        <Card variant="subtle" padding="lg">
          <EmptyState
            size="sm"
            illustration="none"
            title={search ? t('activity.schedules.noMatches') : t(emptyKey)}
          />
        </Card>
      );
    }
    return (
      <div className="flex flex-col gap-8">
        {groupsFor(list).map((group) => (
          <section key={group.key} className="flex flex-col gap-3">
            <div className="flex items-center gap-2.5">
              {group.agentId ? (
                <Avatar
                  src={group.image}
                  alt=""
                  size="xs"
                  shape="circle"
                  imgClassName="size-6 object-contain"
                />
              ) : (
                <Avatar variant="icon" size="xs" shape="circle">
                  <MessageSquare aria-hidden className="size-3.5" />
                </Avatar>
              )}
              <SectionHeader
                as="h2"
                size="xs"
                className="min-w-0 flex-1"
                title={group.name}
                count={group.schedules.length}
                description={
                  group.agentId
                    ? undefined
                    : t('activity.schedules.createdInChatHint')
                }
                actions={
                  group.agentId ? (
                    <div className="flex items-center gap-2">
                      {group.team && (
                        <Badge
                          variant="neutral"
                          title={t('activity.schedules.teamAgent')}
                        >
                          <Users aria-hidden />
                          {t('teamAccess.editor')}
                        </Badge>
                      )}
                      <Button
                        variant="link"
                        size="sm"
                        className="-mr-3"
                        asChild
                      >
                        <Link to={agentSchedulesPath(group.agentId)}>
                          {t('activity.schedules.agentSchedules')}
                          <ArrowRight aria-hidden className="size-3" />
                        </Link>
                      </Button>
                    </div>
                  ) : undefined
                }
              />
            </div>
            <ul className="flex flex-col gap-3">
              {group.schedules.map((schedule) => (
                <li key={schedule.id}>
                  <ScheduleRow
                    schedule={schedule}
                    expanded={expanded === schedule.id}
                    onToggleRuns={(id) =>
                      setExpanded(expanded === id ? null : id)
                    }
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
                    onDelete={(target) => {
                      setToDelete(target);
                      setDeleteState('ACTIVE');
                    }}
                    onSelectRun={setActiveRun}
                    extraMeta={
                      !schedule.agent_id && schedule.origin_conversation_id ? (
                        <Button
                          variant="link"
                          size="text"
                          asChild
                          /* eslint-disable-next-line shadcn/no-restyle -- the meta line's 4px icon gap, like Next run and Last run beside it; a long chat name wraps beside the icon */
                          className="min-w-0 shrink gap-1 whitespace-normal"
                        >
                          <Link to={`/c/${schedule.origin_conversation_id}`}>
                            <MessageSquare
                              aria-hidden
                              className="size-3.5 shrink-0"
                            />
                            {schedule.origin_conversation_name ||
                              t('activity.schedules.openChat')}
                          </Link>
                        </Button>
                      ) : undefined
                    }
                  />
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    );
  };

  // An edit waits for its agent's tools: the form reads them once, on mount.
  const formReady = !editing || formContext.ready;

  return (
    <>
      <PageToolbar
        intro={t('activity.schedules.subtitle')}
        search={
          <SearchInput
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('activity.schedules.search')}
          />
        }
        action={newButton}
      />
      {schedules === null && loading ? (
        <LoadingState fill="block" />
      ) : schedules === null && failed ? (
        <EmptyState
          tone="destructive"
          title={t('activity.schedules.loadError')}
          onRetry={() => dispatch(loadAllSchedules({ token }))}
        />
      ) : (schedules ?? []).length === 0 ? (
        <EmptyState
          title={t('activity.schedules.empty')}
          description={t('activity.schedules.emptyHint')}
          action={newButton}
        />
      ) : (
        <Tabs defaultValue="recurring">
          <TabsList>
            <TabsTrigger value="recurring">
              {t('agents.schedules.recurring')}
              <Badge variant="neutral">{recurring.length}</Badge>
            </TabsTrigger>
            <TabsTrigger value="once">
              {t('agents.schedules.oneTime')}
              <Badge variant="neutral">{oneTime.length}</Badge>
            </TabsTrigger>
          </TabsList>
          <TabsContent value="recurring" className="mt-6">
            {renderGroups(recurring, 'agents.schedules.noRecurring')}
          </TabsContent>
          <TabsContent value="once" className="mt-6">
            {renderGroups(oneTime, 'agents.schedules.noOneTime')}
          </TabsContent>
        </Tabs>
      )}
      <RunDetailDrawer run={activeRun} onClose={() => setActiveRun(null)} />
      {modalOpen && formReady && (
        <ScheduleFormModal
          key={editing?.id ?? 'create'}
          open={modalOpen}
          initial={editing}
          approvalTools={formContext.approvalTools}
          onClose={closeModal}
          onSubmit={handleSubmit}
          submitting={submitting}
          submitDisabled={!editing && !newAgentId}
          agentField={
            editing ? undefined : (
              <FormField label={t('activity.schedules.agentLabel')}>
                <Combobox
                  options={agentOptions}
                  value={newAgentId}
                  onValueChange={(value) => setNewAgentId(value)}
                  placeholder={t('activity.schedules.agentPlaceholder')}
                  searchPlaceholder={t('activity.schedules.agentSearch')}
                  emptyText={t('activity.schedules.agentEmpty')}
                />
              </FormField>
            )
          }
        />
      )}
      <ConfirmationModal
        message={t('agents.schedules.deleteConfirm', {
          interpolation: { escapeValue: false },
          name: toDelete?.name || toDelete?.instruction.slice(0, 80) || '',
        })}
        description={t('agents.schedules.deleteConsequence')}
        modalState={deleteState}
        setModalState={setDeleteState}
        submitLabel={t('agents.schedules.delete')}
        handleSubmit={confirmDelete}
        error={t('agents.schedules.deleteFailed')}
        handleCancel={() => setToDelete(null)}
        variant="destructive"
      />
    </>
  );
}
