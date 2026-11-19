import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { NavLink } from 'react-router-dom';

import { Button } from '../components/ui/button';
import { IconButton } from '../components/ui/icon-button';
import { selectWorkspaceId } from '../workspace/workspaceSlice';
import { teamNavItem } from './sections';

/**
 * The sidebar's "Team" row in a team workspace, under Activity: it opens the
 * current team's page. Nothing in Personal.
 *
 * Args:
 *   onNavigate: Goes to a path the sidebar's way (it moves the sidebar to
 *     the page's section on the click); a modified click opens it as a link.
 *   rail: Draws it as an icon for the collapsed sidebar's rail, like the
 *     Activity and Agents icons beside it.
 */
export default function SidebarTeamEntry({
  onNavigate,
  rail = false,
}: {
  onNavigate: (path: string) => void;
  rail?: boolean;
}) {
  const { t } = useTranslation();
  const team = teamNavItem(useSelector(selectWorkspaceId));
  if (!team) return null;
  const Icon = team.icon;
  if (rail)
    return (
      <IconButton
        label={t(team.labelKey)}
        side="right"
        variant="ghost-muted"
        size="icon"
        onClick={() => onNavigate(team.path)}
      >
        <Icon aria-hidden />
      </IconButton>
    );
  return (
    <Button variant="sidebar-item" asChild className="mx-4 mt-2 flex">
      <NavLink
        to={team.path}
        onClick={(event) => {
          if (event.metaKey || event.ctrlKey || event.shiftKey) return;
          event.preventDefault();
          onNavigate(team.path);
        }}
      >
        <Icon className="text-muted-foreground size-5 shrink-0" aria-hidden />
        <span className="truncate">{t(team.labelKey)}</span>
      </NavLink>
    </Button>
  );
}
