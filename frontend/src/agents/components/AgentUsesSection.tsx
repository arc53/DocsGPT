import {
  ChevronRight,
  Database,
  ScrollText,
  TriangleAlert,
  Wrench,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { cn } from '@/lib/utils';

import userService from '../../api/services/userService';
import { selectToken } from '../../preferences/preferenceSlice';
import { can, isOwner } from '../../utils/accessUtils';
import type { Agent, ResourceState } from '../types';
import { reasonKey } from './ResourceStatusNotice';

type AgentUsesSectionProps = {
  /** The agent the share dialog is for. */
  agentId: string;
  /** The reader's user id, to say "your" for what runs as them. */
  readerId?: string;
};

const TYPE_ICONS: Record<ResourceState['type'], typeof Wrench> = {
  tool: Wrench,
  source: Database,
  prompt: ScrollText,
};

const K = 'settings.teams.share.uses';
const plain = { interpolation: { escapeValue: false } };

/** The agent's own items, then its workflow nodes' ones it doesn't have. */
function mergeStates(
  own: ResourceState[],
  nodes: ResourceState[],
): ResourceState[] {
  const seen = new Set(own.map((item) => item.key.toLowerCase()));
  return [...own, ...nodes.filter((item) => !seen.has(item.key.toLowerCase()))];
}

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
 * whose access it runs with for the people the agent is shared with.
 *
 * Built from `resource_states` on the agent read (and the workflow read),
 * which only owners and editors get; the section is hidden from anyone else,
 * and while it loads or when it fails. A stopped item says why. A tool whose
 * writes act on stored credentials and aren't in the API write allowlist is
 * marked, since API, widget and public-link users can't make those changes.
 */
export default function AgentUsesSection({
  agentId,
  readerId,
}: AgentUsesSectionProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [loaded, setLoaded] = useState<{
    agent: Agent;
    items: ResourceState[];
  } | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoaded(null);
    setOpen(false);
    const load = async () => {
      let agent: Agent;
      try {
        const response = await userService.getAgent(agentId, token);
        if (!response.ok) return;
        agent = await response.json();
      } catch {
        return;
      }
      let items = agent.resource_states ?? [];
      if (agent.agent_type === 'workflow' && agent.workflow) {
        try {
          const response = await userService.getWorkflow(agent.workflow, token);
          if (response.ok) {
            const body = await response.json();
            items = mergeStates(items, body?.data?.resource_states ?? []);
          }
        } catch {
          // The agent's own items still show.
        }
      }
      if (cancelled) return;
      setLoaded({ agent, items });
      // Like Access settings: open when there is something to look at.
      if (items.some((item) => item.state === 'stopped')) setOpen(true);
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [agentId, token]);

  if (!loaded || !can(loaded.agent, 'edit') || loaded.items.length === 0)
    return null;

  const { agent, items } = loaded;
  const ownerReads = isOwner(agent);
  // Without a user id (authentication off) the one local user is everyone.
  const isYou = (userId: string) =>
    readerId ? userId === readerId : ownerReads;
  const allowlist = agent.config?.api_write_allowlist ?? [];
  const nameOf = (item: ResourceState) =>
    item.name || t('agents.form.sponsors.unknownItem');

  const accessLabel = (item: ResourceState): string => {
    const service = item.connection?.name;
    if (item.credential_mode === 'member')
      return service
        ? t(`${K}.access.member`, { ...plain, service })
        : t(`${K}.access.memberNoService`);
    if (item.credential_mode === 'owner' && item.account) {
      if (isYou(item.account.user_id))
        return service
          ? t(`${K}.access.yourAccount`, { ...plain, service })
          : t(`${K}.access.yourAccountNoService`);
      return service
        ? t(`${K}.access.personAccount`, {
            ...plain,
            person: item.account.label,
            service,
          })
        : t(`${K}.access.personAccountNoService`, {
            ...plain,
            person: item.account.label,
          });
    }
    if (item.sponsor)
      return isYou(item.sponsor.user_id)
        ? t(`${K}.access.you`)
        : t(`${K}.access.person`, { ...plain, person: item.sponsor.label });
    return ownerReads ? t(`${K}.access.you`) : t(`${K}.access.owner`);
  };

  const stoppedText = (item: ResourceState) =>
    t(reasonKey(item.reason, ownerReads), {
      ...plain,
      name: nameOf(item),
      service:
        item.connection?.name ||
        t('agents.form.resourceStates.serviceFallback'),
      person: item.sponsor?.label || item.sponsor?.user_id,
    });

  const anyBlocked = items.some(
    (item) =>
      item.state === 'active' && blockedWrites(item, allowlist).length > 0,
  );

  return (
    <section className="flex flex-col gap-3">
      {/* The same inline disclosure as Access settings. */}
      <Button
        type="button"
        variant="link"
        size="sm"
        aria-expanded={open}
        className="-ml-3 w-fit justify-start"
        onClick={() => setOpen((value) => !value)}
      >
        <ChevronRight
          aria-hidden="true"
          className={cn(
            'transition-transform duration-200',
            open && 'rotate-90',
          )}
        />
        {t(`${K}.title`)}
      </Button>
      {open && (
        <>
          <p className="text-muted-foreground text-xs">{t(`${K}.intro`)}</p>
          <Card variant="outline" padding="none" className="overflow-hidden">
            <ListRows>
              {items.map((item) => {
                const Icon = TYPE_ICONS[item.type] ?? Wrench;
                const stopped = item.state === 'stopped';
                const description = stopped
                  ? stoppedText(item)
                  : accessLabel(item);
                const writesOff =
                  !stopped && blockedWrites(item, allowlist).length > 0;
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
                    trailing={
                      stopped ? (
                        <Badge variant="warning">{t(`${K}.stopped`)}</Badge>
                      ) : writesOff ? (
                        <Badge variant="warning">{t(`${K}.writesOff`)}</Badge>
                      ) : null
                    }
                  />
                );
              })}
            </ListRows>
          </Card>
          {anyBlocked && (
            <Alert variant="warning">
              <TriangleAlert />
              <AlertDescription>
                {ownerReads ? t(`${K}.writesNote`) : t(`${K}.writesNoteEditor`)}
              </AlertDescription>
            </Alert>
          )}
        </>
      )}
    </section>
  );
}
