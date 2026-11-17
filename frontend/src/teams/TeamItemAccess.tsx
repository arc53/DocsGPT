import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import { rememberOutsideAccess } from '../agents/OwnerInactiveNotice';
import payerService from '../api/services/payerService';
import type { ResourceType } from '../api/services/teamsService';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import { ListRow, ListRows } from '../components/ui/list-row';
import { SectionHeader } from '../components/ui/section-header';
import type { ActiveState } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { pauseReasonText } from '../payer/pauseReason';
import TakeOverModal from '../payer/TakeOverModal';
import type {
  OutsideAccess,
  OutsideAccessKind,
  PersonRef,
} from '../payer/types';
import { selectToken } from '../preferences/preferenceSlice';
import { roleAtLeast, type WorkspaceRole } from '../workspace/workspaceSlice';

/**
 * `GET /api/resource_shares` for an item a team owns: no per-item people,
 * the team and its size, the caller's access, and an agent's outside access.
 */
export type TeamItemShares = {
  success?: boolean;
  shares?: unknown[];
  workspace: { kind: 'team'; team_id: string; name?: string | null };
  members_count?: number;
  access?: string | null;
  allowed_actions?: string[];
  team_role?: WorkspaceRole | null;
  origin?: 'own' | 'team' | 'shared' | null;
  /** Agents only: what is on, who pays, why it is paused, Take over. */
  outside_access?: OutsideAccess | null;
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
};

const initialOf = (label: string): string => {
  const trimmed = label.trim();
  return trimmed ? trimmed[0].toUpperCase() : '?';
};

/**
 * The share dialog's body for an item a team owns: access follows team
 * membership, so it shows one row for everyone in the team (with Manage
 * members for the team's Admins), the caller's own row with their team role,
 * and for an agent what reaches it from outside the team (public link, API
 * key and widget, webhook), each On or Off and who pays for it, or why it is
 * paused. Those are changed on the agent's own page, by an Admin; an Admin
 * who doesn't pay for them can take them over here.
 */
export default function TeamItemAccess({
  resourceType,
  resourceId,
  resourceName,
  info,
  currentUserId,
  onNavigate,
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
