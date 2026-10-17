import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import Analytics from '../settings/Analytics';
import Logs from '../settings/Logs';
import SectionShell from '../navigation/SectionShell';
import AgentPageToolbar, { LastUsedMeta } from './components/AgentPageToolbar';
import GuardrailEvents from './components/GuardrailEvents';
import { Agent } from './types';

export default function AgentLogs() {
  const { t } = useTranslation();
  const { agentId } = useParams();
  const token = useSelector(selectToken);

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
          <Analytics agentId={agentId} />
          <GuardrailEvents agentId={agentId} />
          <div className="mt-8">
            <Logs
              agentId={agentId}
              tableHeader={t('agents.logs.tableHeader')}
            />
          </div>
        </>
      )}
    </SectionShell>
  );
}
