import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { Navigate, useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import SectionShell from '../navigation/SectionShell';
import { selectToken } from '../preferences/preferenceSlice';
import ConversationInsights from '../settings/insights/ConversationInsights';
import { insightsState } from '../settings/insights/format';
import { useConversationInsights } from '../settings/insights/useConversationInsights';
import TimeFilterSelect, {
  DEFAULT_TIME_FILTER,
  type TimeFilter,
} from '../settings/TimeFilterSelect';
import AgentPageToolbar, { LastUsedMeta } from './components/AgentPageToolbar';
import { agentLogsPath } from './paths';
import { Agent } from './types';

/**
 * An agent's Insights: what the decision model estimated about
 * its conversations, and the docs-gap report. The weekly docs-gaps
 * notification links here (`#docs-gaps`); while the server has insights off,
 * such a link goes on to the agent's Logs.
 */
export default function AgentInsights() {
  const { agentId } = useParams();
  const token = useSelector(selectToken);
  const [agent, setAgent] = useState<Agent>();
  const [timeFilter, setTimeFilter] = useState<TimeFilter>(DEFAULT_TIME_FILTER);
  const insights = useConversationInsights(agentId, timeFilter);
  const state = insightsState(insights.status, insights.data);

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

  if (state === 'serverOff')
    return <Navigate to={agentLogsPath(agentId)} replace />;

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
        <ConversationInsights
          state={state}
          data={insights.data}
          agentId={agentId}
          agent={agent}
          filterOption={timeFilter}
          onRetry={insights.retry}
          standalone
        />
      )}
    </SectionShell>
  );
}
