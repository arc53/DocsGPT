import { Trash2 } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import { rememberOutsideAccess } from '../agents/OwnerInactiveNotice';
import payerService from '../api/services/payerService';
import teamsService, {
  teamErrorMessage,
  type OutsideShare,
  type ResourceSharesResponse,
  type ResourceType,
} from '../api/services/teamsService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import { Combobox } from '../components/ui/combobox';
import { IconButton } from '../components/ui/icon-button';
import { ListRow, ListRows } from '../components/ui/list-row';
import { SectionHeader } from '../components/ui/section-header';
import ConfirmationModal from '../modals/ConfirmationModal';
import type { ActiveState } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { pauseReasonText } from '../payer/pauseReason';
import TakeOverModal from '../payer/TakeOverModal';
import type { OutsideAccessKind, PersonRef } from '../payer/types';
import { selectToken } from '../preferences/preferenceSlice';
import { formatCount } from '../utils/dateTimeUtils';
import { roleAtLeast } from '../workspace/workspaceSlice';
import { shareWarningLines } from './accessSettings';

/**
 * `GET /api/resource_shares` for an item a team owns, or one another team
 * shares with the caller's (`origin: "team_shared"`): no per-item people,
 * but the team it lives in (see `ResourceSharesResponse`).
 */
export type TeamItemShares = Omit<
  ResourceSharesResponse,
  'shares' | 'workspace'
> & {
  shares?: unknown[];
  workspace: NonNullable<ResourceSharesResponse['workspace']>;
};

/** Whether a `resource_shares` answer is a team item's. */
export const isTeamItemShares = (body: unknown): body is TeamItemShares =>
  !!body &&
  typeof body === 'object' &&
  (body as { workspace?: { kind?: unknown } }).workspace?.kind === 'team';

type Props = {
  resourceType: ResourceType;
  /** The item's id: an agent's outside access is taken over by it. */
  resourceId?: string;
  /** The item's name, for the Take over confirm. */
  resourceName?: string;
  info: TeamItemShares;
  /** The caller's user id, to say "you" for the payer. */
  currentUserId?: string;
  /** Before Manage members navigates away, so the dialog can close. */
  onNavigate?: () => void;
  /** After a share with another team was added or stopped: reload `info`. */
  onChanged?: () => unknown;
};

const initialOf = (label: string): string => {
  const trimmed = label.trim();
  return trimmed ? trimmed[0].toUpperCase() : '?';
};

/**
 * The share dialog's body for an item a team owns: access follows team
 * membership, so it shows one row for everyone in the team (with Manage
 * members for the team's Admins), the caller's own row with their team role,
 * the other teams it is shared with (see `OtherTeams`), and for an agent what
 * reaches it from outside the team (public link, API key and widget,
 * webhook), each On or Off and who pays for it, or why it is paused. Those
 * are changed on the agent's own page, by an Admin; an Admin who doesn't pay
 * for them can take them over here. An item another team shares with the
 * caller's only says where it comes from.
 */
