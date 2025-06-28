import { SyntheticEvent, useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Route, Routes, useNavigate } from 'react-router-dom';

import userService from '../api/services/userService';
import Edit from '../assets/edit.svg';
import Link from '../assets/link-gray.svg';
import Monitoring from '../assets/monitoring.svg';
import Pin from '../assets/pin.svg';
import Trash from '../assets/red-trash.svg';
import Robot from '../assets/robot.svg';
import ThreeDots from '../assets/three-dots.svg';
import UnPin from '../assets/unpin.svg';
import ContextMenu, { MenuOption } from '../components/ContextMenu';
import Spinner from '../components/Spinner';
import {
  setConversation,
  updateConversationId,
} from '../conversation/conversationSlice';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import {
  selectAgents,
  selectSelectedAgent,
  selectSharedAgents,
  selectToken,
  setAgents,
  setSelectedAgent,
  setSharedAgents,
} from '../preferences/preferenceSlice';
import AgentLogs from './AgentLogs';
import NewAgent from './NewAgent';
import SharedAgent from './SharedAgent';
import { Agent } from './types';

export default function Agents() {
  return (
    <Routes>
      <Route path="/" element={<AgentsList />} />
      <Route path="/new" element={<NewAgent mode="new" />} />
      <Route path="/edit/:agentId" element={<NewAgent mode="edit" />} />
      <Route path="/logs/:agentId" element={<AgentLogs />} />
      <Route path="/shared/:agentId" element={<SharedAgent />} />
    </Routes>
  );
}

const sectionConfig = {
  user: {
    title: 'By me',
    description: 'Agents created or published by you',
    showNewAgentButton: true,
    emptyStateDescription: 'You don’t have any created agents yet',
  },
  shared: {
    title: 'Shared with me',
    description: 'Agents imported by using a public link',
    showNewAgentButton: false,
    emptyStateDescription: 'No shared agents found',
  },
};

