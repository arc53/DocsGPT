import { Monitor } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { LoadingState } from '@/components/ui/loading-state';

import { BackLink } from '../../../navigation/SectionPageHeader';
import SectionShell from '../../../navigation/SectionShell';
import {
  buildAgentSection,
  getVisibleGroups,
} from '../../../navigation/sections';
import { selectAnalyticsEnabled } from '../../../preferences/preferenceSlice';
import AgentPageToolbar, {
  LastUsedMeta,
} from '../../components/AgentPageToolbar';
import { useAgentMenu } from '../../hooks/useAgentMenu';
import { AGENTS_MANAGE_ROOT } from '../../paths';
import type { Agent, AgentConfig } from '../../types';

/**
 * Stands in for the builder below ``lg``, where it has no layout.
 *
 * A saved workflow gets its agent page's frame (back link, Overview title,
 * the name byline and links to its other pages, which do work on a phone)
 * so the screen isn't a dead end. The links are the agent sidebar's
 * (`buildAgentSection`) after Overview, in its order. A new one only has the way
 * back to the agent list.
 *
 * Args:
 *   agent: The saved workflow, or null for a new one.
 *   loading: The saved workflow is still loading; a spinner, so a phone
 *     doesn't show the new-workflow screen first.
 *   onDeleted: After a delete from the agent ⋯ (the builder's way back).
 *   onKeyRegenerated: A key regenerated in Access details, for the builder.
 *   onConfigChange: The config Access details saved, for the builder.
 */
export default function MobileBlocker({
  agent,
  loading = false,
  onDeleted,
  onKeyRegenerated,
  onConfigChange,
}: {
  agent: Agent | null;
  loading?: boolean;
  onDeleted?: () => void;
  onKeyRegenerated?: (key: string) => void;
  onConfigChange?: (config: AgentConfig) => void;
}) {
  const { t } = useTranslation();
  const analyticsEnabled = useSelector(selectAnalyticsEnabled);
  // The desktop builder's ⋯ offers Access details and Share on a draft too.
  const agentMenu = useAgentMenu({
    agent,
    shareable: true,
    onDeleted,
    onKeyRegenerated,
    onConfigChange,
  });
  if (loading) {
    return (
      <div className="h-full lg:hidden">
        <LoadingState fill="parent" />
      </div>
    );
  }
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

  // Overview is this page, so it gets no link.
  const tabs = getVisibleGroups(
    buildAgentSection(agent.id, agent.name, true, agent),
    { features: { analytics: analyticsEnabled === true } },
  )
    .flatMap((group) => group.items)
    .filter((item) => item.key !== 'overview');

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
              // Four links don't fit one phone row: they wrap, two by two,
              // and share a tablet's row.
              <div className="flex flex-wrap gap-2">
                {tabs.map(({ key, path, icon: Icon, labelKey }) => (
                  // flex-1 shares the row, as Preview and Save do.
                  <Button
                    key={key}
                    asChild
                    variant="outline"
                    size="field"
                    shape="pill"
                    className="flex-1"
                  >
                    <Link to={path}>
                      <Icon />
                      {t(labelKey)}
                    </Link>
                  </Button>
                ))}
              </div>
            ) : undefined
          }
          menu={agentMenu.menu}
        />
        {agentMenu.modals}
        {blocker('p')}
      </SectionShell>
    </div>
  );
}
