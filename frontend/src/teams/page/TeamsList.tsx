import { ChevronRight, Users } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import { teamRoleOf } from '../../api/services/teamsService';
import PageToolbar from '../../components/PageToolbar';
import SkeletonLoader from '../../components/SkeletonLoader';
import { Alert, AlertDescription } from '../../components/ui/alert';
import { Avatar } from '../../components/ui/avatar';
import { Button } from '../../components/ui/button';
import {
  Card,
  CardDescription,
  CardFooter,
  CardTitle,
} from '../../components/ui/card';
import { EmptyState } from '../../components/ui/empty-state';
import { FormField } from '../../components/ui/form-field';
import { Input } from '../../components/ui/input';
import { Modal, ModalActions } from '../../components/ui/modal';
import { Pagination, pageRangeParams } from '../../components/ui/pagination';
import { SHORT_LIST_PAGE_SIZE, useClientPage } from '../../hooks/usePageState';
import SectionShell from '../../navigation/SectionShell';
import { selectToken } from '../../preferences/preferenceSlice';
import { AppDispatch } from '../../store';
import { formatCount } from '../../utils/dateTimeUtils';
import {
  createTeam,
  loadTeams,
  selectTeams,
  selectTeamsError,
  selectTeamsLoading,
} from '../teamsSlice';
import { initialOf } from './teamGrants';
import { TeamRoleBadge } from './TeamRoleSelect';
import { teamPath } from './teamTabs';

/**
 * The caller's teams as cards, each opening its page; New team creates one
 * and opens it. The switcher's "Create team" arrives with `create` in the
 * navigation state.
 */
export default function TeamsList() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const teams = useSelector(selectTeams);
  const teamsLoading = useSelector(selectTeamsLoading);
  const teamsError = useSelector(selectTeamsError);

  const [createOpen, setCreateOpen] = useState(false);
  const [newTeamName, setNewTeamName] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    dispatch(loadTeams({ token }));
  }, []);

  const openCreateModal = () => {
    setNewTeamName('');
    setCreateError(null);
    setCreateOpen(true);
  };

  const closeCreateModal = () => {
    setCreateOpen(false);
    setNewTeamName('');
    setCreateError(null);
  };

  // Navigation intent: `create` pops the create modal; `openTeamId` (an
  // older link into a team) goes to that team's page. Consumed once, then
  // cleared so a refresh or Back doesn't repeat it.
  useEffect(() => {
    const st = location.state as {
      create?: boolean;
      openTeamId?: string;
    } | null;
    if (!st || (!st.create && !st.openTeamId)) return;
    if (st.openTeamId) {
      navigate(teamPath(st.openTeamId), { replace: true });
      return;
    }
    openCreateModal();
    navigate(location.pathname, { replace: true, state: null });
  }, [location.key]);

  const handleCreate = async () => {
    if (!newTeamName.trim() || pending) return;
    setCreateError(null);
    setPending(true);
    try {
      const created = await dispatch(
        createTeam({ name: newTeamName.trim(), token }),
      ).unwrap();
      setNewTeamName('');
      setCreateOpen(false);
      if (created?.id) navigate(teamPath(created.id));
    } catch {
      // Keep the modal open and say so, so the user can retry.
      setCreateError(t('settings.teams.createTeamError'));
    } finally {
      setPending(false);
    }
  };

  const {
    page: teamsPage,
    setPage: setTeamsPage,
    pageItems: pageTeams,
  } = useClientPage(teams, SHORT_LIST_PAGE_SIZE, '');

  return (
    <SectionShell>
      <div>
        <PageToolbar
          intro={t('settings.teams.subtitle')}
          action={
            <Button size="field" shape="pill" onClick={openCreateModal}>
              {t('settings.teams.newTeam')}
            </Button>
          }
        />
        {teamsLoading && teams.length === 0 ? (
          <SkeletonLoader component="default" />
        ) : teamsError ? (
          <EmptyState
            tone="destructive"
            size="sm"
            illustration="none"
            title={t('settings.teams.loadError')}
            onRetry={() => dispatch(loadTeams({ token }))}
          />
        ) : teams.length === 0 ? (
          <EmptyState
            title={t('settings.teams.noTeams')}
            action={
              <Button type="button" shape="pill" onClick={openCreateModal}>
                {t('settings.teams.newTeam')}
              </Button>
            }
          />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {pageTeams.map((team) => (
                <Card
                  key={team.id}
                  asChild
                  variant="filled"
                  padding="lg"
                  interactive
                  className="group h-full"
                >
                  <button onClick={() => navigate(teamPath(team.id))}>
                    <div className="flex items-center gap-3">
                      <span aria-hidden="true" className="contents">
                        <Avatar
                          alt=""
                          size="default"
                          shape="square"
                          variant="muted"
                        >
                          {initialOf(team.name)}
                        </Avatar>
                      </span>
                      <CardTitle className="min-w-0 flex-1 truncate">
                        {team.name}
                      </CardTitle>
                      <TeamRoleBadge role={teamRoleOf(team)} />
                      <ChevronRight
                        className="text-muted-foreground size-4.5 shrink-0 transition-transform group-hover:translate-x-0.5"
                        aria-hidden
                      />
                    </div>
                    {team.description ? (
                      <CardDescription size="xs" className="line-clamp-2">
                        {team.description}
                      </CardDescription>
                    ) : null}
                    <CardFooter className="gap-1.5">
                      <Users className="size-3.5" aria-hidden />
                      <span>
                        {t('settings.teams.memberCount', {
                          count: team.member_count ?? 0,
                          formatted: formatCount(team.member_count ?? 0),
                        })}
                      </span>
                      <span aria-hidden>·</span>
                      <span>
                        {t('settings.teams.sharedCount', {
                          count: team.shared_count ?? 0,
                          formatted: formatCount(team.shared_count ?? 0),
                        })}
                      </span>
                    </CardFooter>
                  </button>
                </Card>
              ))}
            </div>
            <Pagination
              page={teamsPage}
              pageSize={SHORT_LIST_PAGE_SIZE}
              total={teams.length}
              onPageChange={setTeamsPage}
              rangeLabel={(range) =>
                t('settings.teams.pageRange', pageRangeParams(range))
              }
            />
          </>
        )}
      </div>

      <Modal
        open={createOpen}
        onOpenChange={(open) =>
          open ? setCreateOpen(true) : closeCreateModal()
        }
        size="sm"
        title={t('settings.teams.createTeam')}
        description={t('settings.teams.createTeamDescription')}
        footer={
          <ModalActions
            cancelLabel={t('cancel')}
            onCancel={closeCreateModal}
            submitLabel={t('settings.teams.create')}
            onSubmit={handleCreate}
            pending={pending}
            disabled={!newTeamName.trim()}
          />
        }
      >
        <FormField label={t('settings.teams.teamNamePlaceholder')}>
          <Input
            type="text"
            value={newTeamName}
            onChange={(e) => setNewTeamName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
          />
        </FormField>
        {createError && (
          <Alert variant="destructive" className="mt-3">
            <AlertDescription>{createError}</AlertDescription>
          </Alert>
        )}
      </Modal>
    </SectionShell>
  );
}
