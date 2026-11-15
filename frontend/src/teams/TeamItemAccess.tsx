import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import type {
  OutsideAccess,
  PersonRef,
} from '../api/services/workspacesService';
import type { ResourceType } from '../api/services/teamsService';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import { ListRow, ListRows } from '../components/ui/list-row';
import { SectionHeader } from '../components/ui/section-header';
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
  /** Agents only. */
  outside_access?:
    (Omit<OutsideAccess, 'paid_by'> & { paid_by?: PersonRef | null }) | null;
};

/** Whether a `resource_shares` answer is a team item's. */
export const isTeamItemShares = (body: unknown): body is TeamItemShares =>
  !!body &&
  typeof body === 'object' &&
  (body as { workspace?: { kind?: unknown } }).workspace?.kind === 'team';

type Props = {
  resourceType: ResourceType;
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
 * key and widget, webhook), each On or Off and who pays for it. Those are
 * changed on the agent's own page, by an Admin.
 */
export default function TeamItemAccess({
  resourceType,
  info,
  currentUserId,
  onNavigate,
}: Props) {
  const { t } = useTranslation();
  const noEscape = { interpolation: { escapeValue: false } };
  const team = info.workspace.name ?? '';
  const role = info.team_role ?? 'viewer';
  const outside = resourceType === 'agent' ? info.outside_access : null;

  const payer = (person: PersonRef | null | undefined): string | null => {
    if (!person) return null;
    if (currentUserId && person.user_id === currentUserId)
      return t('workspace.share.payerYou');
    return person.label || null;
  };
  const state = (on: boolean): string => {
    if (!on) return t('workspace.share.off');
    const name = payer(outside?.paid_by);
    return name
      ? t('workspace.share.onPaidBy', { name, ...noEscape })
      : t('workspace.share.on');
  };

  const outsideRows = outside
    ? [
        { key: 'publicLink', on: !!outside.public_link },
        { key: 'apiKey', on: !!outside.api_key },
        { key: 'webhook', on: !!outside.webhook },
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
            title={t('workspace.share.outside')}
          />
          <ListRows>
            {outsideRows.map((row) => (
              <ListRow
                key={row.key}
                title={t(`workspace.share.${row.key}`)}
                trailing={
                  <span className="text-muted-foreground shrink-0 pr-3 text-sm">
                    {state(row.on)}
                  </span>
                }
              />
            ))}
          </ListRows>
          <p className="text-muted-foreground px-4 text-xs">
            {t('workspace.share.adminsOnly')}
          </p>
        </section>
      ) : null}
    </div>
  );
}
