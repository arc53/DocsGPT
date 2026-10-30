import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { EmptyState } from '../components/ui/empty-state';
import SectionShell from '../navigation/SectionShell';
import Analytics from '../settings/Analytics';
import TimeFilterSelect, {
  DEFAULT_TIME_FILTER,
  type TimeFilter,
} from '../settings/TimeFilterSelect';
import AgentPageToolbar, { LastUsedMeta } from './components/AgentPageToolbar';
import { useAgent } from './hooks/useAgent';

/**
 * An agent's Analytics: the counted usage (messages, tokens, scheduled
 * runs, tools, feedback) for this agent alone. The first of its Monitoring
 * pages, next to Insights and Logs, as in Settings. The window select is
 * the toolbar's action, as on Insights.
 */
export default function AgentAnalytics() {
  const { t } = useTranslation();
  const { agentId } = useParams();
  const { agent, error, reload } = useAgent(agentId);
  const [timeFilter, setTimeFilter] = useState<TimeFilter>(DEFAULT_TIME_FILTER);

  return (
    <SectionShell>
      <AgentPageToolbar
        name={agent?.name}
        meta={agent && <LastUsedMeta lastUsedAt={agent.last_used_at} />}
        actions={
          <TimeFilterSelect value={timeFilter} onChange={setTimeFilter} />
        }
      />
      {/* The record only fills the byline: its failure says so here, and
          the usage below, which needs only the id, stays. */}
      {error && (
        <EmptyState
          tone="destructive"
          size="sm"
          illustration="none"
          title={t('agents.loadError')}
          onRetry={reload}
        />
      )}
      <p className="text-muted-foreground mb-4 text-sm leading-6">
        {t('agents.analytics.subtitle')}
      </p>
      {agentId && <Analytics agentId={agentId} filterOption={timeFilter} />}
    </SectionShell>
  );
}
