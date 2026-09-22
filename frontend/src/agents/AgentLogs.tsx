import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import Analytics from '../settings/Analytics';
import Logs from '../settings/Logs';
import { formatDateTime } from '../utils/dateTimeUtils';
import { CurrentSectionHeader } from '../navigation/SectionPageHeader';
import SectionPills from '../navigation/SectionPills';
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
    <div className="h-full overflow-auto p-4 md:p-12">
      <div className="mx-auto w-full max-w-6xl">
        <CurrentSectionHeader />
        <SectionPills className="mt-4" />
        <div className="mt-6 flex flex-col gap-3">
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
        {agentId && (
          <>
            <Analytics agentId={agentId} />
            <GuardrailEvents agentId={agentId} />
            <Logs
              agentId={agentId}
              tableHeader={t('agents.logs.tableHeader')}
            />
          </>
        )}
      </div>
    </div>
  );
}
