import {
  ChevronRight,
  Database,
  ScrollText,
  TriangleAlert,
  Wrench,
} from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { cn } from '@/lib/utils';

import { can, isOwner } from '../../utils/accessUtils';
import type { ResourceState } from '../types';
import useAgentResourceStates from '../useAgentResourceStates';
import { reasonKey } from './ResourceStatusNotice';

type AgentUsesSectionProps = {
  /** The agent the share dialog is for. */
  agentId: string;
  /** The reader's user id, to say "your" for what runs as them. */
  readerId?: string;
  /**
   * Opens the agent's Access details, where its owner allows changes
   * through the API, widget and public links. Without it the note only
   * says where to go.
   */
  onOpenAccessDetails?: () => void;
};

const TYPE_ICONS: Record<ResourceState['type'], typeof Wrench> = {
  tool: Wrench,
  source: Database,
  prompt: ScrollText,
};

const K = 'settings.teams.share.uses';
const plain = { interpolation: { escapeValue: false } };

/** Write actions outside callers can't take: not in the API write allowlist. */
function blockedWrites(item: ResourceState, allowlist: string[]): string[] {
  const allowed = new Set(allowlist.map((entry) => entry.toLowerCase()));
  return (item.owner_credential_writes ?? []).filter(
    (action) => !allowed.has(`${item.id}:${action}`.toLowerCase()),
  );
}

/**
 * "What this agent uses" in the agent's share dialog: each attached tool,
 * source and prompt (and a workflow agent's node tools and sources), with
 * whose access, account or saved credentials it runs with for the people
 * the agent is shared with.
 *
 * Built from `resource_states` on the agent read (and the workflow read),
 * which only owners and editors get; the section is hidden from anyone else,
 * and while it loads or when it fails. A stopped item says why. A tool with
 * writes on stored credentials that aren't in the API write allowlist is
 * marked (all or some of them), since API and widget users, and public-link
 * users on the owner's accounts, can't make those changes; so is a tool an
 * admin allows no changes through. That allowlist is not the connector's
 * Allow (the in-chat permission), so the note says so and, for the owner,
 * opens Access details where the list is set.
 */
