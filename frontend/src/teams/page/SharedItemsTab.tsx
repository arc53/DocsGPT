import {
  ArrowUpRight,
  Bot,
  Check,
  ChevronRight,
  FileText,
  MessageSquare,
  Trash2,
  Users,
  Wrench,
  X,
} from 'lucide-react';
import { type ReactNode, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import teamsService, {
  type AccessLevel,
  canManageTeam,
  type ResourceSettingsResponse,
  type ResourceType,
  type TeamGrant,
  type TeamRole,
} from '../../api/services/teamsService';
import { agentChatPath, agentEditPath } from '../../agents/paths';
import SearchInput from '../../components/SearchInput';
import { Alert, AlertDescription } from '../../components/ui/alert';
import { Avatar } from '../../components/ui/avatar';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Card } from '../../components/ui/card';
import {
  DescriptionItem,
  DescriptionList,
} from '../../components/ui/description-list';
import { EmptyState } from '../../components/ui/empty-state';
import { IconButton } from '../../components/ui/icon-button';
import { ListRow, ListRows } from '../../components/ui/list-row';
import { Pagination, pageRangeParams } from '../../components/ui/pagination';
import { SectionHeader } from '../../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import {
  PanelBody,
  PanelHeader,
  SidePanel,
} from '../../components/ui/side-panel';
import { ToggleGroup, ToggleGroupItem } from '../../components/ui/toggle-group';
import { SHORT_LIST_PAGE_SIZE, useClientPage } from '../../hooks/usePageState';
import { cn } from '../../lib/utils';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { showActionToast } from '../../notifications/actionToastSlice';
import { selectToken } from '../../preferences/preferenceSlice';
import { AppDispatch } from '../../store';
import {
  capabilityLines,
  errorMessage,
  resolveSettings,
} from '../accessSettings';
import ShareToTeamModal from '../ShareToTeamModal';
import type { Team } from '../teamsSlice';
import { can } from '../../utils/accessUtils';
import { formatCount, formatDateOnly } from '../../utils/dateTimeUtils';
import { PERSONAL_WORKSPACE } from '../../workspace/requestWorkspace';
import {
  selectWorkspaceId,
  switchWorkspace,
} from '../../workspace/workspaceSlice';
import OutsideSharesSection, {
  SharedFromTeamsSection,
} from './OutsideSharesSection';
import {
  grantKey,
  grantResourceName,
  groupGrants,
  initialOf,
  isFromTeam,
  isPaused,
  type SharedResource,
  truncateSub,
} from './teamGrants';

type ResourceFilter = 'all' | ResourceType;

const RESOURCE_TYPES: ReadonlyArray<ResourceType> = [
  'agent',
  'source',
  'prompt',
  'tool',
];

// Filter pill order on the shared items list.
const FILTER_TYPES: ReadonlyArray<ResourceType> = [
  'agent',
  'source',
  'tool',
  'prompt',
];

type SharedItemsTabProps = {
  team: Team;
  /** The caller's role in the team. */
  role: TeamRole;
  grants: TeamGrant[];
  /** Reads the team's grants again after a change. */
  onGrantsChanged: () => Promise<void> | void;
};

/**
 * The members' personal items shared with the team: they stay their
 * owners', so the page says so and points at moving the ones the team
 * depends on. A row opens a drawer with who has access and what they can do.
 * Under them, other teams' items shared with this one, and what this team
 * shares outside itself.
 */
