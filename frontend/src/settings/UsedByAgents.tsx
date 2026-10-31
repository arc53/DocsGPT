import { Bot } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { agentChatPath, agentEditPath } from '../agents/paths';
import { Button } from '../components/ui/button';
import { MetaItem } from '../components/ui/meta-line';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '../components/ui/popover';
import { SectionHeader } from '../components/ui/section-header';
import { formatCount } from '../utils/dateTimeUtils';
import { agentUseCount } from '../utils/resourceUsage';
import type { ResourceUsage } from './types';

type UsedByAgentsProps = {
  usage: ResourceUsage | null | undefined;
};

/**
 * "2 agents" with the Bot icon, an item in a tile's meta line, in the line's
 * own colour (`link` with `tone="current"`): where an item is used is a fact, so it doesn't
 * take the link colour. When some of those agents are the caller's to open,
 * it opens a popover headed "Used by 2 agents" that lists them as links,
 * with the ones on teammates' agents counted under the list. A link opens
 * the agent's editor when the caller may edit it (`can_edit`), else its
 * chat: the editor's route would send a viewer back to the agent list. Draws nothing
 * for a resource no agent uses; callers check `agentUseCount` first so a
 * `MetaLine` doesn't keep a dot for it.
 */
export default function UsedByAgents({ usage }: UsedByAgentsProps) {
  const { t } = useTranslation();
  const count = agentUseCount(usage);
  if (count === 0) return null;
  const formatted = formatCount(count);
  const label = t('settings.usage.agents', { count, formatted });
  const short = t('settings.usage.agentsShort', { count, formatted });
  const agents = usage?.agents ?? [];
  const others = usage?.others ?? 0;
  if (agents.length === 0)
    return (
      <MetaItem icon={<Bot />} title={label}>
        {short}
      </MetaItem>
    );
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="link"
          tone="current"
          size="text"
          aria-label={label}
        >
          <Bot className="size-3.5" aria-hidden="true" />
          {short}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64" aria-label={label}>
        <SectionHeader as="h3" size="xs" title={label} />
        <ul className="mt-3 flex flex-col gap-2 text-sm">
          {agents.map((agent) => (
            <li key={agent.id} className="flex min-w-0 items-center gap-2">
              <Bot
                className="text-muted-foreground size-4 shrink-0"
                aria-hidden="true"
              />
              <Button variant="link" size="text" asChild>
                <Link
                  to={
                    agent.can_edit
                      ? agentEditPath(agent.id, agent.agent_type === 'workflow')
                      : agentChatPath(agent.id)
                  }
                  title={agent.name}
                  className="min-w-0 shrink"
                >
                  <span className="truncate">{agent.name}</span>
                </Link>
              </Button>
            </li>
          ))}
        </ul>
        {others > 0 ? (
          <p className="text-muted-foreground mt-3 text-xs">
            {t('settings.usage.others', {
              count: others,
              formatted: formatCount(others),
            })}
          </p>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