export default function AgentUsesSection({
  agentId,
  readerId,
  onOpenAccessDetails,
}: AgentUsesSectionProps) {
  const { t } = useTranslation();
  const loaded = useAgentResourceStates(agentId);
  // Like Access settings: open once by itself when something stopped, then
  // follow the reader's clicks.
  const [open, setOpen] = useState<boolean | null>(null);

  if (!loaded || !can(loaded.agent, 'edit') || loaded.items.length === 0)
    return null;

  const { agent, items } = loaded;
  const expanded = open ?? items.some((item) => item.state === 'stopped');
  const ownerReads = isOwner(agent);
  // Without a user id (authentication off) the one local user is everyone.
  const isYou = (userId: string) =>
    readerId ? userId === readerId : ownerReads;
  // A tool each person connects runs on their own account (the notice's
  // note), except for API and widget users.
  const perUser = (item: ResourceState) => item.note === 'per_user_account';
  const allowlist = agent.config?.api_write_allowlist ?? [];
  const nameOf = (item: ResourceState) =>
    item.name || t('agents.form.sponsors.unknownItem');

  // Whose account or saved credentials a tool acts with.
  const credentialsLabel = (item: ResourceState): string | null => {
    const service = item.connection?.name;
    const suffix = service ? '' : 'NoService';
    const named = service ? { ...plain, service } : plain;
    if (perUser(item))
      // API and widget callers run the agent as its owner, so they use the
      // owner's own account.
      return t(
        `${K}.access.member${ownerReads ? '' : 'Shared'}${suffix}`,
        named,
      );
    const account = item.account;
    if (!account) return null;
    // A connection names its service; saved credentials (an API key, an
    // MCP sign-in) have none.
    const connected = item.credential_mode === 'owner';
    const key = connected ? `Account${suffix}` : 'Credentials';
    const opts = connected ? named : plain;
    if (!account.user_id) return t(`${K}.access.other${key}`, opts);
    if (isYou(account.user_id)) return t(`${K}.access.your${key}`, opts);
    return t(`${K}.access.person${key}`, {
      ...opts,
      person: account.label || account.user_id,
    });
  };

  const accessLabel = (item: ResourceState): string => {
    const credentials = credentialsLabel(item);
    if (credentials) return credentials;
    if (item.runs_as) {
      const { user_id: userId, label } = item.runs_as;
      if (!userId) return t(`${K}.access.other`);
      return isYou(userId)
        ? t(`${K}.access.you`)
        : t(`${K}.access.person`, { ...plain, person: label || userId });
    }
    return ownerReads ? t(`${K}.access.you`) : t(`${K}.access.owner`);
  };

  const stoppedText = (item: ResourceState) =>
    t(reasonKey(item.reason, ownerReads, Boolean(item.sponsor?.user_id)), {
      ...plain,
      name: nameOf(item),
      service:
        item.connection?.name ||
        t('agents.form.resourceStates.serviceFallback'),
      person: item.sponsor?.label || item.sponsor?.user_id,
    });

  const badgeFor = (item: ResourceState) => {
    if (item.state === 'stopped')
      return <Badge variant="warning">{t(`${K}.stopped`)}</Badge>;
    if (item.writes_allowed === false)
      return <Badge variant="neutral">{t(`${K}.adminOff`)}</Badge>;
    const blocked = blockedWrites(item, allowlist).length;
    if (blocked === 0) return null;
    const all = blocked === (item.owner_credential_writes ?? []).length;
    return (
      <Badge variant="warning">
        {t(all ? `${K}.writesOff` : `${K}.writesSomeOff`)}
      </Badge>
    );
  };

  // Public-link users act with their own account on a tool each person
  // connects, so only API and widget users are held back there.
  const blocked = items.filter(
    (item) =>
      item.state === 'active' &&
      item.writes_allowed !== false &&
      blockedWrites(item, allowlist).length > 0,
  );
  const blockedMember = blocked.some(perUser);
  const blockedOwned = blocked.some((item) => !perUser(item));
  const editor = ownerReads ? '' : 'Editor';
  const writesNote = blockedOwned
    ? [
        t(`${K}.writesNote${editor}`),
        blockedMember ? t(`${K}.writesNoteMemberTail`) : '',
      ]
        .filter(Boolean)
        .join(' ')
    : blockedMember
      ? t(`${K}.writesNoteApi${editor}`)
      : null;

  return (
    <section className="flex flex-col gap-3">
      {/* The same inline disclosure as Access settings. */}
      <Button
        type="button"
        variant="link"
        size="sm"
        aria-expanded={expanded}
        className="-ml-3 w-fit justify-start"
        onClick={() => setOpen(!expanded)}
      >
        <ChevronRight
          aria-hidden="true"
          className={cn(
            'transition-transform duration-200',
            expanded && 'rotate-90',
          )}
        />
        {t(`${K}.title`)}
      </Button>
      {expanded && (
        <>
          <p className="text-muted-foreground text-xs">{t(`${K}.intro`)}</p>
          <Card variant="outline" padding="none" className="overflow-hidden">
            <ListRows>
              {items.map((item) => {
                const Icon = TYPE_ICONS[item.type] ?? Wrench;
                const description =
                  item.state === 'stopped'
                    ? stoppedText(item)
                    : accessLabel(item);
                return (
                  <ListRow
                    key={item.key}
                    leading={
                      <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md">
                        <Icon className="size-4" aria-hidden="true" />
                      </span>
                    }
                    title={<span title={nameOf(item)}>{nameOf(item)}</span>}
                    description={<span title={description}>{description}</span>}
                    trailing={badgeFor(item)}
                  />
                );
              })}
            </ListRows>
          </Card>
          {writesNote && (
            <Alert variant="warning">
              <TriangleAlert />
              <AlertDescription>{writesNote}</AlertDescription>
              {/* Only the owner sets the allowlist. */}
              {ownerReads && onOpenAccessDetails && (
                <div className="mt-2">
                  <Button
                    type="button"
                    size="sm"
                    shape="pill"
                    variant="outline"
                    onClick={onOpenAccessDetails}
                  >
                    {t(`${K}.openAccessDetails`)}
                  </Button>
                </div>
              )}
            </Alert>
          )}
        </>
      )}
    </section>
  );
}
