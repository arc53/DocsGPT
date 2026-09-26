import {
  Bot,
  ChevronRight,
  CircleAlert,
  FileText,
  MessageSquare,
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
import SkeletonLoader from '../components/SkeletonLoader';
import DetailBreadcrumb from '../navigation/DetailBreadcrumb';
import SectionShell from '../navigation/SectionShell';
import PageToolbar from '../components/PageToolbar';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Avatar } from '../components/ui/avatar';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Card,
  CardDescription,
  CardFooter,
  CardTitle,
} from '../components/ui/card';
import { ActionMenu } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { FormField } from '../components/ui/form-field';
import { IconButton } from '../components/ui/icon-button';
import { Input } from '../components/ui/input';
import { ListRow, ListRows } from '../components/ui/list-row';
import { Modal, ModalActions } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { Textarea } from '../components/ui/textarea';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
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
  const location = useLocation();
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();
  // A failed action on the team detail page is a fire-and-forget result.
  const reportError = (message: string) =>
    dispatch(showActionToast({ variant: 'destructive', message }));
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
    const props = { size: 16, 'aria-hidden': true } as const;
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
      reportError(t('settings.teams.openTeamError'));
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
    try {
      const res = await teamsService.setMemberRole(
        selected.id,
        memberId,
        role,
        token,
      );
      if (res?.success === false)
        reportError(res.message ?? t('settings.teams.updateFailed'));
      openTeam(selected);
    } catch {
      reportError(t('settings.teams.roleChangeError'));
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
      reportError(t('settings.teams.removeMemberError'));
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
      reportError(t('settings.teams.deleteTeamError'));
    }
  };

  const handleUnshare = async (grant: Grant) => {
    if (!selected) return;
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
      reportError(t('settings.teams.unshareError'));
    }
  };

  const isAdmin = selected?.member_role === 'team_admin';

  const roleBadge = (role: TeamRole) => (
    <Badge variant={role === 'team_admin' ? 'default' : 'neutral'}>
      {role === 'team_admin'
        ? t('settings.teams.roleAdmin')
        : t('settings.teams.roleMember')}
    </Badge>
  );

  return (
    <SectionShell>
      <PageToolbar
        intro={t('settings.teams.subtitle')}
        action={
          <Button size="field" shape="pill" onClick={openCreateModal}>
            <Plus aria-hidden />
            {t('settings.teams.newTeam')}
          </Button>
        }
      />

      {!selected ? (
        <div>
          {teamsLoading ? (
            <SkeletonLoader component="default" />
          ) : teamsError ? (
            <EmptyState
              tone="destructive"
              size="sm"
              illustration="none"
              title={t('settings.teams.loadError')}
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => dispatch(loadTeams({ token }))}
                >
                  {t('retry')}
                </Button>
              }
            />
          ) : teams.length === 0 ? (
            <EmptyState
              title={t('settings.teams.noTeams')}
              action={
                <Button variant="ghost" onClick={openCreateModal}>
                  <Plus aria-hidden />
                  {t('settings.teams.newTeam')}
                </Button>
              }
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {teams.map((team) => (
                <Card
                  key={team.id}
                  asChild
                  interactive
                  className="group h-full"
                >
                  <button onClick={() => openTeam(team)}>
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
                      {roleBadge(team.member_role ?? 'team_member')}
                      <ChevronRight
                        className="text-muted-foreground size-4.5 shrink-0 transition-transform group-hover:translate-x-0.5"
                        aria-hidden
                      />
                    </div>
                    {team.description ? (
                      <CardDescription size="xs" className="line-clamp-2">
                        {team.description}
                      </CardDescription>
                    ) : (
                      <p className="text-muted-foreground/50 text-xs italic">
                        {t('settings.teams.noDescription')}
                      </p>
                    )}
                    <CardFooter className="gap-1.5">
                      <Users className="size-3.5" aria-hidden />
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
                    </CardFooter>
                  </button>
                </Card>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          <DetailBreadcrumb
            parentLabel={t('settings.teams.label')}
            currentLabel={selected.name}
            onParentClick={() => {
              setSelected(null);
              setMembers([]);
              setGrants([]);
            }}
          />

          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <span aria-hidden="true" className="contents">
                <Avatar alt="" size="lg" shape="square" variant="muted">
                  {initialOf(selected.name)}
                </Avatar>
              </span>
              <div className="min-w-0">
                <h3 className="text-foreground truncate text-xl leading-tight font-semibold">
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
              <ActionMenu
                options={[
                  {
                    label: t('settings.teams.editTeam'),
                    icon: Pencil,
                    onClick: openEditModal,
                  },
                  {
                    label: t('settings.teams.deleteTeam'),
                    icon: Trash2,
                    variant: 'destructive',
                    onClick: () => requestDeleteTeam(selected),
                  },
                ]}
                triggerLabel={t('settings.teams.teamActions')}
                className="shrink-0"
              />
            )}
          </div>

          <div className="border-border flex flex-col gap-3 border-t pt-6">
            <SectionHeader
              as="h4"
              size="sm"
              title={`${t('settings.teams.members')} · ${members.length}`}
              actions={
                isAdmin && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="shrink-0"
                    onClick={openAddMemberModal}
                  >
                    <Plus aria-hidden />
                    {t('settings.teams.addMember')}
                  </Button>
                )
              }
            />
            {members.length === 0 ? (
              <EmptyState size="sm" title={t('settings.teams.noMembers')} />
            ) : (
              <ListRows>
                {members.map((m) => (
                  <ListRow
                    key={`${m.user_id}-${m.source}`}
                    leading={
                      <span aria-hidden="true" className="contents">
                        <Avatar alt="" size="sm" shape="circle" variant="muted">
                          {initialOf(memberLabel(m))}
                        </Avatar>
                      </span>
                    }
                    title={<span title={memberLabel(m)}>{memberLabel(m)}</span>}
                    description={sourceLabel(m.source)}
                    trailing={
                      <>
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
                          <IconButton
                            variant="ghost-destructive"
                            size="icon-sm"
                            className="shrink-0"
                            label={t('settings.teams.remove')}
                            icon={Trash2}
                            onClick={() => requestRemoveMember(m.user_id)}
                          />
                        )}
                      </>
                    }
                  />
                ))}
              </ListRows>
            )}
          </div>

          <div className="border-border flex flex-col gap-3 border-t pt-6">
            <SectionHeader
              as="h4"
              size="sm"
              title={`${t('settings.teams.sharedResources')} · ${grants.length}`}
            />
            {grants.length === 0 ? (
              <EmptyState size="sm" title={t('settings.teams.nothingShared')} />
            ) : (
              <ListRows>
                {grants.map((g) => (
                  <ListRow
                    key={`${g.resource_type}-${g.resource_id}`}
                    leading={
                      <span
                        aria-hidden="true"
                        className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md"
                        title={resourceTypeLabel(g.resource_type)}
                      >
                        {resourceTypeIcon(g.resource_type)}
                      </span>
                    }
                    title={
                      <span title={g.resource_id}>
                        {resolveResourceName(g)}
                      </span>
                    }
                    trailing={
                      <>
                        <Badge variant="neutral">
                          {accessLevelLabel(g.access_level)}
                        </Badge>
                        {isAdmin && (
                          <IconButton
                            variant="ghost-destructive"
                            size="icon-sm"
                            className="shrink-0"
                            label={t('settings.teams.unshare')}
                            icon={Trash2}
                            onClick={() => handleUnshare(g)}
                          />
                        )}
                      </>
                    }
                  />
                ))}
              </ListRows>
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
          <ModalActions
            cancelLabel={t('cancel')}
            onCancel={closeCreateModal}
            submitLabel={t('settings.teams.create')}
            onSubmit={handleCreate}
            disabled={!newTeamName.trim()}
          />
        }
      >
        <FormField label={t('settings.teams.teamNamePlaceholder')}>
          <Input
            type="text"
            autoFocus
            value={newTeamName}
            onChange={(e) => setNewTeamName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
          />
        </FormField>
        {createError && (
          <Alert variant="destructive" className="mt-3">
            <CircleAlert className="size-4" aria-hidden="true" />
            <AlertDescription>{createError}</AlertDescription>
          </Alert>
        )}
      </Modal>

      <Modal
        open={editOpen}
        onOpenChange={(open) => (open ? setEditOpen(true) : closeEditModal())}
        size="sm"
        mobileVariant="sheet"
        title={t('settings.teams.editTeam')}
        footer={
          <ModalActions
            cancelLabel={t('cancel')}
            onCancel={closeEditModal}
            submitLabel={t('settings.teams.save')}
            onSubmit={handleEditSave}
            disabled={!editName.trim()}
          />
        }
      >
        <div className="flex flex-col gap-5">
          <FormField label={t('settings.teams.teamNamePlaceholder')}>
            <Input
              type="text"
              autoFocus
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
            />
          </FormField>
          <FormField label={t('settings.teams.descriptionLabel')}>
            <Textarea
              rows={3}
              resize="none"
              placeholder={t('settings.teams.descriptionPlaceholder')}
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
            />
          </FormField>
        </div>
        {editError && (
          <Alert variant="destructive" className="mt-3">
            <CircleAlert className="size-4" aria-hidden="true" />
            <AlertDescription>{editError}</AlertDescription>
          </Alert>
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
          <ModalActions
            cancelLabel={t('cancel')}
            onCancel={closeAddMemberModal}
            submitLabel={t('settings.teams.add')}
            onSubmit={handleAddMember}
            disabled={!newMemberEmail.trim()}
          />
        }
      >
        <div className="flex flex-col gap-5">
          <FormField label={t('settings.teams.memberEmailLabel')}>
            <Input
              type="email"
              autoFocus
              placeholder={t('settings.teams.memberEmailPlaceholder')}
              value={newMemberEmail}
              onChange={(e) => setNewMemberEmail(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAddMember()}
            />
          </FormField>
          <FormField label={t('settings.teams.memberRoleLabel')}>
            <Select
              value={newMemberRole}
              onValueChange={(value) => setNewMemberRole(value as TeamRole)}
            >
              <SelectTrigger size="field" className="w-full">
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
          </FormField>
        </div>
        {addMemberError && (
          <Alert variant="destructive" className="mt-3">
            <CircleAlert className="size-4" aria-hidden="true" />
            <AlertDescription>{addMemberError}</AlertDescription>
          </Alert>
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
        variant="destructive"
      />
      <ConfirmationModal
        message={t('settings.teams.removeMemberConfirmation')}
        modalState={removeMemberModalState}
        setModalState={setRemoveMemberModalState}
        submitLabel={t('settings.teams.remove')}
        handleSubmit={confirmRemoveMember}
        handleCancel={() => setMemberToRemove(null)}
        variant="destructive"
      />
    </SectionShell>
  );
}
