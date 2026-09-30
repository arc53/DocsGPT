import {
  ArrowUpRight,
  Bot,
  Check,
  ChevronRight,
  CircleAlert,
  FileText,
  MessageSquare,
  Pencil,
  Plus,
  Trash2,
  Users,
  Wrench,
  X,
} from 'lucide-react';
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import teamsService, {
  AccessLevel,
  ResourceSettingsResponse,
  ResourceType,
  TeamGrant,
  TeamRole,
} from '../api/services/teamsService';
import userService from '../api/services/userService';
import {
  agentChatPath,
  agentEditPath,
  agentEditPathFor,
} from '../agents/paths';
import { Pagination, pageRangeParams } from '../components/ui/pagination';
import { useDebouncedValue } from '../hooks';
import { SHORT_LIST_PAGE_SIZE, useClientPage } from '../hooks/usePageState';
import SearchInput from '../components/SearchInput';
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
import {
  DescriptionItem,
  DescriptionList,
} from '../components/ui/description-list';
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
import { PanelBody, PanelHeader, SidePanel } from '../components/ui/side-panel';
import { Textarea } from '../components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { cn } from '../lib/utils';
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
  capabilityLines,
  errorMessage,
  resolveSettings,
} from '../teams/accessSettings';
import ShareToTeamModal from '../teams/ShareToTeamModal';
import {
  createTeam,
  deleteTeam,
  loadTeams,
  selectTeams,
  selectTeamsError,
  selectTeamsLoading,
  Team,
} from '../teams/teamsSlice';
import { can } from '../utils/accessUtils';
import { formatCount, formatDateOnly } from '../utils/dateTimeUtils';
import { decodeJwtPayload } from '../utils/jwtUtils';

type Member = {
  user_id: string;
  email?: string | null;
  role: TeamRole;
  source: string;
};

type Grant = TeamGrant;

// All of one team's grants on one resource: the whole-team grant (if any)
// and the per-member grants, shown as a single row.
type SharedResource = {
  key: string;
  type: ResourceType;
  id: string;
  grants: Grant[];
  teamGrant: Grant | null;
  memberGrants: Grant[];
};

type ResourceFilter = 'all' | ResourceType;

const resourceKey = (g: Pick<Grant, 'resource_type' | 'resource_id'>) =>
  `${g.resource_type}:${g.resource_id}`;

const grantKey = (g: Grant) => `${resourceKey(g)}:${g.target_user_id ?? ''}`;

/** Group grants by resource, keeping the server's order of first sighting. */
export function groupGrants(grants: Grant[]): SharedResource[] {
  const byKey = new Map<string, SharedResource>();
  grants.forEach((g) => {
    const key = resourceKey(g);
    let entry = byKey.get(key);
    if (!entry) {
      entry = {
        key,
        type: g.resource_type,
        id: g.resource_id,
        grants: [],
        teamGrant: null,
        memberGrants: [],
      };
      byKey.set(key, entry);
    }
    entry.grants.push(g);
    if (g.target_user_id) entry.memberGrants.push(g);
    else entry.teamGrant = g;
  });
  return Array.from(byKey.values());
}

const RESOURCE_TYPES: ReadonlyArray<ResourceType> = [
  'agent',
  'source',
  'prompt',
  'tool',
];

// Filter pill order on the shared resources list.
/** Members per page; search and the pager appear past one page. */
const MEMBERS_PAGE_SIZE = 25;

