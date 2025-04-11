import React, { SyntheticEvent, useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import { Route, Routes, useNavigate } from 'react-router-dom';

import userService from '../api/services/userService';
import Copy from '../assets/copy-linear.svg';
import Edit from '../assets/edit.svg';
import Monitoring from '../assets/monitoring.svg';
import Trash from '../assets/red-trash.svg';
import Robot from '../assets/robot.svg';
import ThreeDots from '../assets/three-dots.svg';
import ContextMenu, { MenuOption } from '../components/ContextMenu';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import AgentLogs from './AgentLogs';
import NewAgent from './NewAgent';
import { Agent } from './types';

export default function Agents() {
  return (
    <Routes>
      <Route path="/" element={<AgentsList />} />
      <Route path="/new" element={<NewAgent mode="new" />} />
      <Route path="/edit/:agentId" element={<NewAgent mode="edit" />} />
      <Route path="/logs/:agentId" element={<AgentLogs />} />
    </Routes>
  );
}

function AgentsList() {
  const navigate = useNavigate();
  const token = useSelector(selectToken);

  const [userAgents, setUserAgents] = useState<Agent[]>([]);

  useEffect(() => {
    const getAgents = async () => {
      const response = await userService.getAgents(token);
      if (!response.ok) throw new Error('Failed to fetch agents');
      const data = await response.json();
      setUserAgents(data);
    };
    getAgents();
  }, [token]);
  return (
    <div className="p-4 md:p-12">
      <h1 className="mb-0 text-[40px] font-bold text-[#212121] dark:text-[#E0E0E0]">
        Agents
      </h1>
      <p className="mt-5 text-[15px] text-[#71717A] dark:text-[#949494]">
        Discover and create custom versions of DocsGPT that combine
        instructions, extra knowledge, and any combination of skills.
      </p>
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
      <div className="mt-8 flex flex-col gap-4">
        <div className="flex w-full items-center justify-between">
          <h2 className="text-[18px] font-semibold text-[#18181B] dark:text-[#E0E0E0]">
            Created by You
          </h2>
          <button
            className="rounded-full bg-purple-30 px-4 py-2 text-sm text-white hover:bg-violets-are-blue"
            onClick={() => navigate('/agents/new')}
          >
            New Agent
          </button>
        </div>
        <div className="flex w-full flex-wrap gap-4">
          {userAgents.map((agent, idx) => (
            <AgentCard key={idx} agent={agent} setUserAgents={setUserAgents} />
          ))}
        </div>
      </div>
    </div>
  );
}

function AgentCard({
  agent,
  setUserAgents,
}: {
  agent: Agent;
  setUserAgents: React.Dispatch<React.SetStateAction<Agent[]>>;
}) {
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const menuRef = useRef<HTMLDivElement>(null);
  const [isMenuOpen, setIsMenuOpen] = useState<boolean>(false);
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');

  const menuOptions: MenuOption[] = [
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
    {
      icon: Trash,
      label: 'Delete',
      onClick: () => setDeleteConfirmation('ACTIVE'),
      variant: 'danger',
      iconWidth: 12,
      iconHeight: 12,
    },
  ];

  const handleDelete = async (agentId: string) => {
    const response = await userService.deleteAgent(agentId, token);
    if (!response.ok) throw new Error('Failed to delete agent');
    const data = await response.json();
    setUserAgents((prevAgents) =>
      prevAgents.filter((prevAgent) => prevAgent.id !== data.id),
    );
  };
  return (
    <div className="relative flex h-44 w-48 flex-col justify-between rounded-[1.2rem] bg-[#F6F6F6] px-6 py-5 dark:bg-[#383838]">
      <div
        ref={menuRef}
        onClick={() => {
          setIsMenuOpen(true);
        }}
        className="absolute right-4 top-4 cursor-pointer"
      >
        <img src={ThreeDots} alt={'use-agent'} className="h-[19px] w-[19px]" />
        <ContextMenu
          isOpen={isMenuOpen}
          setIsOpen={setIsMenuOpen}
          options={menuOptions}
          anchorRef={menuRef}
          position="top-right"
          offset={{ x: 0, y: 0 }}
        />
      </div>
      <div className="w-full">
        <div className="flex w-full items-center gap-1 px-1">
          <img
            src={agent.image ?? Robot}
            alt={`${agent.name}`}
            className="h-7 w-7 rounded-full"
          />
          {agent.status === 'draft' && (
            <p className="text-xs text-black opacity-50 dark:text-[#E0E0E0]">{`(Draft)`}</p>
          )}
        </div>
        <div className="mt-2">
          <p
            title={agent.name}
            className="truncate px-1 text-[13px] font-semibold capitalize leading-relaxed text-[#020617] dark:text-[#E0E0E0]"
          >
            {agent.name}
          </p>
          <p className="mt-1 h-20 overflow-auto px-1 text-[12px] leading-relaxed text-[#64748B] dark:text-sonic-silver-light">
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
