import { Check, ChevronDown } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import teamsService, {
  AccessLevel,
  ResourceShare,
  ResourceType,
  TeamMember,
} from '../api/services/teamsService';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '../components/ui/command';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { Modal } from '../components/ui/modal';
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
import { selectToken } from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import { decodeJwtPayload } from '../utils/jwtUtils';
import { cn } from '@/lib/utils';
import { loadTeams, selectTeams } from './teamsSlice';

type Props = {
  resourceType: ResourceType;
  resourceId: string;
  resourceName?: string;
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
  }, [resourceType, resourceId]);

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
    } catch {
      setActionError(t('settings.teams.share.shareError'));
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
    } catch {
      setActionError(t('settings.teams.share.shareError'));
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
    } catch {
      setActionError(t('settings.teams.share.unshareError'));
    } finally {
      setRowBusy(key, false);
      await refreshShares();
    }
  };

  const title = resourceName
    ? t('settings.teams.share.titleNamed', { name: resourceName })
    : t('settings.teams.share.titleGeneric', {
        type: t(`settings.teams.resourceType.${resourceType}`).toLowerCase(),
      });

  const renderRoleControl = (share: ResourceShare) => {
    const key = shareKey(share);
    const rowBusy = busyKeys.has(key);
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            disabled={rowBusy}
            className="shrink-0 gap-1 px-2 font-normal"
            aria-label={t('settings.teams.share.access')}
          >
            {t(`settings.teams.share.accessLevel.${share.access_level}`)}
            <ChevronDown className="size-4 opacity-50" />
          </Button>
        </DropdownMenuTrigger>
        {/* z-200 keeps the menu above Modal (z-50), matching the combobox/access controls. */}
        <DropdownMenuContent align="end" className="z-200 min-w-40">
          {(['viewer', 'editor'] as AccessLevel[]).map((level) => (
            <DropdownMenuItem
              key={level}
              onSelect={() => changeAccess(share, level)}
            >
              <Check
                className={cn(
                  'size-4 shrink-0',
                  share.access_level === level ? 'opacity-100' : 'opacity-0',
                )}
              />
              {t(`settings.teams.share.accessLevel.${level}`)}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => removeAccess(share)}
          >
            {t('settings.teams.share.removeAccess')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
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
      : t('settings.teams.share.viaTeam', { team: name });
    return (
      <li key={shareKey(share)} className="flex items-center gap-3 py-2">
        <Avatar
          alt=""
          className={cn(
            'bg-primary/10 text-primary dark:bg-primary/20 flex size-9 items-center justify-center text-sm font-medium',
            isTeam ? 'rounded-md' : 'rounded-full',
          )}
        >
          {initialOf(primary)}
        </Avatar>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={primary}>
            {primary}
          </p>
          <p
            className="text-muted-foreground truncate text-xs"
            title={secondary}
          >
            {secondary}
          </p>
        </div>
        {renderRoleControl(share)}
      </li>
    );
  };

  return (
    <Modal
      open
      onOpenChange={(open) => {
        // Don't allow ESC / overlay close while a request is in flight.
        if (!open && !inFlight) onClose();
      }}
      isPerformingTask={inFlight}
      title={title}
      size="md"
      footer={
        <Button variant="outline" disabled={inFlight} onClick={onClose}>
          {t('settings.teams.share.done')}
        </Button>
      }
    >
      <p className="text-muted-foreground mt-1 text-sm">
        {t('settings.teams.share.subtitle')}
      </p>

      {loadError && (
        <p className="text-destructive mt-3 text-sm" role="alert">
          {t('settings.teams.share.loadError')}
        </p>
      )}
      {actionError && (
        <p className="text-destructive mt-3 text-sm" role="alert">
          {actionError}
        </p>
      )}

      {teams.length === 0 ? (
        <p className="mt-6 text-sm">{t('settings.teams.share.noTeams')}</p>
      ) : (
        <>
          {/* Add row: type-ahead combobox + access level select. */}
          <div className="mt-4 flex items-center gap-2">
            <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
              <PopoverTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  role="combobox"
                  aria-expanded={pickerOpen}
                  disabled={committing}
                  className="text-muted-foreground h-9 min-w-0 flex-1 justify-start gap-2 px-3 font-normal"
                >
                  <span className="truncate">
                    {t('settings.teams.share.addPlaceholder')}
                  </span>
                </Button>
              </PopoverTrigger>
              {/* z-200 keeps the popover above Modal (z-50). */}
              <PopoverContent
                className="z-200 w-[min(22rem,calc(100vw-2rem))] p-0"
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
                            className="gap-3"
                          >
                            <Avatar
                              alt=""
                              className="bg-primary/10 text-primary dark:bg-primary/20 flex size-7 items-center justify-center rounded-md text-xs font-medium"
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
                              className="gap-3"
                            >
                              <Avatar
                                alt=""
                                className="bg-primary/10 text-primary dark:bg-primary/20 flex size-7 items-center justify-center rounded-full text-xs font-medium"
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
                className="h-9 w-28 shrink-0"
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

          {/* People with access. */}
          <section className="mt-6">
            <h3 className="text-sm font-medium">
              {t('settings.teams.share.peopleWithAccess')}
            </h3>
            <ul className="mt-1 max-h-72 overflow-auto">
              {/* Owner — pinned, non-interactive. */}
              <li className="flex items-center gap-3 py-2">
                <Avatar
                  alt=""
                  className="bg-primary/10 text-primary dark:bg-primary/20 flex size-9 items-center justify-center rounded-full text-sm font-medium"
                >
                  {initialOf(t('settings.teams.share.you'))}
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    {t('settings.teams.share.you')}
                  </p>
                </div>
                <span className="text-muted-foreground shrink-0 pr-3 text-sm">
                  {t('settings.teams.share.owner')}
                </span>
              </li>
              {shares.map(renderShareRow)}
            </ul>
          </section>
        </>
      )}
    </Modal>
  );
}
