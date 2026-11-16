import {
  Bot,
  FileText,
  KeyRound,
  type LucideIcon,
  MessageSquare,
  Plus,
  Trash2,
  Wallet,
  Wrench,
} from 'lucide-react';
import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import teamsService, {
  type AssignableTeamRole,
  canManageTeam,
  memberTeamRole,
  type ResourceType,
  type TeamGrant,
  teamErrorMessage,
  TeamsApiError,
  type TeamMember,
  type TeamRole,
} from '../../api/services/teamsService';
import SearchInput from '../../components/SearchInput';
import { Alert, AlertDescription } from '../../components/ui/alert';
import { Avatar } from '../../components/ui/avatar';
import { Button } from '../../components/ui/button';
import { EmptyState } from '../../components/ui/empty-state';
import { FormField } from '../../components/ui/form-field';
import { IconButton } from '../../components/ui/icon-button';
import { Input } from '../../components/ui/input';
import { ListRow, ListRows } from '../../components/ui/list-row';
import { Modal, ModalActions } from '../../components/ui/modal';
import { Pagination, pageRangeParams } from '../../components/ui/pagination';
import { SectionHeader } from '../../components/ui/section-header';
import { useDebouncedValue } from '../../hooks';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { ActiveState } from '../../models/misc';
import { showActionToast } from '../../notifications/actionToastSlice';
import { selectToken } from '../../preferences/preferenceSlice';
import { AppDispatch } from '../../store';
import { decodeJwtPayload } from '../../utils/jwtUtils';
import { loadWorkspaces } from '../../workspace/workspaceSlice';
import { loadTeams, type Team } from '../teamsSlice';
import {
  grantResourceName,
  initialOf,
  sharedBy,
  truncateSub,
} from './teamGrants';
import TeamRoleSelect, { TeamRoleBadge } from './TeamRoleSelect';

/** Members per page; search and the pager appear past one page. */
const MEMBERS_PAGE_SIZE = 25;

type Member = TeamMember & { source?: string };

/** What a change of membership pauses of what the member pays for. */
type PausedCounts = { schedules: number; outside_access: number };

const ROLE_RANK: Record<TeamRole, number> = {
  viewer: 0,
  editor: 1,
  admin: 2,
  owner: 3,
};

/**
 * What a role change or a removal pauses of what a member pays for on the
 * team's agents: the schedules they set once they drop below Editor, the
 * outside access they pay for once they drop below Admin. The counts come
 * from the server (`pays_for`, sent to owners and admins only).
 *
 * Args:
 *   member: The member, with `pays_for`.
 *   next: Their role after the change, or null when they leave.
 *
 * Returns:
 *   The counts that would pause; zeros without `pays_for`.
 */
function pausedByChange(
  member: TeamMember,
  next: TeamRole | null,
): PausedCounts {
  const pays = member.pays_for;
  if (!pays) return { schedules: 0, outside_access: 0 };
  const before = memberTeamRole(member);
  const loses = (needed: TeamRole): boolean =>
    ROLE_RANK[before] >= ROLE_RANK[needed] &&
    (next === null || ROLE_RANK[next] < ROLE_RANK[needed]);
  return {
    schedules: loses('editor') ? pays.schedules || 0 : 0,
    outside_access: loses('admin') ? pays.outside_access || 0 : 0,
  };
}

const pausesAnything = (counts: PausedCounts): boolean =>
  counts.schedules > 0 || counts.outside_access > 0;

/** One consequence line in a confirm: an icon, what happens, and why. */
function Consequence({
  icon: Icon,
  title,
  detail,
}: {
  icon: LucideIcon;
  title: string;
  detail: string;
}) {
  return (
    <div className="flex gap-3">
      <Icon
        className="text-muted-foreground mt-0.5 size-4 shrink-0"
        aria-hidden
      />
      <div className="min-w-0">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-muted-foreground text-xs">{detail}</p>
      </div>
    </div>
  );
}

