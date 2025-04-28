import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import { selectToken } from '../preferences/preferenceSlice';
import Analytics from '../settings/Analytics';
import Logs from '../settings/Logs';
import Spinner from '../components/Spinner';
import { Agent } from './types';

export default function AgentLogs() {
  const navigate = useNavigate();
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
    <div className="p-4 md:p-12">
      <div className="flex items-center gap-3 px-4">
        <button
          className="rounded-full border p-3 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
          onClick={() => navigate('/agents')}
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
        </button>
        <p className="mt-px text-sm font-semibold text-eerie-black dark:text-bright-gray">
          Back to all agents
        </p>
      </div>
      <div className="mt-5 flex w-full flex-wrap items-center justify-between gap-2 px-4">
        <h1 className="m-0 text-[40px] font-bold text-[#212121] dark:text-white">
          Agent Logs
        </h1>
      </div>
      <div className="mt-6 flex flex-col gap-3 px-4">
        <h2 className="text-sm font-semibold text-black dark:text-[#E0E0E0]">
          Agent Name
        </h2>
        {agent && (
          <p className="text-[#28292E] dark:text-[#E0E0E0]">{agent.name}</p>
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
          {' '}
          <Spinner />
        </div>
      ) : (
        agent && <Logs agentId={agentId} tableHeader="Agent endpoint logs" />
      )}
    </div>
  );
}
