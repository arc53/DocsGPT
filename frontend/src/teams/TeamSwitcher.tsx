import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Building2,
  Check,
  ChevronsUpDown,
  Plus,
  Settings as SettingsIcon,
  Users,
} from 'lucide-react';

import DocsGPT3 from '../assets/cute_docsgpt3.svg';
import { selectToken } from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import {
  loadTeams,
  selectCurrentTeamId,
  selectTeams,
  setCurrentTeam,
} from './teamsSlice';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';

type TeamSwitcherProps = {
  // Called after a navigation/selection so callers (e.g. the mobile nav) can
  // close themselves. Optional.
  onNavigate?: () => void;
  // Icon-only trigger for the collapsed sidebar (no label/chevron).
  collapsed?: boolean;
};

/**
 * Brand header that doubles as the team/workspace switcher.
 *
 * The whole row is the dropdown trigger and morphs its identity: in a
 * personal context it shows the DocsGPT logo + wordmark; inside a team it
 * shows an initial avatar + the team name. The dropdown lets the user
 * quick-switch teams, jump to team management, or create a new team.
 * Switching is a UX-only selection persisted in the teams slice via
 * setCurrentTeam; it does not scope app data.
 */
export default function TeamSwitcher({
  onNavigate,
  collapsed = false,
}: TeamSwitcherProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();

  const token = useSelector(selectToken);
  const teams = useSelector(selectTeams);
  const currentTeamId = useSelector(selectCurrentTeamId);

  // Populate the switcher on mount so it works before visiting settings.
  useEffect(() => {
    dispatch(loadTeams({ token }));
  }, [dispatch, token]);

  const safeTeams = teams ?? [];
  const currentTeam =
    safeTeams.find((team) => team.id === currentTeamId) ?? null;
  const currentRoleLabel = currentTeam
    ? currentTeam.member_role === 'team_admin'
      ? t('teams.switcher.roleAdmin')
      : t('teams.switcher.roleMember')
    : t('teams.switcher.personalSubtitle');
  const currentName = currentTeam
    ? currentTeam.name
    : t('teams.switcher.personal');
  // The header trigger shows the brand ("DocsGPT") in a personal context rather
  // than "Personal account" — the dropdown still labels the switch entry
  // "Personal account".
  const triggerLabel = currentTeam ? currentTeam.name : 'DocsGPT';
  const teamInitial = currentTeam
    ? currentTeam.name.charAt(0).toUpperCase()
    : '';

  // The morphing brand identity shown in the trigger: the DocsGPT logo for a
  // personal context, or an initial avatar for a team.
  const triggerIcon = currentTeam ? (
    // A solid square reads heavier than the dino, so keep the team avatar a
    // touch smaller (with a little margin to align with the wordmark).
    <span className="bg-muted dark:bg-accent text-foreground mx-1 flex size-7 shrink-0 items-center justify-center rounded-md text-sm font-semibold">
      {teamInitial}
    </span>
  ) : (
    <img className="h-9 shrink-0" src={DocsGPT3} alt="DocsGPT Logo" />
  );

  // Open the active team's detail directly (not just the list).
  const goToManage = () => {
    navigate('/teams', { state: { openTeamId: currentTeam?.id } });
    onNavigate?.();
  };

  // Land on /teams with the create modal already open.
  const goToCreate = () => {
    navigate('/teams', { state: { create: true } });
    onNavigate?.();
  };

  const selectTeam = (teamId: string | null) => {
    dispatch(setCurrentTeam(teamId));
    onNavigate?.();
  };

  // Teams other than the currently active one, for the "switch to" list.
  const otherTeams = safeTeams.filter((team) => team.id !== currentTeamId);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {collapsed ? (
          <button
            type="button"
            aria-label={t('teams.switcher.ariaLabel')}
            className="hover:bg-muted dark:hover:bg-accent flex items-center justify-center rounded-lg p-1 transition-colors"
          >
            {triggerIcon}
          </button>
        ) : (
          <button
            type="button"
            aria-label={t('teams.switcher.ariaLabel')}
            className="hover:bg-muted dark:hover:bg-accent text-foreground flex w-full items-center gap-1.5 rounded-lg px-2 py-1 text-left transition-colors"
          >
            {triggerIcon}
            <span className="text-foreground min-w-0 flex-1 truncate text-xl font-semibold dark:text-white">
              {triggerLabel}
            </span>
            <ChevronsUpDown
              className="text-muted-foreground size-4 shrink-0"
              strokeWidth={1.75}
            />
          </button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-62">
        <DropdownMenuLabel className="flex items-center gap-2">
          <span className="bg-muted dark:bg-accent flex size-7 shrink-0 items-center justify-center rounded-md">
            {currentTeam ? (
              <Users className="size-4" strokeWidth={1.75} />
            ) : (
              <Building2 className="size-4" strokeWidth={1.75} />
            )}
          </span>
          <span className="min-w-0 flex-1">
            <span className="text-foreground block truncate text-sm font-semibold">
              {currentName}
            </span>
            <span className="text-muted-foreground block truncate text-xs font-normal">
              {currentRoleLabel}
            </span>
          </span>
        </DropdownMenuLabel>

        {currentTeam && (
          <DropdownMenuItem onSelect={goToManage}>
            <SettingsIcon className="size-4" strokeWidth={1.75} />
            <span>{t('teams.switcher.manageTeam')}</span>
          </DropdownMenuItem>
        )}

        <DropdownMenuSeparator />

        {/* Personal account entry */}
        {currentTeam && (
          <DropdownMenuItem onSelect={() => selectTeam(null)}>
            <Building2 className="size-4" strokeWidth={1.75} />
            <span className="min-w-0 flex-1 truncate">
              {t('teams.switcher.personal')}
            </span>
            {!currentTeam && <Check className="size-4 shrink-0" />}
          </DropdownMenuItem>
        )}

        {/* Other teams to switch to */}
        {otherTeams.map((team) => (
          <DropdownMenuItem key={team.id} onSelect={() => selectTeam(team.id)}>
            <Users className="size-4" strokeWidth={1.75} />
            <span className="min-w-0 flex-1 truncate" title={team.name}>
              {team.name}
            </span>
          </DropdownMenuItem>
        ))}

        <DropdownMenuSeparator />

        <DropdownMenuItem onSelect={goToCreate}>
          <Plus className="size-4" strokeWidth={1.75} />
          <span>{t('teams.switcher.createTeam')}</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
