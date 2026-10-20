import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import SectionShell from '../navigation/SectionShell';
import { selectToken } from '../preferences/preferenceSlice';
import { InsightsSection } from '../settings/insights/ConversationInsights';
import TimeFilterSelect, {
  DEFAULT_TIME_FILTER,
  type TimeFilter,
} from '../settings/TimeFilterSelect';
import AgentPageToolbar, { LastUsedMeta } from './components/AgentPageToolbar';
import { Agent } from './types';

/**
 * An agent's Insights: what the decision model estimated about
 * its conversations, and the docs-gap report. The weekly docs-gaps
 * notification links here (`#docs-gaps`).
 */
export default function AgentInsights() {
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
      {agentId && (
        <InsightsSection
          agentId={agentId}
          agent={agent}
          filterOption={timeFilter}
          standalone
        />
      )}
    </SectionShell>
  );
}
