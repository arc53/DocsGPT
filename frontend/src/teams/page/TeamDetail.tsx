import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';

import teamsService, {
  type TeamGrant,
  type TeamRole,
  teamRoleOf,
} from '../../api/services/teamsService';
import SkeletonLoader from '../../components/SkeletonLoader';
import { Avatar } from '../../components/ui/avatar';
import { Button } from '../../components/ui/button';
import { EmptyState } from '../../components/ui/empty-state';
import { NavTab } from '../../components/ui/tabs';
import DetailBreadcrumb from '../../navigation/DetailBreadcrumb';
import SectionShell from '../../navigation/SectionShell';
import { showActionToast } from '../../notifications/actionToastSlice';
import { selectToken } from '../../preferences/preferenceSlice';
import { AppDispatch } from '../../store';
import { formatCount } from '../../utils/dateTimeUtils';
import {
  loadTeams,
  selectTeams,
  selectTeamsError,
  selectTeamsLoading,
} from '../teamsSlice';
import MembersTab from './MembersTab';
import SettingsTab from './SettingsTab';
import SharedItemsTab from './SharedItemsTab';
import UsageTab from './UsageTab';
import { initialOf } from './teamGrants';
import {
  TEAM_TABS,
  TEAMS_ROOT,
  type TeamTabKey,
  teamPath,
  visibleTeamTabs,
} from './teamTabs';

/**
 * One team's page at `/teams/:teamId/:tab?`: the team's name and the
 * caller's role, then tabs (Members, Personal items shared, and Usage and
 * Settings for its owner and admins). A tab the caller may not open, or one that
 * isn't built, goes to Members.
 */
export default function TeamDetail() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();
  const { teamId = '', tab } = useParams();
  const token = useSelector(selectToken);
  const teams = useSelector(selectTeams);
  const teamsLoading = useSelector(selectTeamsLoading);
  const teamsError = useSelector(selectTeamsError);
  const team = teams.find((row) => row.id === teamId) ?? null;

  const [grants, setGrants] = useState<TeamGrant[]>([]);
  // The caller's role as the grants answer says it: fresher than the list's.
  const [liveRole, setLiveRole] = useState<TeamRole | null>(null);
  const [grantsSettled, setGrantsSettled] = useState(false);

  useEffect(() => {
    dispatch(loadTeams({ token }));
  }, []);

  const loadGrants = useCallback(async () => {
    if (!team) return;
    try {
      const g = await teamsService.listGrants(team.id, undefined, token);
      setGrants(g?.grants ?? []);
      setLiveRole(
        g?.role || g?.team_role
          ? teamRoleOf({ role: g.role, member_role: g.team_role })
          : null,
      );
    } catch {
      // The page still works on the list's role; say the list didn't load.
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('settings.teams.openTeamError'),
        }),
      );
    } finally {
      setGrantsSettled(true);
    }
  }, [team?.id, token]);

  useEffect(() => {
    setGrants([]);
    setLiveRole(null);
    setGrantsSettled(false);
    loadGrants();
  }, [loadGrants]);

  if (!team) {
    return (
      <SectionShell>
        {teamsLoading ? (
          <SkeletonLoader component="default" />
        ) : (
          <EmptyState
            size="sm"
            tone={teamsError ? 'destructive' : undefined}
            illustration="none"
            title={
              teamsError
                ? t('settings.teams.loadError')
                : t('settings.teams.detail.notFound')
            }
            onRetry={
              teamsError ? () => dispatch(loadTeams({ token })) : undefined
            }
            action={
              teamsError ? undefined : (
                <Button
                  type="button"
                  variant="outline"
                  shape="pill"
                  onClick={() => navigate(TEAMS_ROOT)}
                >
                  {t('settings.teams.detail.backToTeams')}
                </Button>
              )
            }
          />
        )}
      </SectionShell>
    );
  }

  const role: TeamRole = liveRole ?? teamRoleOf(team);
  const tabs = visibleTeamTabs(role);
  const requested = (tab ?? 'members') as TeamTabKey;
  const current = tabs.find((entry) => entry.key === requested);
  // A built tab the list's role doesn't reach may still be reached by the
  // live role; wait for it before sending the caller elsewhere.
  const knownTab = TEAM_TABS.some(
    (entry) => entry.key === requested && entry.enabled,
  );
  if (!current) {
    if (!knownTab || grantsSettled)
      return <Navigate to={teamPath(team.id)} replace />;
    return (
      <SectionShell>
        <SkeletonLoader component="default" />
      </SectionShell>
    );
  }

  return (
    <SectionShell>
      <div className="flex flex-col gap-6">
        <div className="flex min-h-9.5 items-center">
          <DetailBreadcrumb
            parentLabel={t('settings.teams.label')}
            currentLabel={team.name}
            onParentClick={() => navigate(TEAMS_ROOT)}
          />
        </div>

        <div className="flex min-w-0 items-center gap-3">
          <span aria-hidden="true" className="contents">
            <Avatar alt="" size="lg" shape="square" variant="muted">
              {initialOf(team.name)}
            </Avatar>
          </span>
          <div className="min-w-0">
            <h3
              className="text-foreground truncate text-xl leading-tight font-semibold"
              title={team.name}
            >
              {team.name}
            </h3>
            <p className="text-muted-foreground mt-1 text-sm">
              {t('settings.teams.detail.meta', {
                interpolation: { escapeValue: false },
                role: t(`workspace.common.roles.${role}`),
                members: t('settings.teams.memberCount', {
                  count: team.member_count ?? 0,
                  formatted: formatCount(team.member_count ?? 0),
                }),
              })}
            </p>
            {team.description && (
              <p
                className="text-muted-foreground mt-1 line-clamp-2 text-sm"
                title={team.description}
              >
                {team.description}
              </p>
            )}
          </div>
        </div>

        <nav
          aria-label={t('settings.teams.tabs.label')}
          className="border-border flex items-center border-b"
        >
          {tabs.map((entry) => (
            // -mb-px lays the tab's 2px underline over the nav's 1px baseline.
            <NavTab
              key={entry.key}
              current={entry.key === current.key}
              className="-mb-px"
            >
              {entry.key === current.key ? (
                <span>{t(entry.labelKey)}</span>
              ) : (
                <Link to={teamPath(team.id, entry.key)}>
                  {t(entry.labelKey)}
                </Link>
              )}
            </NavTab>
          ))}
        </nav>

        {current.key === 'members' && (
          <MembersTab
            team={team}
            role={role}
            grants={grants}
            onOwnRoleChanged={loadGrants}
          />
        )}
        {current.key === 'shared' && (
          <SharedItemsTab
            team={team}
            role={role}
            grants={grants}
            onGrantsChanged={loadGrants}
          />
        )}
        {current.key === 'usage' && <UsageTab team={team} role={role} />}
        {current.key === 'settings' && <SettingsTab team={team} role={role} />}
      </div>
    </SectionShell>
  );
}
