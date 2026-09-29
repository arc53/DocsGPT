import {
  ArrowLeft,
  ArrowRight,
  ChevronRight,
  CircleAlert,
  Trash2,
  UserRound,
  UsersRound,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import teamsService, {
  AccessLevel,
  ResourceSetting,
  ResourceSettingsResponse,
  ResourceShare,
  ResourceType,
  TeamMember,
} from '../api/services/teamsService';
import connectorsService from '../api/services/connectorsService';
import AgentUsesSection from '../agents/components/AgentUsesSection';
import SearchInput from '../components/SearchInput';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Checkbox } from '../components/ui/checkbox';
import { Label } from '../components/ui/label';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/ui/empty-state';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '../components/ui/command';
import { IconButton } from '../components/ui/icon-button';
import { ListRow, ListRows } from '../components/ui/list-row';
import { Modal } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '../components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { cn } from '../lib/utils';
import { selectToken } from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import { can } from '../utils/accessUtils';
import { formatCount } from '../utils/dateTimeUtils';
import { decodeJwtPayload } from '../utils/jwtUtils';
import {
  anyChanged,
  editorHint,
  errorMessage,
  resolveSettings,
  settingCopy,
  shownSettings,
} from './accessSettings';
import { loadTeams, selectTeams } from './teamsSlice';

/** A connection-backed tool: whose account shares of it run with. */
export type ShareCredentials = {
  toolId: string;
  connectorName: string;
  /** The connection's account; empty when the caller isn't its owner. */
  account: string;
  mode: 'owner' | 'member';
  /** Set when an admin forces one mode for every share of this connector. */
  forcedMode?: 'owner' | 'member' | null;
  /** Owner-mode shares of a tool with write actions need an explicit OK. */
  hasWrites: boolean;
  /**
   * An editor the owner lets share: the mode is the owner's choice, shown
   * but locked, and the write confirmation still applies.
   */
  readOnly?: boolean;
};

type Props = {
  resourceType: ResourceType;
  resourceId: string;
  resourceName?: string;
  credentials?: ShareCredentials;
  onClose: () => void;
};

// Member subs (OIDC subs) can be long; there's no display-name endpoint, so we
// truncate the middle for readability while keeping the ends identifiable.
const truncateSub = (sub: string): string =>
  sub.length > 24 ? `${sub.slice(0, 12)}…${sub.slice(-8)}` : sub;

// Prefer the member's email for a human-readable label, falling back to the
// truncated sub when no email is on record.
const memberLabel = (member: TeamMember): string =>
  member.email && member.email.trim() !== ''
    ? member.email
    : truncateSub(member.user_id);

const initialOf = (label: string): string => {
  const trimmed = label.trim();
  return trimmed ? trimmed[0].toUpperCase() : '?';
};

// Stable identity for a grant row: team + optional member target.
const shareKey = (share: ResourceShare): string =>
  `${share.team_id}:${share.target_user_id ?? ''}`;

// Up to this many grants the dialog lists them all; above it, You plus the
// PREVIEW_COUNT most recent and a "Show all" step.
const SHORT_LIST_MAX = 5;
const PREVIEW_COUNT = 3;

type AccessFilter = 'all' | 'teams' | 'people' | 'editors';

type Suggestion =
  | { kind: 'team'; key: string; teamId: string; teamName: string }
  | {
      kind: 'member';
      key: string;
      teamId: string;
      teamName: string;
      userId: string;
      label: string;
    };

