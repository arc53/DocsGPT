import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { agentEditPath } from '../agents/paths';
import { Button } from '../components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '../components/ui/popover';
import { formatCount } from '../utils/dateTimeUtils';
import { agentUseCount } from '../utils/resourceUsage';
import type { ResourceUsage } from './types';

type UsedByAgentsProps = {
  usage: ResourceUsage | null | undefined;
};

/**
 * "Used by N agents" in a tile's meta line. When some of those agents are
 * the caller's to open, it opens a popover listing them, each a link to the
 * agent, with the ones on teammates' agents counted under the list. Draws
 * nothing for a resource no agent uses.
 */
export default function UsedByAgents({ usage }: UsedByAgentsProps) {
  const { t } = useTranslation();
  const count = agentUseCount(usage);
  if (count === 0) return null;
  const label = t('settings.usage.agents', {
    count,
    formatted: formatCount(count),
  });
  const agents = usage?.agents ?? [];
  const others = usage?.others ?? 0;
  if (agents.length === 0) return <span>{label}</span>;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="link" size="text">
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64" aria-label={label}>
        <ul className="flex flex-col gap-2 text-sm">
          {agents.map((agent) => (
            <li key={agent.id}>
              <Button variant="link" size="text" asChild>
                <Link
                  to={agentEditPath(agent.id, agent.agent_type === 'workflow')}
                >
                  {agent.name}
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