const FILTER_TYPES: ReadonlyArray<ResourceType> = [
  'agent',
  'source',
  'tool',
  'prompt',
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
  // Members page from the server: search and 25 per page, shown only once
  // a team has more than a page of members.
  const [membersPage, setMembersPage] = useState(1);
  const [memberQuery, setMemberQuery] = useState('');
  const debouncedMemberQuery = useDebouncedValue(memberQuery.trim(), 300);
  const [membersTotal, setMembersTotal] = useState(0);
  const [membersAll, setMembersAll] = useState(0);
  const [membersReload, setMembersReload] = useState(0);
  const [membersError, setMembersError] = useState(false);
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
  // The create, edit and add-member modals' request is in flight (one opens
  // at a time): the submit shows pending and a second submit is ignored.
  const [modalPending, setModalPending] = useState(false);

  const [deleteTeamModalState, setDeleteTeamModalState] =
    useState<ActiveState>('INACTIVE');
  const [teamToDelete, setTeamToDelete] = useState<Team | null>(null);
  const [removeMemberModalState, setRemoveMemberModalState] =
    useState<ActiveState>('INACTIVE');
  const [memberToRemove, setMemberToRemove] = useState<string | null>(null);

  // The caller's role in the selected team, as the grants endpoint reports it.
  const [teamRole, setTeamRole] = useState<TeamRole | null>(null);
  // Shared resources list: type filter, search, and the row whose drawer is
  // open (kept while "Manage sharing" has the drawer closed).
  const [resourceFilter, setResourceFilter] = useState<ResourceFilter>('all');
  const [resourceQuery, setResourceQuery] = useState('');
  const [openResourceKey, setOpenResourceKey] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerSettings, setDrawerSettings] =
    useState<ResourceSettingsResponse | null>(null);
  const [busyGrants, setBusyGrants] = useState<Set<string>>(new Set());
  const [shareTarget, setShareTarget] = useState<SharedResource | null>(null);

  // The caller's own sub, to tell whether they own the selected team when
  // the server doesn't send `is_owner`.
  const currentUserId = useMemo(() => {
    const payload = token ? decodeJwtPayload(token) : null;
    return typeof payload?.sub === 'string' ? payload.sub : undefined;
  }, [token]);

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
    if (g.resource_name) return g.resource_name;
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
  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    teamsService
      .listMembers(selected.id, token, {
        q: debouncedMemberQuery,
        page: membersPage,
        pageSize: MEMBERS_PAGE_SIZE,
      })
      .then((m) => {
        if (cancelled) return;
        const rows: Member[] = m?.members ?? [];
        const total: number = m?.total ?? rows.length;
        // Removing the last member on the last page: step back a page.
        if (rows.length === 0 && total > 0 && membersPage > 1) {
          setMembersPage(Math.ceil(total / MEMBERS_PAGE_SIZE));
          return;
        }
        setMembersError(false);
        setMembers(rows);
        setMembersTotal(total);
        if (!debouncedMemberQuery) setMembersAll(total);
      })
      .catch(() => {
        // A failed load is an error with Retry, not "no members".
        if (!cancelled) setMembersError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.id, token, debouncedMemberQuery, membersPage, membersReload]);

  const accessLevelLabel = (level: string): string => {
    const key = `settings.teams.share.accessLevel.${level}`;
    const label = t(key);
    return label === key ? level : label;
  };

  const openTeam = async (team: Team) => {
    // Re-opening the same team (after a role change or a removal) keeps the
    // members page and search; another team starts on page 1.
    const sameTeam = selected?.id === team.id;
    setSelected(team);
    setMembersReload((n) => n + 1);
    if (!sameTeam) {
      // Clear the previous team's data so the detail view doesn't flash
      // stale members/grants while this team's fetch is in flight.
      setMembers([]);
      setMembersError(false);
      setMembersPage(1);
      setMemberQuery('');
      setMembersTotal(0);
      setMembersAll(0);
    }
    setGrants([]);
    setTeamRole(null);
    setOpenResourceKey(null);
    setDrawerOpen(false);
    setResourceFilter('all');
    setResourceQuery('');
    try {
      const g = await teamsService.listGrants(team.id, undefined, token);
      setGrants(g?.grants ?? []);
      setTeamRole(g?.team_role ?? null);
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
    if (!newTeamName.trim() || modalPending) return;
    setCreateError(null);
    setModalPending(true);
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
    } finally {
      setModalPending(false);
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
    if (!selected || !editName.trim() || modalPending) return;
    const name = editName.trim();
    const description = editDescription.trim();
    setModalPending(true);
    try {
      const res = await teamsService.update(
        selected.id,
        { name, description },
        token,
      );
      if (!res || res.success === false) {
        setEditError(res?.message ?? t('settings.teams.updateFailed'));
        return;
      }
      // Reflect locally and refresh the list so the card/switcher update too.
      setSelected({ ...selected, name, description });
      dispatch(loadTeams({ token }));
      setEditOpen(false);
    } catch (error) {
      setEditError(errorMessage(error, t('settings.teams.updateFailed')));
    } finally {
      setModalPending(false);
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
    if (!selected || !newMemberEmail.trim() || modalPending) return;
    setAddMemberError(null);
    setModalPending(true);
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
    } catch (error) {
      // The backend returns 404 with a message when the email maps to no
      // known user ("they must sign in first"); show its message.
      setAddMemberError(
        errorMessage(error, t('settings.teams.addMemberError')),
      );
    } finally {
      setModalPending(false);
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
    } catch (error) {
      reportError(errorMessage(error, t('settings.teams.roleChangeError')));
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
    } catch (error) {
      reportError(errorMessage(error, t('settings.teams.removeMemberError')));
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
    } catch (error) {
      reportError(errorMessage(error, t('settings.teams.deleteTeamError')));
    }
  };

  // Re-read the team's grants after a change (the drawer follows them).
  const refreshGrants = async () => {
    if (!selected) return;
    try {
      const g = await teamsService.listGrants(selected.id, undefined, token);
      setGrants(g?.grants ?? []);
      setTeamRole(g?.team_role ?? null);
    } catch (error) {
      reportError(errorMessage(error, t('settings.teams.openTeamError')));
    }
  };

  const setGrantBusy = (key: string, busy: boolean) =>
    setBusyGrants((prev) => {
      const next = new Set(prev);
      if (busy) next.add(key);
      else next.delete(key);
      return next;
    });

  // Remove one grant: the whole-team grant, or one member's (which needs
  // its target_user_id, or the server would drop the team grant instead).
  const handleUnshare = async (grant: Grant) => {
    if (!selected) return;
    const key = grantKey(grant);
    setGrantBusy(key, true);
    try {
      await teamsService.unshare(
        selected.id,
        {
          resource_type: grant.resource_type,
          resource_id: grant.resource_id,
          target_user_id: grant.target_user_id ?? undefined,
        },
        token,
      );
    } catch (error) {
      reportError(errorMessage(error, t('settings.teams.unshareError')));
    } finally {
      setGrantBusy(key, false);
      await refreshGrants();
    }
  };

  const handleGrantAccess = async (grant: Grant, level: AccessLevel) => {
    if (!selected || grant.access_level === level) return;
    const key = grantKey(grant);
    setGrantBusy(key, true);
    try {
      await teamsService.share(
        selected.id,
        {
          resource_type: grant.resource_type,
          resource_id: grant.resource_id,
          access_level: level,
          target_user_id: grant.target_user_id ?? undefined,
        },
        token,
      );
    } catch (error) {
      reportError(errorMessage(error, t('settings.teams.accessChangeError')));
    } finally {
      setGrantBusy(key, false);
      await refreshGrants();
    }
  };

  // The grants endpoint's live team_role wins over the list's member_role.
  const isAdmin = (teamRole ?? selected?.member_role) === 'team_admin';
  // Only the team's owner may delete it. Prefer the server's `is_owner`;
  // older payloads only carry `owner_id`.
  const isTeamOwner = selected
    ? typeof selected.is_owner === 'boolean'
      ? selected.is_owner
      : Boolean(currentUserId) && selected.owner_id === currentUserId
    : false;

  const sharedResources = useMemo(() => groupGrants(grants), [grants]);
  const resourceCounts = useMemo(() => {
    const counts: Record<ResourceFilter, number> = {
      all: sharedResources.length,
      agent: 0,
      source: 0,
      tool: 0,
      prompt: 0,
    };
    sharedResources.forEach((r) => {
      if (r.type in counts) counts[r.type] += 1;
    });
    return counts;
  }, [sharedResources]);

  const resourceName = (r: SharedResource): string =>
    resolveResourceName(r.grants[0]);
  const ownerLabel = (r: SharedResource): string => {
    const g = r.grants[0];
    return g.owner_label || (g.owner_id ? truncateSub(g.owner_id) : '—');
  };

  const visibleResources = sharedResources.filter((r) => {
    if (resourceFilter !== 'all' && r.type !== resourceFilter) return false;
    const needle = resourceQuery.trim().toLowerCase();
    if (!needle) return true;
    return `${resourceName(r)} ${ownerLabel(r)}`.toLowerCase().includes(needle);
  });
  const {
    page: resourcesPage,
    setPage: setResourcesPage,
    pageItems: pageResources,
  } = useClientPage(
    visibleResources,
    SHORT_LIST_PAGE_SIZE,
    `${resourceFilter}|${resourceQuery}`,
  );
  const {
    page: teamsPage,
    setPage: setTeamsPage,
    pageItems: pageTeams,
  } = useClientPage(teams, SHORT_LIST_PAGE_SIZE, '');

  // The strongest access this team has, plus "+N Editor" when per-member
  // editor grants sit on top of a viewer team grant.
  const resourceBadge = (r: SharedResource): string => {
    const memberEditors = r.memberGrants.filter(
      (g) => g.access_level === 'editor',
    ).length;
    if (r.teamGrant) {
      const level = accessLevelLabel(r.teamGrant.access_level);
      return r.teamGrant.access_level === 'viewer' && memberEditors > 0
        ? t('settings.teams.sharedList.badgeWithEditors', {
            interpolation: { escapeValue: false },
            level,
            count: memberEditors,
            formatted: formatCount(memberEditors),
          })
        : level;
    }
    return accessLevelLabel(memberEditors > 0 ? 'editor' : 'viewer');
  };

  const openResource =
    sharedResources.find((r) => r.key === openResourceKey) ?? null;
  const openCaller = openResource?.grants.find((g) => g.caller)?.caller ?? null;
  const callerCanShare = can(openCaller, 'share');

  const openDrawerFor = (r: SharedResource) => {
    setOpenResourceKey(r.key);
    setDrawerOpen(true);
    setDrawerSettings(null);
    teamsService
      .getResourceSettings(r.type, r.id, token)
      .then((res) => setDrawerSettings(res))
      .catch(() => {
        // The capabilities list falls back to the default rules.
      });
  };

  const closeDrawer = () => {
    setDrawerOpen(false);
    setOpenResourceKey(null);
  };

  // Where "Open {{type}}" goes: an agent's edit page when the caller may
  // view its config, else its chat; the list page for the other types.
  const openAssetPath = (r: SharedResource): string => {
    switch (r.type) {
      case 'agent': {
        if (!can(openCaller, 'view')) return agentChatPath(r.id);
        const agent = agents?.find((a) => a.id === r.id);
        return agent ? agentEditPathFor(agent) : agentEditPath(r.id);
      }
      case 'source':
        return '/settings/knowledge';
      case 'tool':
        return '/settings/tools';
      case 'prompt':
        return '/settings/general';
      default:
        return '/settings';
    }
  };

  const callerAccessLabel = (access?: string | null): string =>
    access
      ? t(`settings.teams.drawer.yourAccessLevel.${access}`, {
          interpolation: { escapeValue: false },
          defaultValue: access,
        })
      : t('settings.teams.drawer.yourAccessLevel.none');

  const grantedAt = (r: SharedResource): string => {
    const first = [...r.grants]
      .filter((g) => g.created_at)
      .sort((a, b) => (a.created_at! < b.created_at! ? -1 : 1))[0];
    if (!first?.created_at) return '—';
    const date = formatDateOnly(first.created_at);
    return first.granted_by_label
      ? t('settings.teams.drawer.sharedOnBy', {
          interpolation: { escapeValue: false },
          date,
          name: first.granted_by_label,
        })
      : date;
  };

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
                <h3
                  className="text-foreground truncate text-xl leading-tight font-semibold"
                  title={selected.name}
                >
                  {selected.name}
                </h3>
                {selected.description && (
                  <p
                    className="text-muted-foreground mt-1 line-clamp-2 text-sm"
                    title={selected.description}
                  >
                    {selected.description}
                  </p>
                )}
              </div>
            </div>
            {(isAdmin || isTeamOwner) && (
              <ActionMenu
                options={[
                  ...(isAdmin
                    ? [
                        {
                          label: t('settings.teams.editTeam'),
                          icon: Pencil,
                          onClick: openEditModal,
                        },
                      ]
                    : []),
                  ...(isTeamOwner
                    ? [
                        {
                          label: t('settings.teams.deleteTeam'),
                          icon: Trash2,
                          variant: 'destructive' as const,
                          onClick: () => requestDeleteTeam(selected),
                        },
                      ]
                    : []),
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
              title={`${t('settings.teams.members')} · ${formatCount(membersAll)}`}
              actions={
                (membersAll > MEMBERS_PAGE_SIZE || isAdmin) && (
                  <div className="flex flex-wrap items-center gap-2">
                    {membersAll > MEMBERS_PAGE_SIZE && (
                      <SearchInput
                        className="w-full sm:w-56"
                        placeholder={t('settings.teams.searchMembers')}
                        value={memberQuery}
                        onChange={(e) => {
                          setMemberQuery(e.target.value);
                          setMembersPage(1);
                        }}
                      />
                    )}
                    {isAdmin && (
                      <Button
                        variant="outline"
                        size="field"
                        className="shrink-0"
                        onClick={openAddMemberModal}
                      >
                        <Plus aria-hidden />
                        {t('settings.teams.addMember')}
                      </Button>
                    )}
                  </div>
                )
              }
            />
            {membersError ? (
              <EmptyState
                tone="destructive"
                size="sm"
                illustration="none"
                title={t('settings.teams.membersLoadError')}
                onRetry={() => setMembersReload((n) => n + 1)}
              />
            ) : members.length === 0 ? (
              <EmptyState
                size="sm"
                title={
                  debouncedMemberQuery
                    ? t('settings.teams.sharedList.noMatches')
                    : t('settings.teams.noMembers')
                }
              />
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
            <Pagination
              page={membersPage}
              pageSize={MEMBERS_PAGE_SIZE}
              total={membersTotal}
              onPageChange={setMembersPage}
              rangeLabel={(range) =>
                t('settings.teams.membersRange', pageRangeParams(range))
              }
            />
          </div>

          <div className="border-border flex flex-col gap-3 border-t pt-6">
            <SectionHeader
              as="h4"
              size="sm"
              title={`${t('settings.teams.sharedResources')} · ${formatCount(sharedResources.length)}`}
            />
            {sharedResources.length === 0 ? (
              <EmptyState size="sm" title={t('settings.teams.nothingShared')} />
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                  <ToggleGroup
                    type="single"
                    value={resourceFilter}
                    onValueChange={(value) =>
                      value && setResourceFilter(value as ResourceFilter)
                    }
                    aria-label={t('settings.teams.sharedList.filterLabel')}
                  >
                    {(['all', ...FILTER_TYPES] as ResourceFilter[]).map(
                      (value) => (
                        <ToggleGroupItem key={value} value={value}>
                          {t(`settings.teams.sharedList.filter.${value}`)}{' '}
                          {formatCount(resourceCounts[value])}
                        </ToggleGroupItem>
                      ),
                    )}
                  </ToggleGroup>
                  <SearchInput
                    className="w-full sm:w-56"
                    placeholder={t('settings.teams.sharedList.search')}
                    value={resourceQuery}
                    onChange={(e) => setResourceQuery(e.target.value)}
                  />
                </div>
                {visibleResources.length === 0 ? (
                  <EmptyState
                    size="xs"
                    illustration="none"
                    title={t('settings.teams.sharedList.noMatches')}
                  />
                ) : (
                  <>
                    <ListRows>
                      {pageResources.map((r) => {
                        const isOpen = drawerOpen && openResourceKey === r.key;
                        return (
                          <ListRow
                            key={r.key}
                            interactive
                            selected={isOpen}
                            asChild
                            leading={
                              <Avatar
                                aria-hidden="true"
                                size="sm"
                                shape="square"
                                variant="icon"
                              >
                                {resourceTypeIcon(r.type)}
                              </Avatar>
                            }
                            title={
                              <span title={resourceName(r)}>
                                {resourceName(r)}
                              </span>
                            }
                            description={t('settings.teams.sharedList.meta', {
                              interpolation: { escapeValue: false },
                              type: resourceTypeLabel(r.type),
                              owner: ownerLabel(r),
                            })}
                            trailing={
                              <>
                                <Badge variant="neutral" className="shrink-0">
                                  {resourceBadge(r)}
                                </Badge>
                                <ChevronRight
                                  className="text-muted-foreground size-4 shrink-0"
                                  aria-hidden
                                />
                              </>
                            }
                          >
                            <button
                              type="button"
                              data-testid="shared-resource-row"
                              onClick={() => openDrawerFor(r)}
                            />
                          </ListRow>
                        );
                      })}
                    </ListRows>
                    <Pagination
                      page={resourcesPage}
                      pageSize={SHORT_LIST_PAGE_SIZE}
                      total={visibleResources.length}
                      onPageChange={setResourcesPage}
                      rangeLabel={(range) =>
                        t(
                          'settings.teams.sharedList.pageRange',
                          pageRangeParams(range),
                        )
                      }
                    />
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}

      <SidePanel
        open={drawerOpen && openResource !== null}
        onOpenChange={(open) => !open && closeDrawer()}
      >
        {openResource && selected && (
          <>
            <PanelHeader
              title={resourceName(openResource)}
              description={t('settings.teams.drawer.subtitle', {
                interpolation: { escapeValue: false },
                type: resourceTypeLabel(openResource.type),
                owner: ownerLabel(openResource),
              })}
              leading={
                <Avatar
                  aria-hidden="true"
                  size="sm"
                  shape="square"
                  variant="icon"
                >
                  {resourceTypeIcon(openResource.type)}
                </Avatar>
              }
            >
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  shape="pill"
                  onClick={() => {
                    const path = openAssetPath(openResource);
                    closeDrawer();
                    navigate(path);
                  }}
                >
                  <ArrowUpRight aria-hidden />
                  {t('settings.teams.drawer.open', {
                    interpolation: { escapeValue: false },
                    type: resourceTypeLabel(openResource.type),
                  })}
                </Button>
                {callerCanShare && (
                  <Button
                    variant="outline"
                    size="sm"
                    shape="pill"
                    onClick={() => {
                      setDrawerOpen(false);
                      setShareTarget(openResource);
                    }}
                  >
                    <Users aria-hidden />
                    {t('settings.teams.drawer.manageSharing')}
                  </Button>
                )}
              </div>
            </PanelHeader>
            <PanelBody>
              <DescriptionList size="sm">
                <DescriptionItem label={t('settings.teams.drawer.owner')}>
                  {ownerLabel(openResource)}
                </DescriptionItem>
                <DescriptionItem label={t('settings.teams.drawer.shared')}>
                  {grantedAt(openResource)}
                </DescriptionItem>
                <DescriptionItem label={t('settings.teams.drawer.yourAccess')}>
                  {callerAccessLabel(openCaller?.access)}
                </DescriptionItem>
              </DescriptionList>

              <section className="flex flex-col gap-3">
                <SectionHeader
                  as="h3"
                  size="xs"
                  title={t('settings.teams.drawer.accessIn', {
                    interpolation: { escapeValue: false },
                    team: selected.name,
                  })}
                />
                <Card variant="subtle" padding="none">
                  <ListRows>
                    {[
                      ...(openResource.teamGrant
                        ? [openResource.teamGrant]
                        : []),
                      ...openResource.memberGrants,
                    ].map((g) => {
                      const isTeam = !g.target_user_id;
                      const label = isTeam
                        ? t('settings.teams.drawer.everyone', {
                            interpolation: { escapeValue: false },
                            team: selected.name,
                          })
                        : g.target_user_label || truncateSub(g.target_user_id!);
                      const busy = busyGrants.has(grantKey(g));
                      return (
                        <ListRow
                          key={grantKey(g)}
                          leading={
                            <span aria-hidden="true" className="contents">
                              <Avatar
                                alt=""
                                size="sm"
                                variant="primary"
                                shape={isTeam ? 'square' : 'circle'}
                              >
                                {initialOf(isTeam ? selected.name : label)}
                              </Avatar>
                            </span>
                          }
                          title={<span title={label}>{label}</span>}
                          description={
                            isTeam
                              ? t('settings.teams.drawer.teamGrant')
                              : t('settings.teams.drawer.memberGrant')
                          }
                          trailing={
                            <>
                              {callerCanShare ? (
                                <Select
                                  value={g.access_level}
                                  disabled={busy}
                                  onValueChange={(value) =>
                                    handleGrantAccess(g, value as AccessLevel)
                                  }
                                >
                                  <SelectTrigger
                                    size="sm"
                                    className="w-28 shrink-0"
                                    aria-label={t(
                                      'settings.teams.share.access',
                                    )}
                                  >
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {(['viewer', 'editor'] as const).map(
                                      (level) => (
                                        <SelectItem key={level} value={level}>
                                          {accessLevelLabel(level)}
                                        </SelectItem>
                                      ),
                                    )}
                                  </SelectContent>
                                </Select>
                              ) : (
                                <Badge variant="neutral" className="shrink-0">
                                  {accessLevelLabel(g.access_level)}
                                </Badge>
                              )}
                              {(callerCanShare || isAdmin) && (
                                <IconButton
                                  variant="ghost-destructive"
                                  size="icon-sm"
                                  className="shrink-0"
                                  disabled={busy}
                                  label={t('settings.teams.drawer.removeGrant')}
                                  icon={Trash2}
                                  onClick={() => handleUnshare(g)}
                                />
                              )}
                            </>
                          }
                        />
                      );
                    })}
                  </ListRows>
                </Card>
                <p className="text-muted-foreground text-xs">
                  {t('settings.teams.drawer.otherTeamsHint')}
                </p>
              </section>

              <section className="flex flex-col gap-3">
                <SectionHeader
                  as="h3"
                  size="xs"
                  title={t('settings.teams.drawer.whatPeopleCanDo')}
                />
                <ul className="flex flex-col gap-2 text-sm">
                  {capabilityLines(
                    t,
                    openResource.type,
                    resolveSettings(
                      openResource.type,
                      drawerSettings?.settings,
                    ),
                  ).map((line) => (
                    <li key={line.key} className="flex items-center gap-2">
                      {line.allowed ? (
                        <Check
                          className="text-success size-4 shrink-0"
                          aria-hidden
                        />
                      ) : (
                        <X
                          className="text-muted-foreground size-4 shrink-0"
                          aria-hidden
                        />
                      )}
                      <span
                        className={cn(!line.allowed && 'text-muted-foreground')}
                      >
                        {line.text}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="text-muted-foreground text-xs">
                  {t('settings.teams.drawer.capabilitiesHint')}
                </p>
              </section>
            </PanelBody>
          </>
        )}
      </SidePanel>

      {shareTarget && (
        <ShareToTeamModal
          resourceType={shareTarget.type}
          resourceId={shareTarget.id}
          resourceName={resourceName(shareTarget)}
          onClose={() => {
            setShareTarget(null);
            // Back to the drawer, with the grants the dialog may have changed.
            setDrawerOpen(true);
            refreshGrants();
          }}
        />
      )}

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
            pending={modalPending}
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
            <CircleAlert className="size-4" aria-hidden="true" />
            <AlertDescription>{createError}</AlertDescription>
          </Alert>
        )}
      </Modal>

      <Modal
        open={editOpen}
        onOpenChange={(open) => (open ? setEditOpen(true) : closeEditModal())}
        size="sm"
        title={t('settings.teams.editTeam')}
        footer={
          <ModalActions
            cancelLabel={t('cancel')}
            onCancel={closeEditModal}
            submitLabel={t('settings.teams.save')}
            onSubmit={handleEditSave}
            pending={modalPending}
            disabled={!editName.trim()}
          />
        }
      >
        <div className="flex flex-col gap-5">
          <FormField label={t('settings.teams.teamNamePlaceholder')}>
            <Input
              type="text"
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
        title={t('settings.teams.addMemberTitle')}
        description={t('settings.teams.addMemberDescription')}
        footer={
          <ModalActions
            cancelLabel={t('cancel')}
            onCancel={closeAddMemberModal}
            submitLabel={t('settings.teams.add')}
            onSubmit={handleAddMember}
            pending={modalPending}
            disabled={!newMemberEmail.trim()}
          />
        }
      >
        <div className="flex flex-col gap-5">
          <FormField label={t('settings.teams.memberEmailLabel')}>
            <Input
              type="email"
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
          interpolation: { escapeValue: false },
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