export default function TeamItemAccess({
  resourceType,
  resourceId,
  resourceName,
  info,
  currentUserId,
  onNavigate,
  onChanged,
}: Props) {
  const { t, i18n } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const noEscape = { interpolation: { escapeValue: false } };
  const team = info.workspace.name ?? '';
  const role = info.team_role ?? 'viewer';
  const given = resourceType === 'agent' ? info.outside_access : null;
  // The block as last answered: the dialog's read, then a Take over's.
  const [outside, setOutside] = useState(given ?? null);
  useEffect(() => setOutside(given ?? null), [given]);
  const [takeOverState, setTakeOverState] = useState<ActiveState>('INACTIVE');

  const payer = (person: PersonRef | null | undefined): string | null => {
    if (!person) return null;
    if (currentUserId && person.user_id === currentUserId)
      return t('workspace.share.payerYou');
    return person.label || null;
  };
  const paused = outside?.paused_for ?? null;
  const pausedText = (): string => {
    const reason = pauseReasonText(t, paused, outside?.paid_by?.label, team, {
      you: !!currentUserId && outside?.paid_by?.user_id === currentUserId,
      language: i18n?.language,
    });
    return reason
      ? t('payer.access.pausedBecause', { reason, ...noEscape })
      : t('payer.access.paused');
  };
  const state = (on: boolean): string => {
    if (!on) return t('workspace.share.off');
    const name = payer(outside?.paid_by);
    return name
      ? t('workspace.share.onPaidBy', { name, ...noEscape })
      : t('workspace.share.on');
  };
  const canTakeOver = !!outside?.can_take_over && !!resourceId;

  const takeOver = async () => {
    if (!resourceId) return;
    const result = await payerService.takeOverOutsideAccess(resourceId, token);
    setOutside(result.outside_access);
    rememberOutsideAccess(resourceId, result.outside_access);
    dispatch(
      showActionToast({
        variant: 'success',
        message: t('payer.access.takenOver'),
      }),
    );
  };

  const outsideRows: { key: string; kind: OutsideAccessKind; on: boolean }[] =
    outside
      ? [
          { key: 'publicLink', kind: 'public_link', on: !!outside.public_link },
          { key: 'apiKey', kind: 'api_key', on: !!outside.api_key },
          { key: 'webhook', kind: 'webhook', on: !!outside.webhook },
        ]
      : [];

  if (info.origin === 'team_shared') {
    const owner = info.shared_from?.name;
    return (
      <div className="flex flex-col gap-4">
        <p className="text-muted-foreground text-sm">
          {owner
            ? t('workspace.share.outside.received.body', {
                owner,
                team,
                ...noEscape,
              })
            : t('workspace.share.outside.received.bodyNoOwner', {
                team,
                ...noEscape,
              })}
        </p>
        <Alert variant="info" role="note">
          <AlertDescription>
            {t('workspace.share.outside.received.note')}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <p className="text-muted-foreground text-sm">
        {t('workspace.share.belongsTo', { team, ...noEscape })}
      </p>
      <section className="flex flex-col gap-1">
        <SectionHeader as="h3" size="xs" title={t('workspace.share.access')} />
        <ListRows>
          <ListRow
            leading={
              <Avatar alt="" variant="primary" size="default" shape="square">
                {initialOf(team)}
              </Avatar>
            }
            title={t('workspace.share.everyoneInTeam', { team, ...noEscape })}
            description={t('workspace.share.members', {
              count: info.members_count ?? 0,
            })}
            trailing={
              roleAtLeast(role, 'admin') ? (
                <Button asChild variant="link" size="inline">
                  <Link
                    to={`/teams/${encodeURIComponent(info.workspace.team_id)}`}
                    onClick={onNavigate}
                  >
                    {t('workspace.share.manageMembers')}
                  </Link>
                </Button>
              ) : null
            }
          />
          <ListRow
            leading={
              <Avatar alt="" variant="primary" size="default" shape="circle">
                {initialOf(t('workspace.common.you'))}
              </Avatar>
            }
            title={t('workspace.common.you')}
            description={t('workspace.share.yourRole', {
              role: t(`workspace.common.roles.${role}`),
              team,
              ...noEscape,
            })}
            trailing={
              <span className="text-muted-foreground shrink-0 pr-3 text-sm">
                {t('workspace.share.fromTeam')}
              </span>
            }
          />
        </ListRows>
      </section>
      <OtherTeams
        resourceType={resourceType}
        resourceId={resourceId}
        info={info}
        currentUserId={currentUserId}
        onChanged={onChanged}
      />
      {outside ? (
        <section className="flex flex-col gap-1">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('workspace.share.outside.title')}
          />
          <ListRows>
            {outsideRows.map((row) => (
              <ListRow
                key={row.key}
                // A paused row's reason is a sentence: it wraps.
                wrap={row.on && !!paused}
                title={t(`workspace.share.${row.key}`)}
                description={
                  row.on && paused ? (
                    <span className="text-warning">{pausedText()}</span>
                  ) : (
                    state(row.on)
                  )
                }
                trailing={
                  row.on && canTakeOver ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      shape="pill"
                      className="shrink-0"
                      onClick={() => setTakeOverState('ACTIVE')}
                    >
                      {t('payer.common.takeOver.submit')}
                    </Button>
                  ) : null
                }
              />
            ))}
          </ListRows>
          <p className="text-muted-foreground px-4 text-xs">
            {t('workspace.share.adminsOnly')}
          </p>
        </section>
      ) : null}
      {/* Stays mounted after a Take over, so its dialog closes as usual. */}
      {outside && resourceId ? (
        <TakeOverModal
          kind="outside_access"
          name={resourceName ?? ''}
          payer={outside?.paid_by}
          modalState={takeOverState}
          setModalState={setTakeOverState}
          onConfirm={takeOver}
        />
      ) : null}
    </div>
  );
}

