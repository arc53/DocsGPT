import type { TFunction } from 'i18next';
import { Bot, FileText, MessageSquare, Wrench } from 'lucide-react';
import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { agentEditPath } from '../../agents/paths';
import teamsService, {
  isOutsidePolicy,
  type OutsideShare,
  type PublishedAgent,
  type ResourceType,
  type TeamGrant,
  teamErrorMessage,
  type TeamOutside,
  type TeamRole,
} from '../../api/services/teamsService';
import SkeletonLoader from '../../components/SkeletonLoader';
import { Alert, AlertDescription } from '../../components/ui/alert';
import { Avatar } from '../../components/ui/avatar';
import { Button } from '../../components/ui/button';
import { Card } from '../../components/ui/card';
import { EmptyState } from '../../components/ui/empty-state';
import { ListRow, ListRows } from '../../components/ui/list-row';
import { SectionHeader } from '../../components/ui/section-header';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { pauseReasonText, payerOf } from '../../payer/pauseReason';
import {
  OUTSIDE_ACCESS_KINDS,
  type OutsideAccessKind,
  type PausedFor,
} from '../../payer/types';
import { selectToken } from '../../preferences/preferenceSlice';
import { AppDispatch } from '../../store';
import {
  formatCount,
  formatDateOnly,
  headingLocale,
} from '../../utils/dateTimeUtils';
import { readerIdFromToken } from '../../utils/personLabel';
import {
  roleAtLeast,
  selectWorkspaceId,
  switchWorkspace,
} from '../../workspace/workspaceSlice';
import type { Team } from '../teamsSlice';
import { grantResourceName, truncateSub } from './teamGrants';

const K = 'settings.teams.outside';
const noEscape = { interpolation: { escapeValue: false } };

const RESOURCE_TYPES: ReadonlyArray<ResourceType> = [
  'agent',
  'source',
  'prompt',
  'tool',
];

const ACCESS_KEYS: Record<OutsideAccessKind, string> = {
  api_key: 'payer.common.access.apiKey',
  public_link: 'payer.common.access.publicLink',
  webhook: 'payer.common.access.webhook',
};

/** The kind's tile in a row. */
function TypeTile({ type }: { type: string }) {
  const props = { className: 'size-4', 'aria-hidden': true } as const;
  let icon: ReactNode;
  switch (type) {
    case 'agent':
      icon = <Bot {...props} />;
      break;
    case 'prompt':
      icon = <MessageSquare {...props} />;
      break;
    case 'tool':
      icon = <Wrench {...props} />;
      break;
    default:
      icon = <FileText {...props} />;
  }
  return (
    <Avatar aria-hidden="true" size="sm" shape="square" variant="icon">
      {icon}
    </Avatar>
  );
}

/** A row's muted meta line, with an optional warning line under it. */
function RowDescription({ meta, warning }: { meta: string; warning?: string }) {
  return (
    <>
      <span className="block">{meta}</span>
      {warning ? <span className="text-warning block">{warning}</span> : null}
    </>
  );
}

/**
 * What ending a share stops in the receiving team, for its confirm: an
 * agent's chats, or the receiving team's agents that use the item.
 *
 * Args:
 *   t: The translate function.
 *   type: The shared item's kind.
 *   team: The receiving team's name.
 *   used: How many of its agents use it; null when that can't be read.
 *   names: Their names, when known (the receiving side reads them).
 *
 * Returns:
 *   One sentence.
 */
export function shareStopsText(
  t: TFunction,
  type: ResourceType,
  team: string,
  used: number | null,
  names?: string[],
): string {
  if (type === 'agent') return t(`${K}.stops.agent`, { team, ...noEscape });
  if (names && names.length > 0)
    return t(`${K}.stops.agents`, {
      team,
      names: names.join(', '),
      ...noEscape,
    });
  if (used === null) return t(`${K}.stops.unknown`, { team, ...noEscape });
  if (used === 0) return t(`${K}.stops.none`, { team, ...noEscape });
  return t(`${K}.stops.usedBy`, {
    team,
    count: used,
    formatted: formatCount(used),
    ...noEscape,
  });
}

type OutsideSharesSectionProps = {
  team: Team;
  /** The caller's role in the team; every member reads the section. */
  role: TeamRole;
};

