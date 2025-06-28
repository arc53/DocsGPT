import { useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import userService from '../api/services/userService';
import Robot from '../assets/robot.svg';
import ThreeDots from '../assets/three-dots.svg';
import ContextMenu, { MenuOption } from '../components/ContextMenu';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import {
  selectToken,
  setAgents,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import { Agent } from './types';

type AgentCardProps = {
  agent: Agent;
  agents: Agent[];
  menuOptions?: MenuOption[];
  onDelete?: (agentId: string) => void;
};

export default function AgentCard({
  agent,
  agents,
  menuOptions,
  onDelete,
}: AgentCardProps) {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);

  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');

  const menuRef = useRef<HTMLDivElement>(null);

  const handleCardClick = () => {
    if (agent.status === 'published') {
      dispatch(setSelectedAgent(agent));
      navigate('/');
    }
  };

  const defaultDelete = async (agentId: string) => {
    const response = await userService.deleteAgent(agentId, token);
    if (!response.ok) throw new Error('Failed to delete agent');
    const data = await response.json();
    dispatch(setAgents(agents.filter((prevAgent) => prevAgent.id !== data.id)));
  };

  return (
    <div
      className={`relative flex h-44 w-48 flex-col justify-between rounded-[1.2rem] bg-[#F6F6F6] px-6 py-5 hover:bg-[#ECECEC] dark:bg-[#383838] dark:hover:bg-[#383838]/80 ${
        agent.status === 'published' ? 'cursor-pointer' : ''
      }`}
      onClick={handleCardClick}
    >
      <div
        ref={menuRef}
        onClick={(e) => {
          e.stopPropagation();
          setIsMenuOpen(true);
        }}
        className="absolute top-4 right-4 z-10 cursor-pointer"
      >
        <img src={ThreeDots} alt="options" className="h-[19px] w-[19px]" />
        {menuOptions && (
          <ContextMenu
            isOpen={isMenuOpen}
            setIsOpen={setIsMenuOpen}
            options={menuOptions}
            anchorRef={menuRef}
            position="top-right"
            offset={{ x: 0, y: 0 }}
          />
        )}
      </div>

      <div className="w-full">
        <div className="flex w-full items-center gap-1 px-1">
          <img
            src={agent.image && agent.image.trim() !== '' ? agent.image : Robot}
            alt={`${agent.name}`}
            className="h-7 w-7 rounded-full object-contain"
          />
          {agent.status === 'draft' && (
            <p className="text-xs text-black opacity-50 dark:text-[#E0E0E0]">
              (Draft)
            </p>
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
          onDelete ? onDelete(agent.id || '') : defaultDelete(agent.id || '');
          setDeleteConfirmation('INACTIVE');
        }}
        cancelLabel="Cancel"
        variant="danger"
      />
    </div>
  );
}
