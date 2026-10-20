import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import SectionShell from '../navigation/SectionShell';
import { selectToken } from '../preferences/preferenceSlice';
import Analytics from '../settings/Analytics';
import TimeFilterSelect, {
  DEFAULT_TIME_FILTER,
  type TimeFilter,
} from '../settings/TimeFilterSelect';
import AgentPageToolbar, { LastUsedMeta } from './components/AgentPageToolbar';
import { Agent } from './types';

/**
 * An agent's Analytics: the counted usage (messages, tokens, scheduled
 * runs, tools, feedback) for this agent alone. The first of its Monitoring
 * pages, next to Insights and Logs, as in Settings. The window select is
 * the toolbar's action, as on Insights.
 */
export default function AgentAnalytics() {
  const { t } = useTranslation();
  const { agentId } = useParams();
  const token = useSelector(selectToken);
  const [agent, setAgent] = useState<Agent>();
  const [timeFilter, setTimeFilter] = useState<TimeFilter>(DEFAULT_TIME_FILTER);

  useEffect(() => {
    if (!agentId) return;
    let cancelled = false;
    userService
      .getAgent(agentId, token)
      .then((response) => {
        if (!response.ok) throw new Error('agent');
        return response.json();
      })
      .then((record: Agent) => {
        if (!cancelled) setAgent(record);
      })
      .catch((error) => console.error(error));
    return () => {
      cancelled = true;
    };
  }, [agentId, token]);

  return (
    <SectionShell>
      <AgentPageToolbar
        name={agent?.name}
        meta={agent && <LastUsedMeta lastUsedAt={agent.last_used_at} />}
        actions={
          <TimeFilterSelect value={timeFilter} onChange={setTimeFilter} />
        }
      />
      <p className="text-muted-foreground mb-4 text-sm leading-6">
        {t('agents.analytics.subtitle')}
      </p>
      {agentId && <Analytics agentId={agentId} filterOption={timeFilter} />}
    </SectionShell>
  );
}
