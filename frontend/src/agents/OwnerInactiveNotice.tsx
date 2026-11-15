import { createContext, useContext } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '../components/ui/alert';
import { Badge } from '../components/ui/badge';
import type { Agent } from './types';

/** An agent as its pages read it, with the owner's account state. */
type NoticeAgent = Agent & { owner_inactive?: boolean };

/**
 * The agent whose pages are open, as the route guard read it. Its pages'
 * toolbars read notices about the agent from here.
 */
export const AgentNoticeContext = createContext<NoticeAgent | null>(null);

/**
 * "Outside access is paused: its owner's account is deactivated." An agent
 * runs its key, public link, webhook and schedules as its owner, so they
 * stop while that account is off.
 *
 * Args:
 *   agent: The agent; the opened one when left out.
 *   className: Placement.
 */
export default function OwnerInactiveNotice({
  agent,
  className,
}: {
  agent?: NoticeAgent | null;
  className?: string;
}) {
  const { t } = useTranslation();
  const opened = useContext(AgentNoticeContext);
  if (!(agent ?? opened)?.owner_inactive) return null;
  return (
    <Alert variant="info" role="note" className={className}>
      <AlertDescription>
        <p>{t('workspace.notices.ownerInactive')}</p>
      </AlertDescription>
    </Alert>
  );
}

/** The same notice as a status Badge, for the workflow builder's one-row header. */
export function OwnerInactiveBadge() {
  const { t } = useTranslation();
  const opened = useContext(AgentNoticeContext);
  if (!opened?.owner_inactive) return null;
  return (
    <Badge variant="warning" title={t('workspace.notices.ownerInactive')}>
      {t('workspace.notices.ownerInactiveShort')}
    </Badge>
  );
}