export default function ShareToTeamModal({
  resourceType,
  resourceId,
  resourceName,
  credentials,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const teams = useSelector(selectTeams);
  // The caller's own OIDC sub — you're the owner, so you're excluded from the
  // "share with a specific person" suggestions (can't share with yourself).
  const currentUserId = useMemo(() => {
    const payload = token ? decodeJwtPayload(token) : null;
    return typeof payload?.sub === 'string' ? payload.sub : undefined;
  }, [token]);

  const [shares, setShares] = useState<ResourceShare[]>([]);
  const [loadError, setLoadError] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const savedCredentialMode =
    credentials?.forcedMode ?? credentials?.mode ?? 'owner';
  const [credentialMode, setCredentialMode] = useState<'owner' | 'member'>(
    savedCredentialMode,
  );
  // The caller may open the dialog before the tool's connection has loaded:
  // follow the mode (or an admin's forced one) when it arrives or changes.
  const [seenCredentialMode, setSeenCredentialMode] =
    useState(savedCredentialMode);
  if (savedCredentialMode !== seenCredentialMode) {
    setSeenCredentialMode(savedCredentialMode);
    setCredentialMode(savedCredentialMode);
  }
  const [writesConfirmed, setWritesConfirmed] = useState(false);
  const needsWriteConfirm =
    !!credentials && credentialMode === 'owner' && credentials.hasWrites;
  const changeCredentialMode = (mode: 'owner' | 'member') => {
    if (!credentials || credentials.readOnly || mode === credentialMode) return;
    const previous = credentialMode;
    setCredentialMode(mode);
    connectorsService
      .setCredentialMode(credentials.toolId, mode, token)
      .then((data) => {
        if (!data?.success) throw new Error('save failed');
      })
      .catch(() => {
        setCredentialMode(previous);
        setActionError(t('settings.connectors.share.saveFailed'));
      });
  };

  // The owner's per-resource switches and the caller's own access, from
  // GET /api/resource_settings. Null until loaded (or when it fails: the hint
  // then uses the defaults and the settings group stays hidden).
  const [settingsInfo, setSettingsInfo] =
    useState<ResourceSettingsResponse | null>(null);
  // Access settings is collapsed by default and opens itself once when a
  // switch is off its default; after that it follows the user's clicks.
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [savingSettings, setSavingSettings] = useState<Set<string>>(new Set());

  // 'all' is the "People with access" step with search and filters.
  const [step, setStep] = useState<'main' | 'all'>('main');
  const [accessQuery, setAccessQuery] = useState('');
  const [accessFilter, setAccessFilter] = useState<AccessFilter>('all');

  // The access level applied to the next suggestion picked from the combobox.
  const [accessLevel, setAccessLevel] = useState<AccessLevel>('viewer');

  // Combobox state.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [query, setQuery] = useState('');

  // Per-team member cache (deduped per user). Loaded lazily for People
  // suggestions and to resolve per-member labels in the access list.
  const [membersByTeam, setMembersByTeam] = useState<
    Record<string, TeamMember[]>
  >({});
  // Team ids with an in-flight members fetch, so a re-run of the fan-out effect
  // (e.g. a teams reload) doesn't fire a duplicate request before its cache write.
  const membersInFlight = useRef<Set<string>>(new Set());

  // Committing = a suggestion pick is in flight (blocks ESC/overlay close).
  const [committing, setCommitting] = useState(false);
  // Per-row busy keys so one in-flight row doesn't freeze the whole list.
  const [busyKeys, setBusyKeys] = useState<Set<string>>(new Set());
  // Ref mirror, kept in sync *synchronously* with each setRowBusy call, so a
  // reconcile after a settle reads the current busy set rather than a closure-
  // stale or not-yet-committed-render value.
  const busyKeysRef = useRef<Set<string>>(busyKeys);

  const setRowBusy = (key: string, busy: boolean) => {
    const next = new Set(busyKeysRef.current);
    if (busy) next.add(key);
    else next.delete(key);
    busyKeysRef.current = next;
    setBusyKeys(next);
  };

  const inFlight = committing || busyKeys.size > 0;

  const refreshShares = () => {
    setLoadError(false);
    return teamsService
      .listResourceShares(resourceType, resourceId, token)
      .then((r) => {
        const server = (r?.shares ?? []) as ResourceShare[];
        // Server state is authoritative, but a reconcile triggered by one
        // action's settle must not stomp a *different* row whose optimistic
        // edit is still in flight. Keep the local row for any key still busy,
        // and append still-busy local rows the server hasn't returned yet.
        setShares((prev) => {
          const busy = busyKeysRef.current;
          if (busy.size === 0) return server;
          const serverByKey = new Map(server.map((s) => [shareKey(s), s]));
          const prevBusy = prev.filter((s) => busy.has(shareKey(s)));
          const merged = server.map(
            (s) => prevBusy.find((p) => shareKey(p) === shareKey(s)) ?? s,
          );
          for (const p of prevBusy) {
            if (!serverByKey.has(shareKey(p))) merged.push(p);
          }
          return merged;
        });
      })
      .catch(() => {
        // Distinguish a failed load from a genuinely empty list: keep any
        // previously known shares and surface an error rather than silently
        // rendering "no access" on a fetch failure.
        setLoadError(true);
      });
  };

  useEffect(() => {
    dispatch(loadTeams({ token }));
    refreshShares();
    setSettingsInfo(null);
    teamsService
      .getResourceSettings(resourceType, resourceId, token)
      .then((r) => {
        setSettingsInfo(r);
        const shown = shownSettings(
          resourceType,
          resolveSettings(resourceType, r?.settings),
          !!credentials,
        );
        if (anyChanged(shown)) {
          setSettingsOpen(true);
        }
      })
      .catch(() => {
        // Without settings the hint falls back to the defaults and the
        // owner-only group stays hidden; sharing itself still works.
      });
  }, [resourceType, resourceId]);

  // A connected tool hides "Editors can change credentials": its secret is
  // the owner's connection, which editors never change.
  const settings = useMemo<ResourceSetting[]>(
    () =>
      shownSettings(
        resourceType,
        resolveSettings(resourceType, settingsInfo?.settings),
        !!credentials,
      ),
    [resourceType, settingsInfo, credentials],
  );
  const canManageSettings = can(settingsInfo, 'manage_settings');

  // Optimistically flip one switch, then adopt the server's answer; revert
  // and show an Alert when the PUT fails.
  const toggleSetting = async (key: string, value: boolean) => {
    if (!settingsInfo) return;
    const previous = settingsInfo;
    setActionError(null);
    setSettingsInfo({
      ...previous,
      settings: resolveSettings(resourceType, previous.settings).map((s) =>
        s.key === key ? { ...s, value } : s,
      ),
    });
    setSavingSettings((prev) => new Set(prev).add(key));
    try {
      const r = await teamsService.updateResourceSettings(
        resourceType,
        resourceId,
        { [key]: value },
        token,
      );
      if (r?.settings) setSettingsInfo(r);
    } catch (error) {
      setSettingsInfo(previous);
      setActionError(
        errorMessage(error, t('settings.teams.accessSettings.saveError')),
      );
    } finally {
      setSavingSettings((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  // Stable signature of the current team set; lets the fan-out effect below
  // depend on team identity rather than the array reference (which is a fresh
  // object on every loadTeams.fulfilled and would otherwise re-fire on reload).
  const teamIdsKey = useMemo(
    () =>
      teams
        .map((team) => team.id)
        .sort()
        .join(','),
    [teams],
  );

  // Lazily load every team's members once we have the team list, so People
  // suggestions and per-member labels are available. Cached per team, with an
  // in-flight guard so a re-run can't duplicate a not-yet-cached fetch.
  useEffect(() => {
    teams.forEach((team) => {
      if (membersByTeam[team.id] || membersInFlight.current.has(team.id))
        return;
      membersInFlight.current.add(team.id);
      teamsService
        .listMembers(team.id, token)
        .then((r) => {
          const members = (r?.members ?? []) as TeamMember[];
          // Collapse the per-(role, source) rows the API returns into one
          // entry per member, matching the previous modal's dedupe.
          const unique = Array.from(
            new Map(members.map((m) => [m.user_id, m])).values(),
          );
          setMembersByTeam((prev) =>
            prev[team.id] ? prev : { ...prev, [team.id]: unique },
          );
        })
        .catch(() => {
          // A members fetch failure just means fewer People suggestions /
          // sub fallbacks for that team; not a hard error for the modal.
        })
        .finally(() => {
          membersInFlight.current.delete(team.id);
        });
    });
    // membersByTeam is intentionally read but omitted from deps: it's only an
    // already-cached guard, and including it would re-fire on every cache write.
  }, [teamIdsKey, token]);

  const teamName = (teamId: string): string =>
    teams.find((team) => team.id === teamId)?.name ?? teamId;

  // Resolve a member's display label from the loaded cache, falling back to a
  // truncated sub when the email isn't known.
  const memberDisplay = (teamId: string, userId: string): string => {
    const member = (membersByTeam[teamId] ?? []).find(
      (m) => m.user_id === userId,
    );
    return member ? memberLabel(member) : truncateSub(userId);
  };

  // Set of granted keys (team + optional member) for fast exclusion.
  const grantedKeys = useMemo(() => new Set(shares.map(shareKey)), [shares]);

  const matches = (haystack: string, q: string): boolean => {
    const needle = q.trim().toLowerCase();
    if (!needle) return true;
    return haystack.toLowerCase().includes(needle);
  };

  const teamSuggestions = useMemo<Suggestion[]>(
    () =>
      teams
        // Exclude teams already whole-team-shared.
        .filter((team) => !grantedKeys.has(`${team.id}:`))
        .filter((team) => matches(team.name, query))
        .map((team) => ({
          kind: 'team' as const,
          key: `team:${team.id}`,
          teamId: team.id,
          teamName: team.name,
        })),
    [teams, grantedKeys, query],
  );

  const memberSuggestions = useMemo<Suggestion[]>(() => {
    const out: Suggestion[] = [];
    teams.forEach((team) => {
      // Skip teams already whole-team-shared: their members are covered by the
      // team grant, so offering them would only create redundant per-member
      // grants. (Whole-team key convention is `${team_id}:`.)
      if (grantedKeys.has(`${team.id}:`)) return;
      (membersByTeam[team.id] ?? []).forEach((member) => {
        // You can't share a resource with yourself — you own it.
        if (member.user_id === currentUserId) return;
        const key = `${team.id}:${member.user_id}`;
        // Exclude (team, member) pairs already granted.
        if (grantedKeys.has(key)) return;
        const label = memberLabel(member);
        if (!matches(`${label} ${member.user_id} ${team.name}`, query)) return;
        out.push({
          kind: 'member',
          key: `member:${key}`,
          teamId: team.id,
          teamName: team.name,
          userId: member.user_id,
          label,
        });
      });
    });
    return out;
  }, [teams, membersByTeam, grantedKeys, query, currentUserId]);

  const hasSuggestions =
    teamSuggestions.length > 0 || memberSuggestions.length > 0;

  // Mutations update `shares` optimistically for instant feedback, then
  // reconcile against the server once the request settles: refreshShares() runs
  // on BOTH success and failure so server state is authoritative. This avoids
  // the pitfalls of a manual revert-by-shareKey (stomping a concurrent change,
  // re-adding a duplicate row on remove-failure, clobbering a newer value on
  // role-change-failure). Per-row busy keys still gate each row's controls.

  // Optimistically commit a picked suggestion, then reconcile with the server.
  const commitSuggestion = async (suggestion: Suggestion) => {
    setPickerOpen(false);
    setQuery('');
    setActionError(null);
    setCommitting(true);

    const optimistic: ResourceShare =
      suggestion.kind === 'team'
        ? {
            team_id: suggestion.teamId,
            team_name: suggestion.teamName,
            access_level: accessLevel,
            target_user_id: null,
          }
        : {
            team_id: suggestion.teamId,
            team_name: suggestion.teamName,
            access_level: accessLevel,
            target_user_id: suggestion.userId,
          };
    setShares((prev) => [...prev, optimistic]);

    try {
      await teamsService.share(
        suggestion.teamId,
        {
          resource_type: resourceType,
          resource_id: resourceId,
          access_level: accessLevel,
          target_user_id:
            suggestion.kind === 'member' ? suggestion.userId : undefined,
        },
        token,
      );
    } catch (error) {
      setActionError(errorMessage(error, t('settings.teams.share.shareError')));
    } finally {
      // Clear this action's in-flight flag *before* reconciling so the refresh
      // adopts the server's canonical state for this pick (while still
      // preserving any other row whose optimistic edit is still in flight).
      setCommitting(false);
      // Reconcile against the server on success and failure alike: a successful
      // grant gets its canonical row, a failed one drops the optimistic row.
      await refreshShares();
    }
  };

  // Optimistically change a grant's access level (upsert, last-write-wins),
  // then reconcile with the server.
  const changeAccess = async (share: ResourceShare, level: AccessLevel) => {
    if (share.access_level === level) return;
    const key = shareKey(share);
    setActionError(null);
    setRowBusy(key, true);
    setShares((prev) =>
      prev.map((s) =>
        shareKey(s) === key ? { ...s, access_level: level } : s,
      ),
    );
    try {
      await teamsService.share(
        share.team_id,
        {
          resource_type: resourceType,
          resource_id: resourceId,
          access_level: level,
          target_user_id: share.target_user_id ?? undefined,
        },
        token,
      );
    } catch (error) {
      setActionError(errorMessage(error, t('settings.teams.share.shareError')));
    } finally {
      // Free this row before reconciling so the refresh adopts server state for
      // it; other rows still busy keep their in-flight optimistic edits.
      setRowBusy(key, false);
      await refreshShares();
    }
  };

  // Optimistically remove a grant, then reconcile with the server.
  const removeAccess = async (share: ResourceShare) => {
    const key = shareKey(share);
    setActionError(null);
    setRowBusy(key, true);
    setShares((prev) => prev.filter((s) => shareKey(s) !== key));
    try {
      await teamsService.unshare(
        share.team_id,
        {
          resource_type: resourceType,
          resource_id: resourceId,
          target_user_id: share.target_user_id ?? undefined,
        },
        token,
      );
    } catch (error) {
      setActionError(
        errorMessage(error, t('settings.teams.share.unshareError')),
      );
    } finally {
      setRowBusy(key, false);
      await refreshShares();
    }
  };

  const title = resourceName
    ? t('settings.teams.share.titleNamed', {
        interpolation: { escapeValue: false },
        name: resourceName,
      })
    : t('settings.teams.share.titleGeneric', {
        interpolation: { escapeValue: false },
        type: t(`settings.teams.resourceType.${resourceType}`).toLowerCase(),
      });

  const renderRoleControl = (share: ResourceShare) => {
    const key = shareKey(share);
    const rowBusy = busyKeys.has(key);
    return (
      <>
        <Select
          value={share.access_level}
          disabled={rowBusy}
          onValueChange={(value) => changeAccess(share, value as AccessLevel)}
        >
          <SelectTrigger
            size="sm"
            className="w-28 shrink-0"
            aria-label={t('settings.teams.share.access')}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(['viewer', 'editor'] as AccessLevel[]).map((level) => (
              <SelectItem key={level} value={level}>
                {t(`settings.teams.share.accessLevel.${level}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <IconButton
          variant="ghost-destructive"
          size="icon-sm"
          icon={Trash2}
          disabled={rowBusy}
          label={t('settings.teams.share.removeAccess')}
          onClick={() => removeAccess(share)}
        />
      </>
    );
  };

  const renderShareRow = (share: ResourceShare) => {
    const isTeam = !share.target_user_id;
    const name = share.team_name ?? teamName(share.team_id);
    const primary = isTeam
      ? name
      : memberDisplay(share.team_id, share.target_user_id!);
    const secondary = isTeam
      ? t('settings.teams.share.teamLabel')
      : t('settings.teams.share.viaTeam', {
          interpolation: { escapeValue: false },
          team: name,
        });
    return (
      <ListRow
        key={shareKey(share)}
        leading={
          <Avatar
            alt=""
            variant="primary"
            size="default"
            shape={isTeam ? 'square' : 'circle'}
          >
            {initialOf(primary)}
          </Avatar>
        }
        title={<span title={primary}>{primary}</span>}
        description={<span title={secondary}>{secondary}</span>}
        trailing={renderRoleControl(share)}
      />
    );
  };

  // Grant rows for the preview: the most recent first (by created_at when
  // the server sends it, else the server's order, newest last).
  const recentShares = useMemo(() => {
    const indexed = shares.map((share, index) => ({ share, index }));
    indexed.sort((x, y) => {
      const ax = x.share.created_at ?? '';
      const ay = y.share.created_at ?? '';
      if (ax !== ay) return ax < ay ? 1 : -1;
      return y.index - x.index;
    });
    return indexed.map((entry) => entry.share);
  }, [shares]);

  const isLongList = shares.length > SHORT_LIST_MAX;
  const previewShares = isLongList
    ? recentShares.slice(0, PREVIEW_COUNT)
    : shares;

  const teamGrantCount = shares.filter((s) => !s.target_user_id).length;
  const personGrantCount = shares.length - teamGrantCount;
  const editorGrantCount = shares.filter(
    (s) => s.access_level === 'editor',
  ).length;

  const shareLabel = (share: ResourceShare): string => {
    const name = share.team_name ?? teamName(share.team_id);
    return share.target_user_id
      ? `${memberDisplay(share.team_id, share.target_user_id)} ${share.target_user_id} ${name}`
      : name;
  };

  const filteredShares = shares.filter((share) => {
    if (accessFilter === 'teams' && share.target_user_id) return false;
    if (accessFilter === 'people' && !share.target_user_id) return false;
    if (accessFilter === 'editors' && share.access_level !== 'editor')
      return false;
    return matches(shareLabel(share), accessQuery);
  });

  const openAllStep = () => {
    setAccessQuery('');
    setAccessFilter('all');
    setStep('all');
  };

  // The caller's own row: the owner, or an editor the owner let share.
  const yourRole =
    settingsInfo?.access === 'editor'
      ? t('settings.teams.share.accessLevel.editor')
      : t('settings.teams.share.owner');

  const youRow = (
    <ListRow
      leading={
        <Avatar alt="" variant="primary" size="default" shape="circle">
          {initialOf(t('settings.teams.share.you'))}
        </Avatar>
      }
      title={t('settings.teams.share.you')}
      trailing={
        <span className="text-muted-foreground shrink-0 pr-3 text-sm">
          {yourRole}
        </span>
      }
    />
  );

  const errors = (
    <>
      {loadError && (
        <Alert variant="destructive">
          <CircleAlert className="size-4" aria-hidden="true" />
          <AlertDescription>
            {t('settings.teams.share.loadError')}
          </AlertDescription>
        </Alert>
      )}
      {actionError && (
        <Alert variant="destructive">
          <CircleAlert className="size-4" aria-hidden="true" />
          <AlertDescription>{actionError}</AlertDescription>
        </Alert>
      )}
    </>
  );

  const filterOptions: Array<{ value: AccessFilter; count: number }> = [
    { value: 'all', count: shares.length },
    { value: 'teams', count: teamGrantCount },
    { value: 'people', count: personGrantCount },
    { value: 'editors', count: editorGrantCount },
  ];

  const allStep = (
    <div className="flex flex-col gap-4">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="-ml-3 w-fit justify-start"
        onClick={() => setStep('main')}
      >
        <ArrowLeft aria-hidden />
        {t('settings.teams.share.back')}
      </Button>
      <div>
        <h2 className="text-foreground text-xl leading-tight font-semibold">
          {t('settings.teams.share.peopleWithAccess')}
        </h2>
        <p className="text-muted-foreground mt-2 text-sm">
          {t('settings.teams.share.allSummary', {
            interpolation: { escapeValue: false },
            name: resourceName ?? '',
            teams: formatCount(teamGrantCount),
            people: formatCount(personGrantCount),
          })}
        </p>
      </div>
      {errors}
      <SearchInput
        placeholder={t('settings.teams.share.searchAccess')}
        labelSurface="card"
        value={accessQuery}
        onChange={(e) => setAccessQuery(e.target.value)}
      />
      <div className="bg-muted w-fit max-w-full rounded-full p-1">
        <ToggleGroup
          type="single"
          size="xs"
          value={accessFilter}
          onValueChange={(value) =>
            value && setAccessFilter(value as AccessFilter)
          }
          aria-label={t('settings.teams.share.filterLabel')}
        >
          {filterOptions.map((option) => (
            <ToggleGroupItem key={option.value} value={option.value}>
              {t(`settings.teams.share.filter.${option.value}`)}{' '}
              {formatCount(option.count)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      <ListRows>
        {accessFilter === 'all' && !accessQuery.trim() && youRow}
        {filteredShares.map(renderShareRow)}
      </ListRows>
      {filteredShares.length === 0 && (
        <EmptyState
          size="xs"
          illustration="none"
          title={t('settings.teams.share.noMatches')}
        />
      )}
    </div>
  );

  const accessSettings = canManageSettings && (
    <section className="flex flex-col gap-3">
      {/* An inline disclosure: no Card around it draws section-toggle's
          ring, so the link button shows its own focus. */}
      <Button
        type="button"
        variant="link"
        size="sm"
        aria-expanded={settingsOpen}
        className="-ml-3 w-fit justify-start"
        onClick={() => setSettingsOpen((open) => !open)}
      >
        <ChevronRight
          aria-hidden="true"
          className={cn(
            'transition-transform duration-200',
            settingsOpen && 'rotate-90',
          )}
        />
        {t('settings.teams.accessSettings.title')}
      </Button>
      {settingsOpen && (
        <SettingRows>
          {settings.map((setting) => {
            const copy = settingCopy(
              t,
              resourceType,
              setting.key,
              credentials ? credentialMode : undefined,
            );
            const id = `share-setting-${setting.key}`;
            return (
              <SettingRow
                key={setting.key}
                htmlFor={id}
                label={copy.label}
                description={copy.description || undefined}
              >
                <Switch
                  id={id}
                  checked={setting.value}
                  disabled={savingSettings.has(setting.key)}
                  onCheckedChange={(value) => toggleSetting(setting.key, value)}
                />
              </SettingRow>
            );
          })}
        </SettingRows>
      )}
    </section>
  );

  const mainStep = (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <p className="text-muted-foreground text-sm">
          {t('settings.teams.share.subtitle')}
        </p>
        {errors}
      </div>

      {teams.length === 0 ? (
        <p className="text-sm">{t('settings.teams.share.noTeams')}</p>
      ) : (
        <>
          {credentials && (
            <section className="flex flex-col gap-3">
              <SectionHeader
                as="h3"
                size="xs"
                title={t('settings.connectors.share.heading')}
              />
              {/* A compact one-of-two; the line under it says what the
                  choice means. */}
              <div className="bg-muted self-start rounded-full p-1">
                <ToggleGroup
                  type="single"
                  size="xs"
                  value={credentialMode}
                  aria-label={t('settings.connectors.share.heading')}
                  onValueChange={(value) =>
                    value && changeCredentialMode(value as 'owner' | 'member')
                  }
                >
                  {(['owner', 'member'] as const).map((mode) => (
                    <ToggleGroupItem
                      key={mode}
                      value={mode}
                      disabled={
                        !!credentials.readOnly ||
                        (!!credentials.forcedMode &&
                          credentials.forcedMode !== mode)
                      }
                    >
                      {mode === 'owner' ? <UserRound /> : <UsersRound />}
                      {/* "Your account" to the owner; an editor sees the
                          owner's, like the agent's "What this agent uses". */}
                      {t(
                        mode === 'owner' && credentials.readOnly
                          ? 'settings.connectors.sharing.ownerShortShared'
                          : `settings.connectors.sharing.${mode}Short`,
                      )}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </div>
              {credentials.forcedMode ? (
                <p className="text-muted-foreground text-xs">
                  {t('settings.connectors.share.forced')}
                </p>
              ) : (
                credentials.readOnly && (
                  <p className="text-muted-foreground text-xs">
                    {t('settings.connectors.share.ownerChooses')}
                  </p>
                )
              )}
              {credentialMode === 'owner' ? (
                // A tool that can act asks for the confirmation below, which
                // says the same; one that only reads gets a plain line.
                needsWriteConfirm ? null : (
                  <p className="text-muted-foreground text-sm">
                    {credentials.readOnly
                      ? t('settings.connectors.share.ownerWarningShared', {
                          name: credentials.connectorName,
                          interpolation: { escapeValue: false },
                        })
                      : t('settings.connectors.share.ownerWarning', {
                          account: credentials.account,
                          name: credentials.connectorName,
                          interpolation: { escapeValue: false },
                        })}
                  </p>
                )
              ) : (
                <p className="text-muted-foreground text-sm">
                  {t('settings.connectors.share.memberNote', {
                    name: credentials.connectorName,
                    interpolation: { escapeValue: false },
                  })}
                </p>
              )}
              {needsWriteConfirm && (
                <div className="flex items-start gap-2">
                  <Checkbox
                    id="share-confirm-writes"
                    checked={writesConfirmed}
                    onCheckedChange={(checked) =>
                      setWritesConfirmed(checked === true)
                    }
                  />
                  <Label
                    htmlFor="share-confirm-writes"
                    className="text-sm font-normal"
                  >
                    {credentials.readOnly
                      ? t('settings.connectors.share.confirmWriteShared', {
                          name: credentials.connectorName,
                          interpolation: { escapeValue: false },
                        })
                      : t('settings.connectors.share.confirmWrite')}
                  </Label>
                </div>
              )}
            </section>
          )}

          <div>
            {/* Add row: type-ahead combobox + access level select. */}
            <div className="flex items-center gap-2">
              <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
                <PopoverTrigger asChild>
                  <Button
                    type="button"
                    variant="combobox"
                    role="combobox"
                    aria-expanded={pickerOpen}
                    disabled={
                      committing || (needsWriteConfirm && !writesConfirmed)
                    }
                    data-placeholder=""
                    className="min-w-0 flex-1 justify-start"
                  >
                    <span className="truncate">
                      {t('settings.teams.share.addPlaceholder')}
                    </span>
                  </Button>
                </PopoverTrigger>
                <PopoverContent
                  className="w-[min(22rem,calc(100vw-2rem))] p-0"
                  align="start"
                >
                  <Command shouldFilter={false}>
                    <CommandInput
                      placeholder={t('settings.teams.share.searchPlaceholder')}
                      value={query}
                      onValueChange={setQuery}
                    />
                    <CommandList>
                      {!hasSuggestions && (
                        <CommandEmpty>
                          {t('settings.teams.share.noMatches')}
                        </CommandEmpty>
                      )}
                      {teamSuggestions.length > 0 && (
                        <CommandGroup
                          heading={t('settings.teams.share.teamsGroup')}
                        >
                          {teamSuggestions.map((suggestion) => (
                            <CommandItem
                              key={suggestion.key}
                              value={suggestion.key}
                              onSelect={() => commitSuggestion(suggestion)}
                            >
                              <Avatar
                                alt=""
                                variant="primary"
                                size="xs"
                                shape="square"
                              >
                                {initialOf(suggestion.teamName)}
                              </Avatar>
                              <span className="min-w-0 flex-1 truncate">
                                {suggestion.teamName}
                              </span>
                            </CommandItem>
                          ))}
                        </CommandGroup>
                      )}
                      {memberSuggestions.length > 0 && (
                        <CommandGroup
                          heading={t('settings.teams.share.peopleGroup')}
                        >
                          {memberSuggestions.map((suggestion) =>
                            suggestion.kind === 'member' ? (
                              <CommandItem
                                key={suggestion.key}
                                value={`${suggestion.key} ${suggestion.label} ${suggestion.teamName}`}
                                onSelect={() => commitSuggestion(suggestion)}
                              >
                                <Avatar
                                  alt=""
                                  variant="primary"
                                  size="xs"
                                  shape="circle"
                                >
                                  {initialOf(suggestion.label)}
                                </Avatar>
                                <span className="min-w-0 flex-1 truncate">
                                  {suggestion.label}
                                  <span className="text-muted-foreground">
                                    {' · '}
                                    {suggestion.teamName}
                                  </span>
                                </span>
                              </CommandItem>
                            ) : null,
                          )}
                        </CommandGroup>
                      )}
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>

              <Select
                value={accessLevel}
                disabled={committing}
                onValueChange={(value) => setAccessLevel(value as AccessLevel)}
              >
                <SelectTrigger
                  className="w-28 shrink-0"
                  aria-label={t('settings.teams.share.access')}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="viewer">
                    {t('settings.teams.share.accessLevel.viewer')}
                  </SelectItem>
                  <SelectItem value="editor">
                    {t('settings.teams.share.accessLevel.editor')}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <p
              data-testid="share-editor-hint"
              className="text-muted-foreground mt-1.5 text-xs"
            >
              {editorHint(t, resourceType, settings, !!credentials)}
            </p>
          </div>

          {/* People with access. */}
          <section className="flex flex-col gap-1">
            <SectionHeader
              as="h3"
              size="xs"
              title={t('settings.teams.share.peopleWithAccess')}
              actions={
                isLongList && (
                  <Button
                    type="button"
                    variant="link"
                    size="inline"
                    onClick={openAllStep}
                  >
                    {t('settings.teams.share.showAll', {
                      formatted: formatCount(shares.length),
                    })}
                    <ArrowRight className="size-3" aria-hidden />
                  </Button>
                )
              }
            />
            <ListRows>
              {youRow}
              {previewShares.map(renderShareRow)}
            </ListRows>
            {isLongList && (
              <p className="text-muted-foreground px-4 text-xs">
                {t('settings.teams.share.andMore', {
                  count: shares.length - previewShares.length,
                  formatted: formatCount(shares.length - previewShares.length),
                })}
              </p>
            )}
          </section>
        </>
      )}

      {/* Whose access each of the agent's tools, sources and prompt runs
          with, for the people it is shared with (owners and editors only:
          viewers never open this dialog). */}
      {resourceType === 'agent' && (
        <AgentUsesSection agentId={resourceId} readerId={currentUserId} />
      )}

      {accessSettings}
    </div>
  );

  return (
    <Modal
      open
      onOpenChange={(open) => {
        // Don't allow ESC / overlay close while a request is in flight.
        if (!open && !inFlight) onClose();
      }}
      isPerformingTask={inFlight}
      // The "all" step draws its own heading under a Back button (Upload's
      // step pattern); the dialog keeps an accessible title either way.
      title={
        step === 'all' ? t('settings.teams.share.peopleWithAccess') : title
      }
      hideTitle={step === 'all'}
      size="md"
      footer={
        <Button size="lg" shape="pill" disabled={inFlight} onClick={onClose}>
          {t('settings.teams.share.done')}
        </Button>
      }
    >
      {step === 'all' ? allStep : mainStep}
    </Modal>
  );
}