type OtherTeamsProps = {
  resourceType: ResourceType;
  resourceId?: string;
  info: TeamItemShares;
  currentUserId?: string;
  onChanged?: () => unknown;
};

/**
 * "Shared with other teams" for a member of the team that owns the item: a
 * picker of the caller's other teams and Share, gated on `share_outside`
 * (only `share_targets` are offered); what the picked team will get; the
 * current shares, each with Stop sharing when the caller may stop it. A
 * locked team says why nothing can be shared instead of the picker.
 */
function OtherTeams({
  resourceType,
  resourceId,
  info,
  currentUserId,
  onChanged,
}: OtherTeamsProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const noEscape = { interpolation: { escapeValue: false } };
  const owner = info.workspace.name ?? '';
  const shares = info.outside_shares ?? [];
  const targets = info.share_targets ?? [];
  const canShare = !!info.allowed_actions?.includes('share_outside');
  const locked = info.outside_policy === 'locked';
  const [target, setTarget] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toRevoke, setToRevoke] = useState<OutsideShare | null>(null);

  // A Viewer of an unlocked team with nothing shared has nothing to read
  // here; once locked, whoever could take items outside learns why not.
  const shown =
    canShare ||
    shares.length > 0 ||
    (locked && roleAtLeast(info.team_role ?? 'viewer', 'editor'));
  if (!shown) return null;

  const teamLabel = (name: string | null | undefined): string =>
    name || t('workspace.share.outside.unknownTeam');
  const picked = targets.find((row) => row.team_id === target) ?? null;

  const share = async () => {
    if (!picked || !resourceId) return;
    setSharing(true);
    setError(null);
    try {
      await teamsService.shareTeamItem(
        picked.team_id,
        { resource_type: resourceType, resource_id: resourceId },
        token,
      );
      setTarget(null);
      await onChanged?.();
    } catch (failure) {
      setError(
        teamErrorMessage(t, failure, t('workspace.share.outside.shareError')),
      );
    } finally {
      setSharing(false);
    }
  };

  const revoke = async (row: OutsideShare) => {
    if (!resourceId) return;
    await teamsService.unshareTeamItem(
      row.team_id,
      { resource_type: resourceType, resource_id: resourceId },
      token,
    );
    await onChanged?.();
  };

  // What stops when a share ends: the other team's chats with an agent, or
  // that team's agents using a source, tool or prompt.
  const revokeDescription = (row: OutsideShare): string => {
    const team = teamLabel(row.name);
    const what =
      resourceType === 'agent'
        ? t('workspace.share.outside.revokeAgent', { team, ...noEscape })
        : row.used_by_count
          ? t('workspace.share.outside.revokeUsed', {
              count: row.used_by_count,
              formatted: formatCount(row.used_by_count),
              team,
              ...noEscape,
            })
          : t('workspace.share.outside.revokeUnused', { team, ...noEscape });
    return `${what} ${t('workspace.share.outside.again')}`;
  };

  const rowDescription = (row: OutsideShare): ReactNode => {
    if (row.paused_reason === 'team_locked') {
      return (
        <span className="text-warning">
          {t('workspace.share.outside.pausedLocked', {
            owner,
            ...noEscape,
          })}
        </span>
      );
    }
    const by = row.shared_by;
    const parts = [
      by && currentUserId && by.user_id === currentUserId
        ? t('workspace.share.outside.sharedByYou')
        : by?.label
          ? t('workspace.share.outside.sharedBy', {
              name: by.label,
              ...noEscape,
            })
          : null,
      row.used_by_count
        ? t('workspace.share.outside.usedBy', {
            count: row.used_by_count,
            formatted: formatCount(row.used_by_count),
          })
        : null,
    ].filter(Boolean);
    return parts.join(' · ');
  };

  const picker = canShare ? (
    targets.length === 0 ? (
      <p className="text-muted-foreground text-sm">
        {t('workspace.share.outside.noTargets')}
      </p>
    ) : (
      <>
        <div className="flex items-center gap-2">
          <Combobox
            options={targets.map((row) => ({
              value: row.team_id,
              label: teamLabel(row.name),
              leading: (
                <Avatar alt="" variant="primary" size="xs" shape="square">
                  {initialOf(teamLabel(row.name))}
                </Avatar>
              ),
            }))}
            value={target}
            onValueChange={(value) => {
              setError(null);
              setTarget(value);
            }}
            placeholder={t('workspace.share.outside.pickerPlaceholder')}
            searchPlaceholder={t('workspace.share.outside.pickerSearch')}
            emptyText={t('workspace.share.outside.noMatches')}
            aria-label={t('workspace.share.outside.picker')}
            disabled={sharing}
            className="min-w-0 flex-1"
          />
          <Button
            type="button"
            size="field"
            disabled={!picked}
            loading={sharing}
            onClick={share}
          >
            {t('workspace.share.outside.share')}
          </Button>
        </div>
        {picked ? (
          <Alert variant="warning">
            <AlertDescription>
              {shareWarningLines(
                t,
                info.warning_kind,
                teamLabel(picked.name),
                owner,
              ).map((line) => (
                <p key={line}>{line}</p>
              ))}
            </AlertDescription>
          </Alert>
        ) : null}
      </>
    )
  ) : null;

  return (
    <section className="flex flex-col gap-3">
      <SectionHeader
        as="h3"
        size="xs"
        title={t('workspace.share.outside.teamsTitle')}
      />
      {locked ? (
        <Alert variant="info" role="note">
          <AlertDescription>
            {t('workspace.share.outside.locked', { team: owner, ...noEscape })}
          </AlertDescription>
        </Alert>
      ) : (
        picker
      )}
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {shares.length > 0 ? (
        <ListRows>
          {shares.map((row) => (
            <ListRow
              key={row.id}
              wrap={row.paused_reason === 'team_locked'}
              leading={
                <Avatar alt="" variant="primary" size="default" shape="square">
                  {initialOf(teamLabel(row.name))}
                </Avatar>
              }
              title={teamLabel(row.name)}
              description={rowDescription(row)}
              trailing={
                row.can_revoke ? (
                  <IconButton
                    variant="ghost-destructive"
                    size="icon-sm"
                    icon={Trash2}
                    label={t('workspace.share.outside.revoke')}
                    onClick={() => setToRevoke(row)}
                  />
                ) : null
              }
            />
          ))}
        </ListRows>
      ) : null}
      {toRevoke ? (
        <ConfirmationModal
          message={t('workspace.share.outside.revokeConfirm', {
            team: teamLabel(toRevoke.name),
            ...noEscape,
          })}
          description={revokeDescription(toRevoke)}
          modalState="ACTIVE"
          setModalState={(state) => state === 'INACTIVE' && setToRevoke(null)}
          submitLabel={t('workspace.share.outside.revoke')}
          handleSubmit={() => revoke(toRevoke)}
          error={(reason) =>
            teamErrorMessage(
              t,
              reason,
              t('workspace.share.outside.unshareError'),
            )
          }
          variant="destructive"
        />
      ) : null}
    </section>
  );
}
