import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { Check, ChevronsUpDown, Plus, Settings, User } from 'lucide-react';

import DocsGPTMark from '../assets/logo-b.svg';
import DocsGPTMarkWhite from '../assets/logo-w.svg';
import { useDarkTheme } from '../hooks';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import { focusRing } from '../lib/utils';
import useWorkspace from '../workspace/useWorkspace';
import {
  selectWorkspaces,
  type WorkspaceRole,
  type WorkspaceRow,
} from '../workspace/workspaceSlice';

type TeamSwitcherProps = {
  // Called after a navigation/selection so callers (e.g. the mobile nav) can
  // close themselves. Optional.
  onNavigate?: () => void;
  // Icon-only trigger for the collapsed sidebar (no label/chevron).
  collapsed?: boolean;
};

const ROLE_KEYS: Record<WorkspaceRole, string> = {
  owner: 'workspace.common.roles.owner',
  admin: 'workspace.common.roles.admin',
  editor: 'workspace.common.roles.editor',
  viewer: 'workspace.common.roles.viewer',
};

/** A team's initial in a square, the team's mark wherever it is named. */
function TeamInitial({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  return (
    <Avatar size="xs" shape="square" variant="icon" className={className}>
      <span className="text-foreground text-sm font-semibold">
        {name.charAt(0).toUpperCase()}
      </span>
    </Avatar>
  );
}

/**
 * Brand header that doubles as the workspace switcher.
 *
 * The row names the workspace the app is in and the caller's place there:
 * "Personal · Only you", or a team's initial, name and "Team · Admin". The
 * menu lists Personal and every team with how many people are in it and the
 * caller's role, checks the current one, and ends in "Manage teams" (or
 * "Create team" while the user has none). Picking one switches every list,
 * chats included.
 */
export default function TeamSwitcher({
  onNavigate,
  collapsed = false,
}: TeamSwitcherProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id: currentId, workspace, role, isTeam, switchTo } = useWorkspace();
  const workspaces = useSelector(selectWorkspaces);
  const [isDarkTheme] = useDarkTheme();

  const roleWord = (r: WorkspaceRole | null | undefined) =>
    t(ROLE_KEYS[r ?? 'viewer']);
  const teams = workspaces.filter((row) => row.kind === 'team');
  const hasTeams = teams.length > 0;

  const currentName = isTeam
    ? workspace.name
    : t('workspace.switcher.personal');
  const currentSubtitle = isTeam
    ? t('workspace.switcher.teamRole', { role: roleWord(role) })
    : t('workspace.switcher.onlyYou');

  // The mark leading the row: the team's initial, or the DocsGPT mark in
  // Personal. A solid square reads heavier than the dino, so the team mark
  // keeps a little margin to align with the labels below it.
  const mark = isTeam ? (
    <TeamInitial name={workspace.name} className="mx-1" />
  ) : (
    <img
      className="h-8 w-auto shrink-0"
      src={isDarkTheme ? DocsGPTMarkWhite : DocsGPTMark}
      alt={t('teams.switcher.logoAlt')}
    />
  );

  const goToManage = () => {
    navigate('/teams');
    onNavigate?.();
  };

  // Land on /teams with the create modal already open.
  const goToCreate = () => {
    navigate('/teams', { state: { create: true } });
    onNavigate?.();
  };

  const select = (id: string) => {
    if (id === currentId) return;
    switchTo(id);
    onNavigate?.();
  };

  const teamMeta = (team: WorkspaceRow) =>
    t('workspace.switcher.teamMeta', {
      count: team.member_count ?? 0,
      role: roleWord(team.role),
    });

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {collapsed ? (
          <button
            type="button"
            aria-label={t('teams.switcher.ariaLabel')}
            title={currentName}
            className={`${focusRing} hover:bg-sidebar-accent flex items-center justify-center rounded-full p-1 transition-colors outline-none`}
          >
            {mark}
          </button>
        ) : (
          <Button
            type="button"
            variant="sidebar-item"
            size="lg"
            aria-label={t('teams.switcher.ariaLabel')}
            className="w-full"
          >
            {mark}
            <span className="min-w-0 flex-1 text-left">
              <span
                className="text-foreground block truncate text-sm leading-tight font-semibold"
                title={currentName}
              >
                {currentName}
              </span>
              <span className="text-muted-foreground block truncate text-xs leading-tight font-normal">
                {currentSubtitle}
              </span>
            </span>
            {/* sidebar-item rows carry no right padding, so the chevron's
                margin keeps it clear of the pill's end. */}
            <ChevronsUpDown className="text-muted-foreground mr-3 size-4" />
          </Button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-62">
        <DropdownMenuItem onSelect={() => select('personal')}>
          <Avatar size="xs" shape="square" variant="icon">
            <User className="text-foreground size-4" />
          </Avatar>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium">
              {t('workspace.switcher.personal')}
            </span>
            <span className="text-muted-foreground block truncate text-xs">
              {t('workspace.switcher.onlyYou')}
            </span>
          </span>
          {!isTeam && <Check className="text-primary size-4 shrink-0" />}
        </DropdownMenuItem>

        {hasTeams && (
          <DropdownMenuLabel>
            <span className="text-muted-foreground text-xs">
              {t('workspace.switcher.teams')}
            </span>
          </DropdownMenuLabel>
        )}
        {teams.map((team) => (
          <DropdownMenuItem key={team.id} onSelect={() => select(team.id)}>
            <TeamInitial name={team.name} />
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium" title={team.name}>
                {team.name}
              </span>
              <span className="text-muted-foreground block truncate text-xs">
                {teamMeta(team)}
              </span>
            </span>
            {team.id === currentId && (
              <Check className="text-primary size-4 shrink-0" />
            )}
          </DropdownMenuItem>
        ))}

        <DropdownMenuSeparator />

        {/* With no teams there is nothing to manage yet, so offer creation;
            once one exists, the teams page covers both. */}
        {hasTeams ? (
          <DropdownMenuItem onSelect={goToManage}>
            <Settings className="size-4" />
            <span>{t('teams.switcher.manageTeams')}</span>
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem onSelect={goToCreate}>
            <Plus className="size-4" />
            <span>{t('teams.switcher.createTeam')}</span>
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
