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
import { ListRow, ListRows } from '@/components/ui/list-row';
import { cn } from '@/lib/utils';

import ConnectorIcon from '../../connectors/ConnectorIcon';
import { connectorIconKey } from '../../connectors/i18n';
import { can, isOwner } from '../../utils/accessUtils';
import { personLabel } from '../../utils/personLabel';
import type { ResourcePerson, ResourceState } from '../types';
import useAgentResourceStates from '../useAgentResourceStates';
import { stoppedReason } from './ResourceStatusNotice';

type AgentUsesSectionProps = {
  /** The agent the share dialog is for. */
  agentId: string;
  /** The reader's user id, to say "you" for what runs as them. */
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
 * source and prompt (and a workflow agent's node tools and sources), in the
 * same unboxed rows as People with access, with the service's logo where
 * it has one.
 *
 * Built from `resource_states` on the agent read (and the workflow read),
 * which only owners and editors get; the section is hidden from anyone else,
 * and while it loads or when it fails. A row's meta says only what differs
 * from the owner's own access — who else it runs as, or that each person
 * uses their own account — and otherwise the kind of item; a stopped item
 * says why in a few words (the agent form's notice has the full sentence).
 * A tool with writes on stored credentials that aren't in the API write
 * allowlist is marked (all or some of them), since API, widget and link
 * users can't make those changes; so is a tool an admin allows no changes
 * through. One line under the list says so and, for the owner, opens
 * Access details where the list is set.
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
  const allowlist = agent.config?.api_write_allowlist ?? [];
  const nameOf = (item: ResourceState) =>
    item.name || t('agents.form.sponsors.unknownItem');

  /** "Runs as …" the person: the reader, someone named, or someone else. */
  const runsAs = (person: ResourcePerson): string => {
    if (!person.user_id) return t(`${K}.access.runsAsOther`);
    if (isYou(person.user_id)) return t(`${K}.access.runsAsYou`);
    return t(`${K}.access.runsAs`, { ...plain, person: personLabel(person) });
  };

  // Whose access a running item uses, when it isn't the owner's own; null
  // when it is.
  const accessMeta = (item: ResourceState): string | null => {
    // A tool each person connects runs on their own account (API and
    // widget callers run the agent as its owner).
    if (item.note === 'per_user_account') {
      const service = item.connection?.name;
      return service
        ? t(`${K}.access.member`, { ...plain, service })
        : t(`${K}.access.memberNoService`);
    }
    if (item.runs_as) return runsAs(item.runs_as);
    // It runs as the owner, on the saved credentials or connected account
    // of the tool's owner: the reader's own when they own the agent. An
    // editor can't tell the agent owner's account from a third person's,
    // so only theirs or an unknown one is named.
    const account = item.account;
    if (!account) return null;
    if (!account.user_id) return runsAs(account);
    if (ownerReads) return isYou(account.user_id) ? null : runsAs(account);
    return isYou(account.user_id) ? runsAs(account) : null;
  };

  const metaFor = (item: ResourceState): string => {
    if (item.state === 'stopped') {
      const service = item.connection?.name ?? '';
      const reason = stoppedReason(item, {
        ownerReads,
        readerId,
        noService: !service.trim(),
      });
      return t(`${K}.reasonShort.${reason}`, {
        ...plain,
        service,
        person: personLabel(item.sponsor),
      });
    }
    return (
      accessMeta(item) ?? t(`agents.form.sponsorConfirm.types.${item.type}`)
    );
  };

  const leadingFor = (item: ResourceState) => {
    const Icon = TYPE_ICONS[item.type] ?? Wrench;
    const connectorKey = item.connection?.connector_key;
    return (
      <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md">
        {connectorKey ? (
          <ConnectorIcon
            icon={connectorIconKey(connectorKey)}
            className="size-4"
          />
        ) : (
          <Icon className="size-4" aria-hidden="true" />
        )}
      </span>
    );
  };

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

  const anyBlocked = items.some(
    (item) =>
      item.state === 'active' &&
      item.writes_allowed !== false &&
      blockedWrites(item, allowlist).length > 0,
  );

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
          <ListRows>
            {items.map((item) => {
              const meta = metaFor(item);
              return (
                <ListRow
                  key={item.key}
                  leading={leadingFor(item)}
                  title={<span title={nameOf(item)}>{nameOf(item)}</span>}
                  description={<span title={meta}>{meta}</span>}
                  trailing={badgeFor(item)}
                />
              );
            })}
          </ListRows>
          {anyBlocked && (
            <Alert variant="warning">
              <TriangleAlert />
              <AlertDescription>
                {t(ownerReads ? `${K}.writesNote` : `${K}.writesNoteEditor`)}
              </AlertDescription>
              {/* Only the owner sets the allowlist. */}
              {ownerReads && onOpenAccessDetails && (
                <div className="mt-2 flex flex-col items-start gap-1.5">
                  {/* Access details lists these writes once there is a key
                      (a draft gets one when it is published). */}
                  {!agent.key && (
                    <p className="text-xs">{t(`${K}.accessDetailsNeedsKey`)}</p>
                  )}
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
