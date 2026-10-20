import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import {
  useLocation,
  useNavigationType,
  useParams,
  useSearchParams,
} from 'react-router-dom';

import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import Logs from '../settings/Logs';
import { revealElement } from '../settings/logsLinks';
import { SectionHeader } from '../components/ui/section-header';
import SectionShell from '../navigation/SectionShell';
import AgentPageToolbar, { LastUsedMeta } from './components/AgentPageToolbar';
import GuardrailEvents from './components/GuardrailEvents';
import { Agent } from './types';

/**
 * An agent's Logs: its guardrail activity, then its log list under a Logs
 * heading. The usage charts
 * are its Analytics page (`AgentAnalytics`).
 */
export default function AgentLogs() {
  const { t } = useTranslation();
  const { agentId } = useParams();
  const token = useSelector(selectToken);
  const location = useLocation();
  const navigationType = useNavigationType();
  const [searchParams] = useSearchParams();
  const logsRef = useRef<HTMLElement>(null);

  const [agent, setAgent] = useState<Agent>();
  const [loadingAgent, setLoadingAgent] = useState<boolean>(true);

  const fetchAgent = async (agentId: string) => {
    setLoadingAgent(true);
    try {
      const response = await userService.getAgent(agentId ?? '', token);
      if (!response.ok) throw new Error('Failed to fetch Chatbots');
      const agent = await response.json();
      setAgent(agent);
    } catch (error) {
      console.error(error);
    } finally {
      setLoadingAgent(false);
    }
  };

  useEffect(() => {
    if (agentId) fetchAgent(agentId);
  }, [agentId, token]);

  // A drill-down (a docs-gap example, "See every docs gap") lands on Logs
  // further down this page: bring it into view. The label select replaces
  // the entry instead, so changing the filter in place doesn't scroll.
  const label = searchParams.get('label');
  const conversation = searchParams.get('conversation');
  useEffect(() => {
    if (navigationType === 'REPLACE') return;
    if (!label && !conversation) return;
    revealElement(logsRef.current, 'start');
  }, [location.key, label, conversation, navigationType]);

  const analytics = agent?.config?.analytics;

  return (
    <SectionShell>
      {agent && (
        <AgentPageToolbar
          name={agent.name}
          meta={<LastUsedMeta lastUsedAt={agent.last_used_at} />}
        />
      )}
      {agentId && (
        <>
          <GuardrailEvents agentId={agentId} />
          {/* The drill-down target (`#logs`): a named section, the peer of
              Guardrail activity. */}
          <section ref={logsRef} id="logs" className="mt-8 scroll-mt-4">
            <SectionHeader
              title={t('agents.pageHeader.tabs.logs')}
              description={t('agents.logs.description')}
              className="mb-4"
            />
            <Logs
              agentId={agentId}
              tableHeader={t('agents.logs.tableHeader')}
              analytics={
                agent
                  ? {
                      enabled: analytics?.enabled !== false,
                      tags: analytics?.tags ?? [],
                    }
                  : undefined
              }
            />
          </section>
        </>
      )}
    </SectionShell>
  );
}
