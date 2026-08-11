import {
  ArrowLeft,
  Bot,
  ChevronRight,
  FileText,
  MessageSquare,
  MoreVertical,
  Pencil,
  Plus,
  Trash2,
  Users,
  Wrench,
} from 'lucide-react';
import { type ReactNode, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import teamsService, {
  ResourceType,
  TeamRole,
} from '../api/services/teamsService';
import userService from '../api/services/userService';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import SkeletonLoader from '../components/SkeletonLoader';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { Input } from '../components/ui/input';
import { Modal } from '../components/ui/modal';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { useDarkTheme } from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import {
  selectAgents,
  selectPrompts,
  selectSourceDocs,
  selectToken,
  setAgents,
} from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import {
  createTeam,
  deleteTeam,
  loadTeams,
  selectTeams,
  selectTeamsError,
  selectTeamsLoading,
  Team,
} from '../teams/teamsSlice';

type Member = {
  user_id: string;
  email?: string | null;
  role: TeamRole;
  source: string;
};

type Grant = {
  resource_type: string;
  resource_id: string;
  access_level: string;
};

const RESOURCE_TYPES: ReadonlyArray<ResourceType> = [
  'agent',
  'source',
  'prompt',
  'tool',
];

// Member subs (OIDC subs) can be long; truncate the middle for readability
// while keeping the ends identifiable when no email is available.
const truncateSub = (sub: string): string =>
  sub.length > 24 ? `${sub.slice(0, 12)}…${sub.slice(-8)}` : sub;

// First character of a label, uppercased, for initial avatars (ported from
// ShareToTeamModal to keep avatar treatment consistent across team UIs).
const initialOf = (label: string): string => {
  const trimmed = label.trim();
  return trimmed ? trimmed[0].toUpperCase() : '?';
};

export default function Teams() {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const teams = useSelector(selectTeams);
  const teamsLoading = useSelector(selectTeamsLoading);
  const teamsError = useSelector(selectTeamsError);
  const agents = useSelector(selectAgents);
  const sourceDocs = useSelector(selectSourceDocs);
  const prompts = useSelector(selectPrompts);

  const [selected, setSelected] = useState<Team | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  // Tools aren't kept in Redux; lazily fetch the user's tool instances (keyed
  // by id) only when a team actually has a tool grant, so shared-tool rows can
  // render a friendly name instead of the raw instance UUID.
  const [toolsById, setToolsById] = useState<Record<string, string>>({});
  const [newTeamName, setNewTeamName] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editError, setEditError] = useState<string | null>(null);
  const [newMemberEmail, setNewMemberEmail] = useState('');
  const [newMemberRole, setNewMemberRole] = useState<TeamRole>('team_member');
  const [addMemberOpen, setAddMemberOpen] = useState(false);
  const [addMemberError, setAddMemberError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [deleteTeamModalState, setDeleteTeamModalState] =
    useState<ActiveState>('INACTIVE');
  const [teamToDelete, setTeamToDelete] = useState<Team | null>(null);
  const [removeMemberModalState, setRemoveMemberModalState] =
    useState<ActiveState>('INACTIVE');
  const [memberToRemove, setMemberToRemove] = useState<string | null>(null);

  useEffect(() => {
    dispatch(loadTeams({ token }));
  }, []);

  const resourceTypeLabel = (type: string) =>
    RESOURCE_TYPES.includes(type as ResourceType)
      ? t(`settings.teams.resourceType.${type}`)
      : type;

  const memberLabel = (m: Member): string =>
    m.email && m.email.trim() !== '' ? m.email : truncateSub(m.user_id);

  // Where a membership came from: manual add, an SSO group claim, or SCIM
  // provisioning. Falls back to the raw source value for forward-compat.
  const sourceLabel = (s: string): string =>
    (
      ({
        manual: t('settings.teams.sourceManual'),
        oidc_group: t('settings.teams.sourceSso'),
        scim: t('settings.teams.sourceScim'),
      }) as Record<string, string>
    )[s] ?? s;

  // Resolve a grant's resource_id to its display name from the Redux-hydrated
  // lists (agents/sources/prompts) or the lazily-fetched tools map. Derived at
  // render so names appear as soon as those lists hydrate. Falls back to a
  // truncated id when the resource isn't found (e.g. not yet loaded).
  const resolveResourceName = (g: Grant): string => {
    switch (g.resource_type) {
      case 'agent':
        return (
          agents?.find((a) => a.id === g.resource_id)?.name ??
          truncateSub(g.resource_id)
        );
      case 'source':
        return (
          sourceDocs?.find((d) => d.id === g.resource_id)?.name ??
          truncateSub(g.resource_id)
        );
      case 'prompt':
        return (
          prompts?.find((p) => p.id === g.resource_id)?.name ??
          truncateSub(g.resource_id)
        );
      case 'tool':
        return toolsById[g.resource_id] ?? truncateSub(g.resource_id);
      default:
        return truncateSub(g.resource_id);
    }
  };

  // Lucide icon for a grant's resource type, shown in the row's type tile.
  const resourceTypeIcon = (type: string): ReactNode => {
    const props = { size: 16, strokeWidth: 1.75, 'aria-hidden': true } as const;
    switch (type) {
      case 'agent':
        return <Bot {...props} />;
      case 'source':
        return <FileText {...props} />;
      case 'prompt':
        return <MessageSquare {...props} />;
      case 'tool':
        return <Wrench {...props} />;
      default:
        return <FileText {...props} />;
    }
  };

  // Friendly label for a grant's access level; reuses the share-modal keys
  // when present, otherwise renders the raw value.
  const accessLevelLabel = (level: string): string => {
    const key = `settings.teams.share.accessLevel.${level}`;
    const label = t(key);
    return label === key ? level : label;
  };

  const openTeam = async (team: Team) => {
    setSelected(team);
    setError(null);
    // Clear the previous team's data so the detail view doesn't flash stale
    // members/grants while this team's fetch is in flight.
    setMembers([]);
    setGrants([]);
    try {
      const m = await teamsService.listMembers(team.id, token);
      setMembers(m?.members ?? []);
      const g = await teamsService.listGrants(team.id, undefined, token);
      setGrants(g?.grants ?? []);
      // Agents/sources/prompts are normally hydrated at app init, but a fresh
      // load landing directly on /teams may not have agents yet. Backfill them
      // (only when missing and an agent is actually shared) so the row resolves
      // to a name. Own try/catch — a failure just leaves the truncated-id row.
      if (
        !agents &&
        g?.grants?.some((x: Grant) => x.resource_type === 'agent')
      ) {
        try {
          const res = await userService.getAgents(token);
          const data = await res.json();
          // Guard: only push an actual array into Redux — a non-2xx body
          // (e.g. { success:false }) would otherwise poison selectAgents and
          // crash resolveResourceName / other consumers app-wide.
          if (Array.isArray(data)) dispatch(setAgents(data));
        } catch {
          // Non-fatal: agent rows fall back to a truncated resource id.
        }
      }
      // Resolve tool names only when this team actually shares a tool. Kept in
      // its own try/catch so a tools fetch failure never blocks the already-
      // rendered members/grants — the row just falls back to the truncated id.
      if (g?.grants?.some((x: Grant) => x.resource_type === 'tool')) {
        try {
          const res = await userService.getUserTools(token);
          const data = await res.json();
          const map: Record<string, string> = {};
          (data?.data ?? data?.tools ?? []).forEach(
            (tl: {
              id: string;
              customName?: string;
              displayName?: string;
              name?: string;
            }) => {
              map[tl.id] = tl.customName || tl.displayName || tl.name || tl.id;
            },
          );
          setToolsById(map);
        } catch {
          // Non-fatal: tool rows fall back to a truncated resource id.
        }
      }
    } catch {
      // Surface the failure instead of silently rendering an empty team.
      setError(t('settings.teams.openTeamError'));
    }
  };

  const handleCreate = async () => {
    if (!newTeamName.trim()) return;
    setCreateError(null);
    try {
      const created = await dispatch(
        createTeam({ name: newTeamName.trim(), token }),
      ).unwrap();
      setNewTeamName('');
      setCreateOpen(false);
      openTeam(created);
    } catch {
      // Keep the modal open and surface the error so the user can retry.
      setCreateError(t('settings.teams.createTeamError'));
    }
  };

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

  const openEditModal = () => {
    if (!selected) return;
    setEditName(selected.name);
    setEditDescription(selected.description ?? '');
    setEditError(null);
    setEditOpen(true);
  };

  const closeEditModal = () => {
    setEditOpen(false);
    setEditError(null);
  };

  const handleEditSave = async () => {
    if (!selected || !editName.trim()) return;
    const name = editName.trim();
    const description = editDescription.trim();
    try {
      const res = await teamsService.update(
        selected.id,
        { name, description },
        token,
      );
      if (!res || res.success === false) {
        setEditError(t('settings.teams.updateFailed'));
        return;
      }
      // Reflect locally and refresh the list so the card/switcher update too.
      setSelected({ ...selected, name, description });
      dispatch(loadTeams({ token }));
      setEditOpen(false);
    } catch {
      setEditError(t('settings.teams.updateFailed'));
    }
  };

  // Consume navigation intent from the team switcher: "Manage team" passes
  // openTeamId (open that team's detail directly); "Create team" passes
  // create:true (pop the create modal). Consumed once, then the history state
  // is cleared so a refresh/back doesn't re-trigger it.
  const pendingOpenId = useRef<string | null>(null);
  // Re-run on every navigation (location.key) so it also fires when the user is
  // already on /teams and re-triggers from the switcher. Open the team
  // immediately if teams are loaded; otherwise defer to the effect below.
  useEffect(() => {
    const st = location.state as {
      create?: boolean;
      openTeamId?: string;
    } | null;
    if (!st || (!st.create && !st.openTeamId)) return;
    if (st.create) openCreateModal();
    if (st.openTeamId) {
      pendingOpenId.current = st.openTeamId;
      const team = teams?.find((tm) => tm.id === st.openTeamId);
      if (team) {
        pendingOpenId.current = null;
        openTeam(team);
      }
    }
    // Clear the history state so a refresh/back doesn't re-trigger it.
    navigate(location.pathname, { replace: true, state: null });
  }, [location.key]);

  // Open the requested team once teams finish loading (deferred case).
  useEffect(() => {
    if (!pendingOpenId.current) return;
    const team = teams?.find((tm) => tm.id === pendingOpenId.current);
    if (team) {
      pendingOpenId.current = null;
      openTeam(team);
    }
  }, [teams]);

  const openAddMemberModal = () => {
    setNewMemberEmail('');
    setNewMemberRole('team_member');
    setAddMemberError(null);
    setAddMemberOpen(true);
  };

  const closeAddMemberModal = () => {
    setAddMemberOpen(false);
    setAddMemberError(null);
  };

  const handleAddMember = async () => {
    if (!selected || !newMemberEmail.trim()) return;
    setAddMemberError(null);
    try {
      const res = await teamsService.addMember(
        selected.id,
        { email: newMemberEmail.trim(), role: newMemberRole },
        token,
      );
      if (res?.success === false) {
        // The backend returns 404 with a message when the email maps to no
        // known user; surface its message (e.g. "they must sign in first").
        setAddMemberError(res.message ?? t('settings.teams.memberNotFound'));
        return;
      }
      setNewMemberEmail('');
      setNewMemberRole('team_member');
      setAddMemberOpen(false);
      openTeam(selected);
    } catch {
      setAddMemberError(t('settings.teams.addMemberError'));
    }
  };

  const handleRoleChange = async (memberId: string, role: TeamRole) => {
    if (!selected) return;
    setError(null);
    try {
      const res = await teamsService.setMemberRole(
        selected.id,
        memberId,
        role,
        token,
      );
      if (res?.success === false)
        setError(res.message ?? t('settings.teams.updateFailed'));
      openTeam(selected);
    } catch {
      setError(t('settings.teams.roleChangeError'));
    }
  };

  const requestRemoveMember = (memberId: string) => {
    setMemberToRemove(memberId);
    setRemoveMemberModalState('ACTIVE');
  };

  const confirmRemoveMember = async () => {
    if (!selected || !memberToRemove) return;
    const memberId = memberToRemove;
    setMemberToRemove(null);
    try {
      await teamsService.removeMember(selected.id, memberId, token);
      openTeam(selected);
    } catch {
      setError(t('settings.teams.removeMemberError'));
    }
  };

  const requestDeleteTeam = (team: Team) => {
    setTeamToDelete(team);
    setDeleteTeamModalState('ACTIVE');
  };

  const confirmDeleteTeam = async () => {
    if (!teamToDelete) return;
    const team = teamToDelete;
    setTeamToDelete(null);
    try {
      await dispatch(deleteTeam({ id: team.id, token })).unwrap();
      if (selected?.id === team.id) setSelected(null);
    } catch {
      setError(t('settings.teams.deleteTeamError'));
    }
  };

  const handleUnshare = async (grant: Grant) => {
    if (!selected) return;
    setError(null);
    try {
      await teamsService.unshare(
        selected.id,
        {
          resource_type: grant.resource_type as ResourceType,
          resource_id: grant.resource_id,
        },
        token,
      );
      openTeam(selected);
    } catch {
      setError(t('settings.teams.unshareError'));
    }
  };

  const isAdmin = selected?.member_role === 'team_admin';

  const roleBadge = (role: TeamRole) => (
    <span
      className={`rounded-full px-2 py-0.5 text-xs ${
        role === 'team_admin'
          ? 'bg-muted-foreground/15 text-foreground'
          : 'bg-muted-foreground/10 text-muted-foreground'
      }`}
    >
      {role === 'team_admin'
        ? t('settings.teams.roleAdmin')
        : t('settings.teams.roleMember')}
    </span>
  );

  const emptyState = (message: string, extra?: ReactNode) => (
    <div className="flex flex-col items-center justify-center py-12">
      <img
        src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
        alt=""
        aria-hidden="true"
        className="mx-auto mb-6 h-32 w-32"
      />
      <p className="text-muted-foreground max-w-sm text-center text-sm">
        {message}
      </p>
      {extra}
    </div>
  );

  return (
    <div className="h-full overflow-auto p-4 md:p-12">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="text-foreground text-2xl font-bold">
            {t('settings.teams.label')}
          </p>
          <p className="text-muted-foreground text-sm">
            {t('settings.teams.subtitle')}
          </p>
        </div>
        <Button className="shrink-0" onClick={openCreateModal}>
          <Plus size={16} strokeWidth={1.75} aria-hidden />
          {t('settings.teams.newTeam')}
        </Button>
      </div>

      {!selected ? (
        <div className="mx-auto mt-8 w-full max-w-5xl">
          {teamsLoading ? (
            <SkeletonLoader component="default" />
          ) : teamsError ? (
            <p className="text-destructive text-sm" role="alert">
              {t('settings.teams.loadError')}
            </p>
          ) : teams.length === 0 ? (
            emptyState(
              t('settings.teams.noTeams'),
              <Button
                variant="ghost"
                className="mt-4"
                onClick={openCreateModal}
              >
                <Plus size={16} strokeWidth={1.75} aria-hidden />
                {t('settings.teams.newTeam')}
              </Button>,
            )
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {teams.map((team) => (
                <button
                  key={team.id}
                  className="border-border bg-muted dark:bg-accent hover:border-primary/40 group flex h-full flex-col gap-3 rounded-2xl border p-4 text-left transition-colors"
                  onClick={() => openTeam(team)}
                >
                  <div className="flex items-center gap-3">
                    <span aria-hidden="true" className="contents">
                      <Avatar
                        alt=""
                        className="bg-muted-foreground/15 text-foreground flex size-9 shrink-0 items-center justify-center rounded-md text-sm font-medium"
                      >
                        {initialOf(team.name)}
                      </Avatar>
                    </span>
                    <span className="text-foreground min-w-0 flex-1 truncate text-sm font-semibold">
                      {team.name}
                    </span>
                    {roleBadge(team.member_role ?? 'team_member')}
                    <ChevronRight
                      className="text-muted-foreground shrink-0 transition-transform group-hover:translate-x-0.5"
                      size={18}
                      strokeWidth={1.75}
                      aria-hidden
                    />
                  </div>
                  {team.description ? (
                    <p className="text-muted-foreground line-clamp-2 text-xs leading-relaxed">
                      {team.description}
                    </p>
                  ) : (
                    <p className="text-muted-foreground/50 text-xs italic">
                      {t('settings.teams.noDescription')}
                    </p>
                  )}
                  <div className="text-muted-foreground mt-auto flex items-center gap-1.5 text-xs">
                    <Users size={13} strokeWidth={1.75} aria-hidden />
                    <span>
                      {t(
                        (team.member_count ?? 0) === 1
                          ? 'settings.teams.memberCountOne'
                          : 'settings.teams.memberCountOther',
                        { count: team.member_count ?? 0 },
                      )}
                    </span>
                    <span aria-hidden>·</span>
                    <span>
                      {t('settings.teams.sharedCount', {
                        count: team.shared_count ?? 0,
                      })}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="mx-auto mt-8 max-w-5xl space-y-6">
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground -ml-2"
            onClick={() => {
              setSelected(null);
              setMembers([]);
              setGrants([]);
              setError(null);
            }}
          >
            <ArrowLeft size={16} strokeWidth={1.75} aria-hidden />
            {t('settings.teams.backToTeams')}
          </Button>

          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <span aria-hidden="true" className="contents">
                <Avatar
                  alt=""
                  className="bg-muted-foreground/15 text-foreground flex size-10 shrink-0 items-center justify-center rounded-md text-base font-medium"
                >
                  {initialOf(selected.name)}
                </Avatar>
              </span>
              <div className="min-w-0">
                <h3 className="text-foreground truncate text-xl font-bold">
                  {selected.name}
                </h3>
                {selected.description && (
                  <p className="text-muted-foreground mt-1 line-clamp-2 text-sm">
                    {selected.description}
                  </p>
                )}
              </div>
            </div>
            {isAdmin && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="text-muted-foreground shrink-0"
                    aria-label={t('settings.teams.teamActions')}
                  >
                    <MoreVertical size={18} strokeWidth={1.75} aria-hidden />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-[160px]">
                  <DropdownMenuItem onSelect={openEditModal}>
                    <Pencil size={15} strokeWidth={1.75} aria-hidden />
                    <span>{t('settings.teams.editTeam')}</span>
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={() => requestDeleteTeam(selected)}
                  >
                    <Trash2 size={15} strokeWidth={1.75} aria-hidden />
                    <span>{t('settings.teams.deleteTeam')}</span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>

          {error && (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          )}

          <div className="border-border mt-6 border-t pt-6">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h4 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
                {t('settings.teams.members')} · {members.length}
              </h4>
              {isAdmin && (
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  onClick={openAddMemberModal}
                >
                  <Plus size={15} strokeWidth={1.75} aria-hidden />
                  {t('settings.teams.addMember')}
                </Button>
              )}
            </div>
            {members.length === 0 ? (
              emptyState(t('settings.teams.noMembers'))
            ) : (
              <ul>
                {members.map((m) => (
                  <li
                    key={`${m.user_id}-${m.source}`}
                    className="border-border/60 flex items-center gap-3 border-b px-1 py-2.5 last:border-b-0"
                  >
                    <span aria-hidden="true" className="contents">
                      <Avatar
                        alt=""
                        className="bg-muted-foreground/15 text-foreground flex size-8 items-center justify-center rounded-full text-sm font-medium"
                      >
                        {initialOf(memberLabel(m))}
                      </Avatar>
                    </span>
                    <div className="min-w-0 flex-1">
                      <p
                        className="text-foreground truncate text-sm font-medium"
                        title={memberLabel(m)}
                      >
                        {memberLabel(m)}
                      </p>
                      <p className="text-muted-foreground truncate text-xs">
                        {sourceLabel(m.source)}
                      </p>
                    </div>
                    {isAdmin ? (
                      <Select
                        value={m.role}
                        onValueChange={(value) =>
                          handleRoleChange(m.user_id, value as TeamRole)
                        }
                      >
                        <SelectTrigger
                          size="sm"
                          className="shrink-0"
                          aria-label={t('settings.teams.memberRoleLabel')}
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="team_member">
                            {t('settings.teams.roleMember')}
                          </SelectItem>
                          <SelectItem value="team_admin">
                            {t('settings.teams.roleAdmin')}
                          </SelectItem>
                        </SelectContent>
                      </Select>
                    ) : (
                      <span className="shrink-0">{roleBadge(m.role)}</span>
                    )}
                    {isAdmin && (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className="text-muted-foreground hover:text-destructive shrink-0"
                        aria-label={t('settings.teams.remove')}
                        title={t('settings.teams.remove')}
                        onClick={() => requestRemoveMember(m.user_id)}
                      >
                        <Trash2 size={16} strokeWidth={1.75} aria-hidden />
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="border-border mt-6 border-t pt-6">
            <h4 className="text-muted-foreground mb-3 text-xs font-semibold tracking-wide uppercase">
              {t('settings.teams.sharedResources')} · {grants.length}
            </h4>
            {grants.length === 0 ? (
              emptyState(t('settings.teams.nothingShared'))
            ) : (
              <ul>
                {grants.map((g) => (
                  <li
                    key={`${g.resource_type}-${g.resource_id}`}
                    className="border-border/60 flex items-center gap-3 border-b px-1 py-2.5 last:border-b-0"
                  >
                    <span
                      aria-hidden="true"
                      className="bg-muted-foreground/10 text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md"
                      title={resourceTypeLabel(g.resource_type)}
                    >
                      {resourceTypeIcon(g.resource_type)}
                    </span>
                    <span
                      className="text-foreground min-w-0 flex-1 truncate text-sm font-medium"
                      title={g.resource_id}
                    >
                      {resolveResourceName(g)}
                    </span>
                    <span className="bg-muted-foreground/10 text-muted-foreground shrink-0 rounded-full px-2 py-0.5 text-xs">
                      {accessLevelLabel(g.access_level)}
                    </span>
                    {isAdmin && (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className="text-muted-foreground hover:text-destructive shrink-0"
                        aria-label={t('settings.teams.unshare')}
                        title={t('settings.teams.unshare')}
                        onClick={() => handleUnshare(g)}
                      >
                        <Trash2 size={16} strokeWidth={1.75} aria-hidden />
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      <Modal
        open={createOpen}
        onOpenChange={(open) =>
          open ? setCreateOpen(true) : closeCreateModal()
        }
        size="sm"
        mobileVariant="sheet"
        title={t('settings.teams.createTeam')}
        description={t('settings.teams.createTeamDescription')}
        footer={
          <>
            <Button variant="ghost" onClick={closeCreateModal}>
              {t('cancel')}
            </Button>
            <Button onClick={handleCreate} disabled={!newTeamName.trim()}>
              {t('settings.teams.create')}
            </Button>
          </>
        }
      >
        <Input
          type="text"
          autoFocus
          label={t('settings.teams.teamNamePlaceholder')}
          aria-label={t('settings.teams.teamNamePlaceholder')}
          value={newTeamName}
          onChange={(e) => setNewTeamName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
        />
        {createError && (
          <p className="text-destructive mt-3 text-sm" role="alert">
            {createError}
          </p>
        )}
      </Modal>

      <Modal
        open={editOpen}
        onOpenChange={(open) => (open ? setEditOpen(true) : closeEditModal())}
        size="sm"
        mobileVariant="sheet"
        title={t('settings.teams.editTeam')}
        footer={
          <>
            <Button variant="ghost" onClick={closeEditModal}>
              {t('cancel')}
            </Button>
            <Button onClick={handleEditSave} disabled={!editName.trim()}>
              {t('settings.teams.save')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Input
            type="text"
            autoFocus
            label={t('settings.teams.teamNamePlaceholder')}
            aria-label={t('settings.teams.teamNamePlaceholder')}
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
          />
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="team-edit-description"
              className="text-foreground text-sm font-medium"
            >
              {t('settings.teams.descriptionLabel')}
            </label>
            <textarea
              id="team-edit-description"
              rows={3}
              className="border-border bg-background text-foreground focus-visible:ring-ring/50 focus-visible:border-ring placeholder:text-muted-foreground w-full resize-none rounded-lg border px-3 py-2 text-sm outline-none focus-visible:ring-[3px]"
              placeholder={t('settings.teams.descriptionPlaceholder')}
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
            />
          </div>
        </div>
        {editError && (
          <p className="text-destructive mt-3 text-sm" role="alert">
            {editError}
          </p>
        )}
      </Modal>

      <Modal
        open={addMemberOpen}
        onOpenChange={(open) =>
          open ? setAddMemberOpen(true) : closeAddMemberModal()
        }
        size="sm"
        mobileVariant="sheet"
        title={t('settings.teams.addMemberTitle')}
        description={t('settings.teams.addMemberDescription')}
        footer={
          <>
            <Button variant="ghost" onClick={closeAddMemberModal}>
              {t('cancel')}
            </Button>
            <Button onClick={handleAddMember} disabled={!newMemberEmail.trim()}>
              {t('settings.teams.add')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Input
            type="email"
            autoFocus
            label={t('settings.teams.memberEmailLabel')}
            aria-label={t('settings.teams.memberEmailLabel')}
            placeholder={t('settings.teams.memberEmailPlaceholder')}
            value={newMemberEmail}
            onChange={(e) => setNewMemberEmail(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAddMember()}
          />
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="add-member-role"
              className="text-foreground text-sm font-medium"
            >
              {t('settings.teams.memberRoleLabel')}
            </label>
            <Select
              value={newMemberRole}
              onValueChange={(value) => setNewMemberRole(value as TeamRole)}
            >
              <SelectTrigger
                id="add-member-role"
                aria-label={t('settings.teams.memberRoleLabel')}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="team_member">
                  {t('settings.teams.roleMember')}
                </SelectItem>
                <SelectItem value="team_admin">
                  {t('settings.teams.roleAdmin')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        {addMemberError && (
          <p className="text-destructive mt-3 text-sm" role="alert">
            {addMemberError}
          </p>
        )}
      </Modal>

      <ConfirmationModal
        message={t('settings.teams.deleteTeamConfirmation', {
          name: teamToDelete?.name ?? '',
        })}
        modalState={deleteTeamModalState}
        setModalState={setDeleteTeamModalState}
        submitLabel={t('settings.teams.deleteTeam')}
        handleSubmit={confirmDeleteTeam}
        handleCancel={() => setTeamToDelete(null)}
        variant="danger"
      />
      <ConfirmationModal
        message={t('settings.teams.removeMemberConfirmation')}
        modalState={removeMemberModalState}
        setModalState={setRemoveMemberModalState}
        submitLabel={t('settings.teams.remove')}
        handleSubmit={confirmRemoveMember}
        handleCancel={() => setMemberToRemove(null)}
        variant="danger"
      />
    </div>
  );
}
