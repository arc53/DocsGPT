import { CalendarClock, Monitor, ScrollText } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';

import { BackLink } from '../../../navigation/SectionPageHeader';
import SectionShell from '../../../navigation/SectionShell';
import { canAgent } from '../../agentAccess';
import AgentPageToolbar, {
  LastUsedMeta,
} from '../../components/AgentPageToolbar';
import {
  AGENTS_MANAGE_ROOT,
  agentLogsPath,
  agentSchedulesPath,
} from '../../paths';
import type { Agent } from '../../types';

/**
 * Stands in for the builder below ``lg``, where it has no layout.
 *
 * A saved workflow gets its agent page's frame (back link, Overview title,
 * the name byline and links to the Logs and Schedules tabs, which do work
 * on a phone) so the screen isn't a dead end. A new one only has the way
 * back to the agent list.
 *
 * Args:
 *   agent: The saved workflow, or null for a new one.
 */
export default function MobileBlocker({ agent }: { agent: Agent | null }) {
  const { t } = useTranslation();
  const blocker = (titleAs: 'p' | 'h1') => (
    <EmptyState
      icon={Monitor}
      titleAs={titleAs}
      title={t('agents.workflow.mobileBlocker.title')}
      description={t('agents.workflow.mobileBlocker.body')}
    />
  );

  if (!agent?.id) {
    return (
      // h-full, not h-dvh: the page area already sits under the 56px top bar.
      <div className="bg-background flex h-full flex-col p-4 lg:hidden">
        <BackLink to={AGENTS_MANAGE_ROOT} className="self-start">
          {t('agents.title')}
        </BackLink>
        <div className="flex flex-1 flex-col justify-center">
          {blocker('h1')}
        </div>
      </div>
    );
  }

  const tabs = [
    {
      action: 'view_logs',
      to: agentLogsPath(agent.id),
      icon: ScrollText,
      label: t('agents.pageHeader.tabs.logs'),
    },
    {
      action: 'manage_schedules',
      to: agentSchedulesPath(agent.id),
      icon: CalendarClock,
      label: t('agents.pageHeader.tabs.schedules'),
    },
  ].filter((tab) => canAgent(agent, tab.action));

  return (
    <div className="h-full lg:hidden">
      <SectionShell>
        <AgentPageToolbar
          name={agent.name}
          status={
            agent.status !== 'draft' ? (
              <Badge variant="success">
                {t('agents.form.status.published')}
              </Badge>
            ) : (
              <Badge variant="neutral">{t('agents.card.draft')}</Badge>
            )
          }
          meta={<LastUsedMeta lastUsedAt={agent.last_used_at} />}
          actions={
            tabs.length > 0 ? (
              <div className="flex gap-2">
                {tabs.map(({ to, icon: Icon, label }) => (
                  // flex-1 shares the phone row, as Preview and Save do.
                  <Button
                    key={to}
                    asChild
                    variant="outline"
                    size="field"
                    shape="pill"
                    className="flex-1"
                  >
                    <Link to={to}>
                      <Icon />
                      {label}
                    </Link>
                  </Button>
                ))}
              </div>
            ) : undefined
          }
        />
        {blocker('p')}
      </SectionShell>
    </div>
  );
}
