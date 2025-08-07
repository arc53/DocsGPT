import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import Spinner from '../components/Spinner';
import {
  setConversation,
  updateConversationId,
} from '../conversation/conversationSlice';
import {
  selectSelectedAgent,
  selectToken,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import AgentCard from './AgentCard';
import { agentSectionsConfig } from './agents.config';
import { Agent } from './types';

export default function AgentsList() {
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const selectedAgent = useSelector(selectSelectedAgent);

  useEffect(() => {
    dispatch(setConversation([]));
    dispatch(
      updateConversationId({
        query: { conversationId: null },
      }),
    );
    if (selectedAgent) dispatch(setSelectedAgent(null));
  }, [token]);
  return (
    <div className="p-4 md:p-12">
      <h1 className="text-eerie-black mb-0 text-[40px] font-bold dark:text-[#E0E0E0]">
        Agents
      </h1>
      <p className="dark:text-gray-4000 mt-5 text-[15px] text-[#71717A]">
        Discover and create custom versions of DocsGPT that combine
        instructions, extra knowledge, and any combination of skills
      </p>
      {agentSectionsConfig.map((sectionConfig) => (
        <AgentSection key={sectionConfig.id} config={sectionConfig} />
      ))}
    </div>
  );
}

function AgentSection({
  config,
}: {
  config: (typeof agentSectionsConfig)[number];
}) {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const agents = useSelector(config.selectData);

  const [loading, setLoading] = useState(true);

  const updateAgents = (updatedAgents: Agent[]) => {
    dispatch(config.updateAction(updatedAgents));
  };

  useEffect(() => {
    const getAgents = async () => {
      setLoading(true);
      try {
        const response = await config.fetchAgents(token);
        if (!response.ok)
          throw new Error(`Failed to fetch ${config.id} agents`);
        const data = await response.json();
        dispatch(config.updateAction(data));
      } catch (error) {
        console.error(`Error fetching ${config.id} agents:`, error);
        dispatch(config.updateAction([]));
      } finally {
        setLoading(false);
      }
    };
    getAgents();
  }, [token, config, dispatch]);
  return (
    <div className="mt-8 flex flex-col gap-4">
      <div className="flex w-full items-center justify-between">
        <div className="flex flex-col gap-2">
          <h2 className="text-[18px] font-semibold text-[#18181B] dark:text-[#E0E0E0]">
            {config.title}
          </h2>
          <p className="text-[13px] text-[#71717A]">{config.description}</p>
        </div>
        {config.showNewAgentButton && (
          <button
            className="bg-purple-30 hover:bg-violets-are-blue rounded-full px-4 py-2 text-sm text-white"
            onClick={() => navigate('/agents/new')}
          >
            New Agent
          </button>
        )}
      </div>
      <div>
        {loading ? (
          <div className="flex h-72 w-full items-center justify-center">
            <Spinner />
          </div>
        ) : agents && agents.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 sm:flex sm:flex-wrap">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                agents={agents}
                updateAgents={updateAgents}
                section={config.id}
              />
            ))}
          </div>
        ) : (
          <div className="flex h-72 w-full flex-col items-center justify-center gap-3 text-base text-[#18181B] dark:text-[#E0E0E0]">
            <p>{config.emptyStateDescription}</p>
            {config.showNewAgentButton && (
              <button
                className="bg-purple-30 hover:bg-violets-are-blue ml-2 rounded-full px-4 py-2 text-sm text-white"
                onClick={() => navigate('/agents/new')}
              >
                New Agent
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