function AgentsList() {
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const agents = useSelector(selectAgents);
  const sharedAgents = useSelector(selectSharedAgents);
  const selectedAgent = useSelector(selectSelectedAgent);

  const [loadingUserAgents, setLoadingUserAgents] = useState<boolean>(true);
  const [loadingSharedAgents, setLoadingSharedAgents] = useState<boolean>(true);

  const getAgents = async () => {
    try {
      setLoadingUserAgents(true);
      const response = await userService.getAgents(token);
      if (!response.ok) throw new Error('Failed to fetch agents');
      const data = await response.json();
      dispatch(setAgents(data));
      setLoadingUserAgents(false);
    } catch (error) {
      console.error('Error:', error);
      setLoadingUserAgents(false);
    }
  };

  const getSharedAgents = async () => {
    try {
      setLoadingSharedAgents(true);
      const response = await userService.getSharedAgents(token);
      if (!response.ok) throw new Error('Failed to fetch shared agents');
      const data = await response.json();
      dispatch(setSharedAgents(data));
      setLoadingSharedAgents(false);
    } catch (error) {
      console.error('Error:', error);
      setLoadingSharedAgents(false);
    }
  };

  useEffect(() => {
    getAgents();
    getSharedAgents();
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
      {/* Premade agents section */}
      {/* <div className="mt-6">
        <h2 className="text-[18px] font-semibold text-[#18181B] dark:text-[#E0E0E0]">
          Premade by DocsGPT
        </h2>
        <div className="mt-4 flex w-full flex-wrap gap-4">
          {Array.from({ length: 5 }, (_, index) => (
            <div
              key={index}
              className="relative flex h-44 w-48 flex-col justify-between rounded-[1.2rem] bg-[#F6F6F6] px-6 py-5 dark:bg-[#383838]"
            >
              <button onClick={() => {}} className="absolute right-4 top-4">
                <img
                  src={Copy}
                  alt={'use-agent'}
                  className="h-[19px] w-[19px]"
                />
              </button>
              <div className="w-full">
                <div className="flex w-full items-center px-1">
                  <img
                    src={Robot}
                    alt="agent-logo"
                    className="h-7 w-7 rounded-full"
                  />
                </div>
                <div className="mt-2">
                  <p
                    title={''}
                    className="truncate px-1 text-[13px] font-semibold capitalize leading-relaxed text-raisin-black-light dark:text-bright-gray"
                  >
                    {}
                  </p>
                  <p className="mt-1 h-20 overflow-auto px-1 text-[12px] leading-relaxed text-old-silver dark:text-sonic-silver-light">
                    {}
                  </p>
                </div>
              </div>
              <div className="absolute bottom-4 right-4"></div>
            </div>
          ))}
        </div>
      </div> */}
      <AgentSection
        agents={agents ?? []}
        updateAgents={(updatedAgents) => {
          dispatch(setAgents(updatedAgents));
        }}
        loading={loadingUserAgents}
        section="user"
      />
      <AgentSection
        agents={sharedAgents ?? []}
        updateAgents={(updatedAgents) => {
          dispatch(setSharedAgents(updatedAgents));
        }}
        loading={loadingSharedAgents}
        section="shared"
      />
    </div>
  );
}

function AgentSection({
  agents,
  updateAgents,
  loading,
  section,
}: {
  agents: Agent[];
  updateAgents?: (agents: Agent[]) => void;
  loading: boolean;
  section: keyof typeof sectionConfig;
}) {
  const navigate = useNavigate();
  return (
    <div className="mt-8 flex flex-col gap-4">
      <div className="flex w-full items-center justify-between">
        <div className="flex flex-col gap-2">
          <h2 className="text-[18px] font-semibold text-[#18181B] dark:text-[#E0E0E0]">
            {sectionConfig[section].title}
          </h2>
          <p className="text-[13px] text-[#71717A]">
            {sectionConfig[section].description}
          </p>
        </div>
        {sectionConfig[section].showNewAgentButton && (
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
            {agents.map((agent, idx) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                agents={agents}
                updateAgents={updateAgents}
                section={section}
              />
            ))}
          </div>
        ) : (
          <div className="flex h-72 w-full flex-col items-center justify-center gap-3 text-base text-[#18181B] dark:text-[#E0E0E0]">
            <p>{sectionConfig[section].emptyStateDescription}</p>
            {sectionConfig[section].showNewAgentButton && (
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

function AgentCard({
  agent,
  agents,
  updateAgents,
  section,
}: {
  agent: Agent;
  agents: Agent[];
  updateAgents?: (agents: Agent[]) => void;
  section: keyof typeof sectionConfig;
}) {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);

  const [isMenuOpen, setIsMenuOpen] = useState<boolean>(false);
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');

  const menuRef = useRef<HTMLDivElement>(null);

  const togglePin = async () => {
    try {
      const response = await userService.togglePinAgent(agent.id ?? '', token);
      if (!response.ok) throw new Error('Failed to pin agent');
      const updatedAgents = agents.map((prevAgent) => {
        if (prevAgent.id === agent.id)
          return { ...prevAgent, pinned: !prevAgent.pinned };
        return prevAgent;
      });
      updateAgents?.(updatedAgents);
    } catch (error) {
      console.error('Error:', error);
    }
  };

  const handleHideSharedAgent = async () => {
    try {
      const response = await userService.removeSharedAgent(
        agent.id ?? '',
        token,
      );
      if (!response.ok) throw new Error('Failed to hide shared agent');
      const updatedAgents = agents.filter(
        (prevAgent) => prevAgent.id !== agent.id,
      );
      updateAgents?.(updatedAgents);
    } catch (error) {
      console.error('Error:', error);
    }
  };

  const menuOptionsConfig: Record<string, MenuOption[]> = {
    user: [
      {
        icon: Monitoring,
        label: 'Logs',
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          navigate(`/agents/logs/${agent.id}`);
        },
        variant: 'primary',
        iconWidth: 14,
        iconHeight: 14,
      },
      {
        icon: Edit,
        label: 'Edit',
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          navigate(`/agents/edit/${agent.id}`);
        },
        variant: 'primary',
        iconWidth: 14,
        iconHeight: 14,
      },
      ...(agent.status === 'published'
        ? [
            {
              icon: agent.pinned ? UnPin : Pin,
              label: agent.pinned ? 'Unpin' : 'Pin agent',
              onClick: (e: SyntheticEvent) => {
                e.stopPropagation();
                togglePin();
              },
              variant: 'primary' as const,
              iconWidth: 18,
              iconHeight: 18,
            },
          ]
        : []),
      {
        icon: Trash,
        label: 'Delete',
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          setDeleteConfirmation('ACTIVE');
        },
        variant: 'danger',
        iconWidth: 13,
        iconHeight: 13,
      },
    ],
    shared: [
      {
        icon: Link,
        label: 'Open',
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          navigate(`/agents/shared/${agent.shared_token}`);
        },
        variant: 'primary',
        iconWidth: 12,
        iconHeight: 12,
      },
      {
        icon: agent.pinned ? UnPin : Pin,
        label: agent.pinned ? 'Unpin' : 'Pin agent',
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          togglePin();
        },
        variant: 'primary',
        iconWidth: 18,
        iconHeight: 18,
      },
      {
        icon: Trash,
        label: 'Remove',
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          handleHideSharedAgent();
        },
        variant: 'danger',
        iconWidth: 13,
        iconHeight: 13,
      },
    ],
  };

  const menuOptions = menuOptionsConfig[section] || [];

  const handleClick = () => {
    if (section === 'user') {
      if (agent.status === 'published') {
        dispatch(setSelectedAgent(agent));
        navigate(`/`);
      }
    }
    if (section === 'shared') {
      navigate(`/agents/shared/${agent.shared_token}`);
    }
  };

  const handleDelete = async (agentId: string) => {
    const response = await userService.deleteAgent(agentId, token);
    if (!response.ok) throw new Error('Failed to delete agent');
    const data = await response.json();
    dispatch(setAgents(agents.filter((prevAgent) => prevAgent.id !== data.id)));
  };
  return (
    <div
      className={`relative flex h-44 w-full flex-col justify-between rounded-[1.2rem] bg-[#F6F6F6] px-6 py-5 hover:bg-[#ECECEC] md:w-48 dark:bg-[#383838] dark:hover:bg-[#383838]/80 ${agent.status === 'published' && 'cursor-pointer'}`}
      onClick={(e) => {
        e.stopPropagation();
        handleClick();
      }}
    >
      <div
        ref={menuRef}
        onClick={(e) => {
          e.stopPropagation();
          setIsMenuOpen(true);
        }}
        className="absolute top-4 right-4 z-10 cursor-pointer"
      >
        <img src={ThreeDots} alt={'use-agent'} className="h-[19px] w-[19px]" />
        <ContextMenu
          isOpen={isMenuOpen}
          setIsOpen={setIsMenuOpen}
          options={menuOptions}
          anchorRef={menuRef}
          position="bottom-right"
          offset={{ x: 0, y: 0 }}
        />
      </div>
      <div className="w-full">
        <div className="flex w-full items-center gap-1 px-1">
          <img
            src={agent.image && agent.image.trim() !== '' ? agent.image : Robot}
            alt={`${agent.name}`}
            className="h-7 w-7 rounded-full object-contain"
          />
          {agent.status === 'draft' && (
            <p className="text-xs text-black opacity-50 dark:text-[#E0E0E0]">{`(Draft)`}</p>
          )}
        </div>
        <div className="mt-2">
          <p
            title={agent.name}
            className="truncate px-1 text-[13px] leading-relaxed font-semibold text-[#020617] capitalize dark:text-[#E0E0E0]"
          >
            {agent.name}
          </p>
          <p className="dark:text-sonic-silver-light mt-1 h-20 overflow-auto px-1 text-[12px] leading-relaxed text-[#64748B]">
            {agent.description}
          </p>
        </div>
      </div>
      <ConfirmationModal
        message="Are you sure you want to delete this agent?"
        modalState={deleteConfirmation}
        setModalState={setDeleteConfirmation}
        submitLabel="Delete"
        handleSubmit={() => {
          handleDelete(agent.id || '');
          setDeleteConfirmation('INACTIVE');
        }}
        cancelLabel="Cancel"
        variant="danger"
      />
    </div>
  );
}
