import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import Spinner from '../components/Spinner';
import { selectToken } from '../preferences/preferenceSlice';
import Analytics from '../settings/Analytics';
import Logs from '../settings/Logs';
import { formatDateTime } from '../utils/dateTimeUtils';
import AgentPageHeader from './AgentPageHeader';
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

  const agentEditPath =
    agent?.agent_type === 'workflow'
      ? `/agents/workflow/edit/${agentId}`
      : `/agents/edit/${agentId}`;

  return (
    <div className="p-4 pt-4 md:p-12 md:pt-4">
      <AgentPageHeader
        agentId={agentId}
        agentName={agent?.name}
        agentEditPath={agentEditPath}
        currentPage="logs"
        className="px-4"
      />
      <div className="mt-6 flex flex-col gap-3 px-4">
        {agent && (
          <div className="flex flex-col gap-1">
            <p className="text-foreground">{agent.name}</p>
            <p className="text-muted-foreground text-xs">
              {agent.last_used_at
                ? t('agents.logs.lastUsedAt') +
                  ' ' +
                  formatDateTime(agent.last_used_at)
                : t('agents.logs.noUsageHistory')}
            </p>
          </div>
        )}
      </div>
      {loadingAgent ? (
        <div className="flex h-[345px] w-full items-center justify-center">
          <Spinner />
        </div>
      ) : (
        agent && <Analytics agentId={agent.id} />
      )}
      {loadingAgent ? (
        <div className="flex h-[55vh] w-full items-center justify-center">
          <Spinner />
        </div>
      ) : (
        agent && (
          <Logs agentId={agent.id} tableHeader={t('agents.logs.tableHeader')} />
        )
      )}
    </div>
  );
}