export default function SharedItemsTab({
  team,
  role,
  grants,
  onGrantsChanged,
}: SharedItemsTabProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const workspaceId = useSelector(selectWorkspaceId);
  const isAdmin = canManageTeam(role);

  const [resourceFilter, setResourceFilter] = useState<ResourceFilter>('all');
  const [resourceQuery, setResourceQuery] = useState('');
  // The row whose drawer is open (kept while "Manage sharing" has the drawer
  // closed).
  const [openResourceKey, setOpenResourceKey] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerSettings, setDrawerSettings] =
    useState<ResourceSettingsResponse | null>(null);
  const [busyGrants, setBusyGrants] = useState<Set<string>>(new Set());
  const [shareTarget, setShareTarget] = useState<SharedResource | null>(null);
  // The grant waiting on its remove confirm (it takes access away).
  const [grantToRemove, setGrantToRemove] = useState<TeamGrant | null>(null);

  const reportError = (message: string) =>
    dispatch(showActionToast({ variant: 'destructive', message }));

  const resourceTypeLabel = (type: string) =>
    RESOURCE_TYPES.includes(type as ResourceType)
      ? t(`settings.teams.resourceType.${type}`)
      : type;

  // Lucide icon for a grant's resource type, shown in the row's type tile.
  const resourceTypeIcon = (type: string): ReactNode => {
    const props = { size: 16, 'aria-hidden': true } as const;
    switch (type) {
      case 'agent':
        return <Bot {...props} />;
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

  // Another team's items are listed on their own, never as a member's.
  const fromTeams = useMemo(() => grants.filter(isFromTeam), [grants]);
  const sharedResources = useMemo(
    () => groupGrants(grants.filter((g) => !isFromTeam(g))),
    [grants],
  );
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
    grantResourceName(r.grants[0]);
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
      case 'agent':
        return can(openCaller, 'view')
          ? agentEditPath(r.id)
          : agentChatPath(r.id);
      case 'source':
        return '/settings/knowledge';
      case 'tool':
        return '/settings/tools';
      case 'prompt':
        return '/settings/prompts';
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

  const setGrantBusy = (key: string, busy: boolean) =>
    setBusyGrants((prev) => {
      const next = new Set(prev);
      if (busy) next.add(key);
      else next.delete(key);
      return next;
    });

  // Remove one grant: the whole-team grant, or one member's (which needs
  // its target_user_id, or the server would drop the team grant instead).
  // A failure rethrows, so the confirm stays open with unshareError.
  const handleUnshare = async (grant: TeamGrant) => {
    const key = grantKey(grant);
    setGrantBusy(key, true);
    try {
      await teamsService.unshare(
        team.id,
        {
          resource_type: grant.resource_type,
          resource_id: grant.resource_id,
          target_user_id: grant.target_user_id ?? undefined,
        },
        token,
      );
    } finally {
      setGrantBusy(key, false);
      await onGrantsChanged();
    }
  };

  const handleGrantAccess = async (grant: TeamGrant, level: AccessLevel) => {
    if (grant.access_level === level) return;
    const key = grantKey(grant);
    setGrantBusy(key, true);
    try {
      await teamsService.share(
        team.id,
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
      await onGrantsChanged();
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <SectionHeader
        as="h4"
        size="sm"
        title={t('settings.teams.sharedItems.title')}
        count={sharedResources.length}
      />
      <p className="text-muted-foreground text-sm">
        {t('settings.teams.sharedItems.intro')}
      </p>
      {sharedResources.length === 0 ? (
        <EmptyState size="sm" title={t('settings.teams.sharedItems.empty')} />
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
              {(['all', ...FILTER_TYPES] as ResourceFilter[]).map((value) => (
                <ToggleGroupItem
                  key={value}
                  value={value}
                  count={resourceCounts[value]}
                >
                  {t(`settings.teams.sharedList.filter.${value}`)}
                </ToggleGroupItem>
              ))}
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
                        <span title={resourceName(r)}>{resourceName(r)}</span>
                      }
                      description={
                        isPaused(r)
                          ? t('settings.teams.sharedList.paused', {
                              interpolation: { escapeValue: false },
                              name: ownerLabel(r),
                            })
                          : t('settings.teams.sharedList.meta', {
                              interpolation: { escapeValue: false },
                              type: resourceTypeLabel(r.type),
                              owner: ownerLabel(r),
                            })
                      }
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

      <SidePanel
        open={drawerOpen && openResource !== null}
        onOpenChange={(open) => !open && closeDrawer()}
      >
        {openResource && (
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
                    // A member's personal item lives in Personal for
                    // everyone it's shared with, the viewer included.
                    if (workspaceId !== PERSONAL_WORKSPACE)
                      dispatch(
                        switchWorkspace(PERSONAL_WORKSPACE, {
                          reason: 'link',
                        }),
                      );
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
              {isPaused(openResource) && (
                <Alert variant="warning">
                  <AlertDescription>
                    {t('settings.teams.drawer.paused', {
                      interpolation: { escapeValue: false },
                      name: ownerLabel(openResource),
                    })}
                  </AlertDescription>
                </Alert>
              )}
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
                    team: team.name,
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
                            team: team.name,
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
                                {initialOf(isTeam ? team.name : label)}
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
                                  onClick={() => setGrantToRemove(g)}
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
            {grantToRemove && (
              <ConfirmationModal
                message={t('settings.teams.share.removeConfirm', {
                  interpolation: { escapeValue: false },
                  name: grantToRemove.target_user_id
                    ? grantToRemove.target_user_label ||
                      truncateSub(grantToRemove.target_user_id)
                    : team.name,
                })}
                description={
                  grantToRemove.target_user_id
                    ? t('settings.teams.share.removeConfirmPerson', {
                        interpolation: { escapeValue: false },
                        name:
                          grantToRemove.target_user_label ||
                          truncateSub(grantToRemove.target_user_id),
                        resource: resourceName(openResource),
                        team: team.name,
                      })
                    : t('settings.teams.share.removeConfirmTeam', {
                        interpolation: { escapeValue: false },
                        team: team.name,
                        resource: resourceName(openResource),
                      })
                }
                modalState="ACTIVE"
                setModalState={(state) =>
                  state === 'INACTIVE' && setGrantToRemove(null)
                }
                submitLabel={t('settings.teams.remove')}
                handleSubmit={() => handleUnshare(grantToRemove)}
                error={t('settings.teams.unshareError')}
                variant="destructive"
              />
            )}
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
            onGrantsChanged();
          }}
          onMoved={() => void onGrantsChanged()}
        />
      )}

      {/* Other teams' items, then what this team takes outside. */}
      <div className="mt-5 flex flex-col gap-8">
        <SharedFromTeamsSection
          team={team}
          grants={fromTeams}
          onGrantsChanged={onGrantsChanged}
        />
        <OutsideSharesSection team={team} role={role} />
      </div>
    </div>
  );
}