/**
 * "Shared outside the team": the team's items shared with other teams, each
 * with who shared it and when, paused while the team is locked, and "Stop
 * sharing" for whoever the server lets revoke it (its confirm says what
 * stops in the receiving team); then the team's agents reachable from
 * outside, read-only, opened by Editors and up to change their access.
 */
export default function OutsideSharesSection({
  team,
  role,
}: OutsideSharesSectionProps) {
  const { t, i18n } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const workspaceId = useSelector(selectWorkspaceId);
  const language = i18n?.language;
  const me = readerIdFromToken(token);

  const [outside, setOutside] = useState<TeamOutside | null>(null);
  const [status, setStatus] = useState<'loading' | 'error' | 'ready'>(
    'loading',
  );
  const [toRevoke, setToRevoke] = useState<OutsideShare | null>(null);

  // Only the newest read applies: one for the team you left answering late
  // would show that team's shares on this one's page.
  const loadSeq = useRef(0);
  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    try {
      const res = await teamsService.getOutside(team.id, token);
      if (seq !== loadSeq.current) return;
      setOutside(res);
      setStatus('ready');
    } catch {
      if (seq !== loadSeq.current) return;
      setStatus('error');
    }
  }, [team.id, token]);

  useEffect(() => {
    setStatus('loading');
    setOutside(null);
    load();
  }, [load]);

  const typeLabel = (type: string) =>
    RESOURCE_TYPES.includes(type as ResourceType)
      ? t(`settings.teams.resourceType.${type}`)
      : type;
  const teamName = (name: string | null, id: string) =>
    name?.trim() || truncateSub(id);
  const shareName = (share: OutsideShare) =>
    share.resource_name?.trim() || truncateSub(share.resource_id);

  const accessList = new Intl.ListFormat(
    headingLocale(language === 'jp' ? 'ja' : language),
    { type: 'conjunction' },
  );

  // The team's agents open in the team: move there first when elsewhere.
  const openAgent = (agentId: string) => {
    navigate(agentEditPath(agentId));
    if (workspaceId !== team.id) dispatch(switchWorkspace(team.id));
  };

  const revoke = async (share: OutsideShare) => {
    await teamsService.unshareTeamItem(
      share.team_id,
      { resource_type: share.resource_type, resource_id: share.resource_id },
      token,
    );
    await load();
  };

  const shareRow = (share: OutsideShare) => {
    const name = shareName(share);
    const receiving = teamName(share.name, share.team_id);
    const meta = [
      typeLabel(share.resource_type),
      t(`${K}.shares.with`, { team: receiving, ...noEscape }),
      share.shared_by
        ? t(`${K}.shares.by`, {
            name: share.shared_by.label?.trim() || share.shared_by.user_id,
            ...noEscape,
          })
        : null,
      share.created_at ? formatDateOnly(share.created_at) : null,
    ]
      .filter(Boolean)
      .join(' · ');
    return (
      <ListRow
        key={share.id}
        wrap
        data-testid="outside-share-row"
        leading={<TypeTile type={share.resource_type} />}
        title={name}
        description={
          <RowDescription
            meta={meta}
            warning={
              share.paused_reason === 'team_locked'
                ? t(`${K}.paused`, { team: team.name, ...noEscape })
                : undefined
            }
          />
        }
        trailing={
          share.can_revoke ? (
            <Button
              variant="ghost-destructive"
              size="sm"
              className="shrink-0"
              aria-label={t(`${K}.shares.revokeLabel`, {
                name,
                team: receiving,
                ...noEscape,
              })}
              onClick={() => setToRevoke(share)}
            >
              {t(`${K}.shares.revoke`)}
            </Button>
          ) : null
        }
      />
    );
  };

  const publishedRow = (agent: PublishedAgent) => {
    const name = agent.name?.trim() || truncateSub(agent.agent_id);
    const access = agent.outside_access;
    const on = accessList.format(
      OUTSIDE_ACCESS_KINDS.filter((kind) => access?.[kind]).map((kind) =>
        t(ACCESS_KEYS[kind]),
      ),
    );
    const payer = payerOf(access?.paid_by, me);
    const reason = pauseReasonText(
      t,
      (access?.paused_for as PausedFor | null | undefined) ?? null,
      payer.label,
      team.name,
      { you: payer.you, language },
    );
    return (
      <ListRow
        key={agent.agent_id}
        wrap
        data-testid="outside-published-row"
        leading={<TypeTile type="agent" />}
        title={name}
        description={
          <RowDescription
            meta={
              on
                ? t('payer.team.paused.access', { access: on, ...noEscape })
                : t('payer.team.paused.accessAll')
            }
            warning={reason || undefined}
          />
        }
        trailing={
          roleAtLeast(role, 'editor') ? (
            <Button
              variant="outline"
              size="sm"
              className="shrink-0"
              aria-label={t(`${K}.published.openLabel`, {
                name,
                ...noEscape,
              })}
              onClick={() => openAgent(agent.agent_id)}
            >
              {t(`${K}.published.open`)}
            </Button>
          ) : null
        }
      />
    );
  };

  const shares = outside?.shares ?? [];
  const published = outside?.published ?? [];
  const policy = isOutsidePolicy(outside?.outside_policy)
    ? outside.outside_policy
    : isOutsidePolicy(team.outside_policy)
      ? team.outside_policy
      : null;

  let body: ReactNode;
  if (status === 'loading') body = <SkeletonLoader component="default" />;
  else if (status === 'error')
    body = (
      <EmptyState
        size="sm"
        tone="destructive"
        illustration="none"
        title={t(`${K}.shares.loadError`)}
        onRetry={() => {
          setStatus('loading');
          load();
        }}
      />
    );
  else if (shares.length === 0 && published.length === 0)
    body = (
      <EmptyState
        size="xs"
        illustration="none"
        title={t(`${K}.shares.empty`)}
      />
    );
  else
    body = (
      <>
        {shares.length > 0 && (
          <Card variant="subtle" padding="none" className="overflow-hidden">
            <ListRows>{shares.map(shareRow)}</ListRows>
          </Card>
        )}
        {published.length > 0 && (
          <div data-testid="outside-published" className="flex flex-col gap-3">
            <SectionHeader
              as="h5"
              size="xs"
              title={t(`${K}.published.title`)}
              count={published.length}
            />
            <Card variant="subtle" padding="none" className="overflow-hidden">
              <ListRows>{published.map(publishedRow)}</ListRows>
            </Card>
          </div>
        )}
      </>
    );

  return (
    <section data-testid="outside-shares" className="flex flex-col gap-3">
      <SectionHeader
        as="h4"
        size="sm"
        title={t(`${K}.shares.title`)}
        count={
          status === 'ready' ? shares.length + published.length : undefined
        }
      />
      <p className="text-muted-foreground text-sm">
        {t(`${K}.shares.intro`)}
        {policy ? (
          <>
            {' '}
            {t(`${K}.shares.policy`, {
              policy: t(`${K}.policy.${policy}`),
              ...noEscape,
            })}
          </>
        ) : null}
      </p>
      {policy === 'locked' &&
        status === 'ready' &&
        shares.length + published.length > 0 && (
          <Alert variant="info">
            <AlertDescription>
              {t(`${K}.shares.locked`, { team: team.name, ...noEscape })}
            </AlertDescription>
          </Alert>
        )}
      {body}
      {toRevoke && (
        <ConfirmationModal
          message={t(`${K}.shares.revokeTitle`, {
            name: shareName(toRevoke),
            team: teamName(toRevoke.name, toRevoke.team_id),
            ...noEscape,
          })}
          description={shareStopsText(
            t,
            toRevoke.resource_type,
            teamName(toRevoke.name, toRevoke.team_id),
            toRevoke.used_by_count,
          )}
          modalState="ACTIVE"
          setModalState={(state) => state === 'INACTIVE' && setToRevoke(null)}
          submitLabel={t(`${K}.shares.revoke`)}
          handleSubmit={() => revoke(toRevoke)}
          error={(e) => teamErrorMessage(t, e, t(`${K}.shares.revokeError`))}
          variant="destructive"
        />
      )}
    </section>
  );
}