const RESOURCE_ICONS: Record<ResourceType, typeof Bot> = {
  agent: Bot,
  source: FileText,
  prompt: MessageSquare,
  tool: Wrench,
};

type MembersTabProps = {
  team: Team;
  /** The caller's role in the team. */
  role: TeamRole;
  /** The team's grants: the remove dialog lists what a member shares. */
  grants: TeamGrant[];
};

/**
 * A team's members and their roles. Owners and admins add people (as Viewer
 * unless they pick another role), change roles and remove people; everyone
 * else reads the list.
 */
export default function MembersTab({ team, role, grants }: MembersTabProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const canManage = canManageTeam(role);

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

  const [addOpen, setAddOpen] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [newRole, setNewRole] = useState<AssignableTeamRole>('viewer');
  const [addError, setAddError] = useState<string | null>(null);
  const [addPending, setAddPending] = useState(false);

  const [removeState, setRemoveState] = useState<ActiveState>('INACTIVE');
  const [memberToRemove, setMemberToRemove] = useState<Member | null>(null);

  // A role change that would pause what the member pays for asks first.
  const [roleChangeState, setRoleChangeState] =
    useState<ActiveState>('INACTIVE');
  const [roleChange, setRoleChange] = useState<{
    member: Member;
    next: AssignableTeamRole;
    paused: PausedCounts;
  } | null>(null);

  // The caller's own sub: changing your own role changes what you can do.
  const currentUserId = useMemo(() => {
    const payload = token ? decodeJwtPayload(token) : null;
    return typeof payload?.sub === 'string' ? payload.sub : undefined;
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    teamsService
      .listMembers(team.id, token, {
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
  }, [team.id, token, debouncedMemberQuery, membersPage, membersReload]);

  const memberLabel = (m: Member): string =>
    m.email && m.email.trim() !== '' ? m.email : truncateSub(m.user_id);

  // Where a membership came from: manual add, an SSO group claim, or SCIM
  // provisioning. Falls back to the raw source value for forward-compat.
  const sourceLabel = (s?: string): string | undefined =>
    s
      ? ((
          {
            manual: t('settings.teams.sourceManual'),
            oidc_group: t('settings.teams.sourceSso'),
            scim: t('settings.teams.sourceScim'),
          } as Record<string, string>
        )[s] ?? s)
      : undefined;

  // The list and the switcher show counts and the caller's role; refresh
  // them after a change (the workspaces too when it was the caller's role).
  const afterChange = (memberId?: string) => {
    setMembersReload((n) => n + 1);
    dispatch(loadTeams({ token }));
    if (memberId && memberId === currentUserId)
      dispatch(loadWorkspaces({ token }));
  };

  const reportError = (message: string) =>
    dispatch(showActionToast({ variant: 'destructive', message }));

  const openAdd = () => {
    setNewEmail('');
    setNewRole('viewer');
    setAddError(null);
    setAddOpen(true);
  };

  const closeAdd = () => {
    setAddOpen(false);
    setAddError(null);
  };

  const handleAdd = async () => {
    if (!newEmail.trim() || addPending) return;
    setAddError(null);
    setAddPending(true);
    try {
      const res = await teamsService.addMember(
        team.id,
        { email: newEmail.trim(), role: newRole },
        token,
      );
      if (res?.success === false) {
        setAddError(res.message ?? t('settings.teams.memberNotFound'));
        return;
      }
      setAddOpen(false);
      afterChange();
    } catch (error) {
      // An email nobody has signed in with is a 404 with the server's
      // reason ("they must sign in first").
      setAddError(
        teamErrorMessage(t, error, t('settings.teams.addMemberError')),
      );
    } finally {
      setAddPending(false);
    }
  };

  const handleRoleChange = async (member: Member, next: AssignableTeamRole) => {
    try {
      const res = await teamsService.setMemberRole(
        team.id,
        member.user_id,
        next,
        token,
      );
      if (res?.success === false)
        reportError(res.message ?? t('settings.teams.updateFailed'));
    } catch (error) {
      reportError(
        teamErrorMessage(t, error, t('settings.teams.roleChangeError')),
      );
    }
    afterChange(member.user_id);
  };

  const requestRoleChange = (member: Member, next: AssignableTeamRole) => {
    const paused = pausedByChange(member, next);
    if (!pausesAnything(paused)) {
      handleRoleChange(member, next);
      return;
    }
    setRoleChange({ member, next, paused });
    setRoleChangeState('ACTIVE');
  };

  // Returns the request so the confirm stays open on a failure and says why.
  const confirmRoleChange = async () => {
    if (!roleChange) return;
    const { member, next } = roleChange;
    const res = await teamsService.setMemberRole(
      team.id,
      member.user_id,
      next,
      token,
    );
    if (res?.success === false)
      throw new TeamsApiError(
        400,
        res.message ?? t('settings.teams.updateFailed'),
      );
    setRoleChange(null);
    afterChange(member.user_id);
  };

  // The lines a confirm adds for what the member pays for.
  const payerLines = (name: string, paused: PausedCounts): ReactNode[] => {
    const lines: ReactNode[] = [];
    if (paused.schedules > 0)
      lines.push(
        <Consequence
          key="schedules"
          icon={Wallet}
          title={t('payer.team.remove.schedules', {
            count: paused.schedules,
            name,
            interpolation: { escapeValue: false },
          })}
          detail={t('payer.team.remove.schedulesDetail', {
            name,
            interpolation: { escapeValue: false },
          })}
        />,
      );
    if (paused.outside_access > 0)
      lines.push(
        <Consequence
          key="access"
          icon={KeyRound}
          title={t('payer.team.remove.access', {
            count: paused.outside_access,
          })}
          detail={t('payer.team.remove.accessDetail', {
            name,
            interpolation: { escapeValue: false },
          })}
        />,
      );
    return lines;
  };

  const requestRemove = (member: Member) => {
    setMemberToRemove(member);
    setRemoveState('ACTIVE');
  };

  // Returns the request so the confirm stays open on a failure and says why;
  // the member is cleared only once they're gone, so the dialog keeps the name.
  const confirmRemove = async () => {
    if (!memberToRemove) return;
    await teamsService.removeMember(team.id, memberToRemove.user_id, token);
    const removed = memberToRemove.user_id;
    setMemberToRemove(null);
    afterChange(removed);
  };

  const removeName = memberToRemove ? memberLabel(memberToRemove) : '';
  const removeShared = memberToRemove
    ? sharedBy(grants, memberToRemove.user_id)
    : [];
  const removePayerLines = memberToRemove
    ? payerLines(removeName, pausedByChange(memberToRemove, null))
    : [];
  const roleChangeName = roleChange ? memberLabel(roleChange.member) : '';

  const resourceIcon = (type: ResourceType): ReactNode => {
    const Icon = RESOURCE_ICONS[type] ?? FileText;
    return <Icon className="size-4" aria-hidden />;
  };

  return (
    <div className="flex flex-col gap-3">
      <SectionHeader
        as="h4"
        size="sm"
        title={t('settings.teams.members')}
        count={membersAll}
        actions={
          (membersAll > MEMBERS_PAGE_SIZE || canManage) && (
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
              {canManage && (
                <Button
                  variant="outline"
                  size="field"
                  className="shrink-0"
                  onClick={openAdd}
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
          {members.map((m) => {
            const memberRole = memberTeamRole(m);
            const isOwner = memberRole === 'owner';
            return (
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
                    {canManage && !isOwner ? (
                      <TeamRoleSelect
                        value={memberRole}
                        onChange={(next) => requestRoleChange(m, next)}
                        className="shrink-0"
                        aria-label={t('settings.teams.memberRoleLabel')}
                      />
                    ) : (
                      <TeamRoleBadge role={memberRole} />
                    )}
                    {canManage && !isOwner && (
                      <IconButton
                        variant="ghost-destructive"
                        size="icon-sm"
                        className="shrink-0"
                        label={t('settings.teams.remove')}
                        icon={Trash2}
                        onClick={() => requestRemove(m)}
                      />
                    )}
                  </>
                }
              />
            );
          })}
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

      <Modal
        open={addOpen}
        onOpenChange={(open) => (open ? setAddOpen(true) : closeAdd())}
        size="sm"
        title={t('settings.teams.addMemberTitle')}
        description={t('settings.teams.addMemberDescription')}
        footer={
          <ModalActions
            cancelLabel={t('cancel')}
            onCancel={closeAdd}
            submitLabel={t('settings.teams.add')}
            onSubmit={handleAdd}
            pending={addPending}
            disabled={!newEmail.trim()}
          />
        }
      >
        <div className="flex flex-col gap-5">
          <FormField label={t('settings.teams.memberEmailLabel')}>
            <Input
              type="email"
              placeholder={t('settings.teams.memberEmailPlaceholder')}
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            />
          </FormField>
          <FormField
            label={t('settings.teams.memberRoleLabel')}
            hint={t(`settings.teams.roleHints.${newRole}`)}
          >
            <TeamRoleSelect
              value={newRole}
              onChange={setNewRole}
              size="field"
              className="w-full"
            />
          </FormField>
        </div>
        {addError && (
          <Alert variant="destructive" className="mt-3">
            <AlertDescription>{addError}</AlertDescription>
          </Alert>
        )}
      </Modal>

      <ConfirmationModal
        message={t('settings.teams.removeMemberConfirmation', {
          interpolation: { escapeValue: false },
          name: removeName,
          team: team.name,
        })}
        description={t('settings.teams.removeMember.teamItemsStay', {
          interpolation: { escapeValue: false },
          name: removeName,
          team: team.name,
        })}
        modalState={removeState}
        setModalState={setRemoveState}
        submitLabel={t('settings.teams.remove')}
        handleSubmit={confirmRemove}
        handleCancel={() => setMemberToRemove(null)}
        error={(e) =>
          teamErrorMessage(t, e, t('settings.teams.removeMemberError'))
        }
        variant="destructive"
      >
        {removePayerLines.length > 0 && (
          <div className="flex flex-col gap-3">{removePayerLines}</div>
        )}
        {removeShared.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium">
              {t('settings.teams.removeMember.personalItems', {
                interpolation: { escapeValue: false },
                count: removeShared.length,
                name: removeName,
                team: team.name,
              })}
            </p>
            <ListRows>
              {removeShared.map((item) => (
                <ListRow
                  key={item.key}
                  leading={
                    <Avatar
                      aria-hidden="true"
                      size="sm"
                      shape="square"
                      variant="icon"
                    >
                      {resourceIcon(item.type)}
                    </Avatar>
                  }
                  title={grantResourceName(item.grants[0])}
                  description={t(`settings.teams.resourceType.${item.type}`)}
                />
              ))}
            </ListRows>
            <p className="text-muted-foreground text-xs">
              {t('settings.teams.removeMember.personalItemsPaused', {
                interpolation: { escapeValue: false },
                name: removeName,
                team: team.name,
              })}
            </p>
          </div>
        )}
      </ConfirmationModal>

      <ConfirmationModal
        message={t('payer.team.demote.title', {
          interpolation: { escapeValue: false },
          name: roleChangeName,
          role: roleChange
            ? t(`workspace.common.roles.${roleChange.next}`)
            : '',
        })}
        description={t('payer.team.demote.description', {
          interpolation: { escapeValue: false },
          name: roleChangeName,
          team: team.name,
        })}
        modalState={roleChangeState}
        setModalState={setRoleChangeState}
        submitLabel={t('payer.team.demote.submit')}
        handleSubmit={confirmRoleChange}
        handleCancel={() => setRoleChange(null)}
        error={(e) =>
          teamErrorMessage(t, e, t('settings.teams.roleChangeError'))
        }
      >
        {roleChange && (
          <div className="flex flex-col gap-3">
            {payerLines(roleChangeName, roleChange.paused)}
          </div>
        )}
      </ConfirmationModal>
    </div>
  );
}