type SharedFromTeamsSectionProps = {
  team: Team;
  /** The team's grants rows that came from other teams (`origin: team_shared`). */
  grants: TeamGrant[];
  /** Reads the team's grants again after a change. */
  onGrantsChanged: () => Promise<void> | void;
};

/**
 * "Shared from other teams": items other teams share with this one, each
 * named with the team it comes from, paused while that team is locked, and
 * "Remove from this team" for the team's Admins and Owner (its confirm
 * names this team's agents that stop using it). Nothing when there are none.
 */
export function SharedFromTeamsSection({
  team,
  grants,
  onGrantsChanged,
}: SharedFromTeamsSectionProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [toRemove, setToRemove] = useState<TeamGrant | null>(null);

  if (grants.length === 0) return null;

  const typeLabel = (type: string) =>
    RESOURCE_TYPES.includes(type as ResourceType)
      ? t(`settings.teams.resourceType.${type}`)
      : type;
  const fromName = (g: TeamGrant) =>
    g.shared_from?.name?.trim() || t(`${K}.fromAnotherTeam`);
  const fromLine = (g: TeamGrant) =>
    g.shared_from?.name?.trim()
      ? t('workspace.page.sharedFromTeams.from', {
          team: g.shared_from.name.trim(),
          ...noEscape,
        })
      : t(`${K}.fromAnotherTeam`);

  const remove = async (g: TeamGrant) => {
    try {
      await teamsService.unshareTeamItem(
        team.id,
        { resource_type: g.resource_type, resource_id: g.resource_id },
        token,
      );
    } finally {
      await onGrantsChanged();
    }
  };

  const removeDescription = (g: TeamGrant): string => {
    const names = (g.used_by ?? [])
      .map((agent) => agent.name?.trim() || truncateSub(agent.id))
      .filter(Boolean);
    const stops = shareStopsText(
      t,
      g.resource_type,
      team.name,
      g.used_by ? g.used_by.length : null,
      names,
    );
    const again = g.shared_from?.name?.trim()
      ? t(`${K}.fromTeams.removeAgain`, {
          from: g.shared_from.name.trim(),
          ...noEscape,
        })
      : '';
    return again ? `${stops} ${again}` : stops;
  };

  return (
    <section data-testid="shared-from-teams" className="flex flex-col gap-3">
      <SectionHeader
        as="h4"
        size="sm"
        title={t(`${K}.fromTeams.title`)}
        count={grants.length}
      />
      <p className="text-muted-foreground text-sm">
        {t(`${K}.fromTeams.intro`)}
      </p>
      <Card variant="subtle" padding="none" className="overflow-hidden">
        <ListRows>
          {grants.map((g) => {
            const name = grantResourceName(g);
            return (
              <ListRow
                key={g.id ?? `${g.resource_type}:${g.resource_id}`}
                wrap
                data-testid="shared-from-team-row"
                leading={<TypeTile type={g.resource_type} />}
                title={name}
                description={
                  <RowDescription
                    meta={`${typeLabel(g.resource_type)} · ${fromLine(g)}`}
                    warning={
                      g.paused_reason === 'team_locked'
                        ? t(`${K}.paused`, {
                            team: fromName(g),
                            ...noEscape,
                          })
                        : undefined
                    }
                  />
                }
                trailing={
                  g.can_revoke ? (
                    <Button
                      variant="ghost-destructive"
                      size="sm"
                      className="shrink-0"
                      aria-label={t(`${K}.fromTeams.removeLabel`, {
                        name,
                        ...noEscape,
                      })}
                      onClick={() => setToRemove(g)}
                    >
                      {t(`${K}.fromTeams.remove`)}
                    </Button>
                  ) : null
                }
              />
            );
          })}
        </ListRows>
      </Card>
      {toRemove && (
        <ConfirmationModal
          message={t(`${K}.fromTeams.removeTitle`, {
            name: grantResourceName(toRemove),
            team: team.name,
            ...noEscape,
          })}
          description={removeDescription(toRemove)}
          modalState="ACTIVE"
          setModalState={(state) => state === 'INACTIVE' && setToRemove(null)}
          submitLabel={t(`${K}.fromTeams.remove`)}
          handleSubmit={() => remove(toRemove)}
          error={(e) => teamErrorMessage(t, e, t(`${K}.fromTeams.removeError`))}
          variant="destructive"
        />
      )}
    </section>
  );
}
