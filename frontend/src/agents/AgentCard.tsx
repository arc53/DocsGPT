import { SyntheticEvent, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import userService from '../api/services/userService';
import Duplicate from '../assets/duplicate.svg';
import Edit from '../assets/edit.svg';
import Link from '../assets/link-gray.svg';
import Monitoring from '../assets/monitoring.svg';
import Pin from '../assets/pin.svg';
import Trash from '../assets/red-trash.svg';
import Robot from '../assets/robot.svg';
import ThreeDots from '../assets/three-dots.svg';
import UnPin from '../assets/unpin.svg';
import ContextMenu, { MenuOption } from '../components/ContextMenu';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import {
  selectAgents,
  selectToken,
  setAgents,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import { Agent } from './types';

type AgentCardProps = {
  agent: Agent;
  agents: Agent[];
  updateAgents?: (agents: Agent[]) => void;
  section: string;
};

export default function AgentCard({
  agent,
  agents,
  updateAgents,
  section,
}: AgentCardProps) {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const userAgents = useSelector(selectAgents);

  const [isMenuOpen, setIsMenuOpen] = useState<boolean>(false);
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');

  const menuRef = useRef<HTMLDivElement>(null);

  const menuOptionsConfig: Record<string, MenuOption[]> = {
    template: [
      {
        icon: Duplicate,
        label: 'Duplicate',
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          handleDuplicate();
        },
        variant: 'primary',
        iconWidth: 18,
        iconHeight: 18,
      },
    ],
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

  const handleDelete = async () => {
    try {
      const response = await userService.deleteAgent(agent.id ?? '', token);
      if (!response.ok) throw new Error('Failed to delete agent');
      const updatedAgents = agents.filter(
        (prevAgent) => prevAgent.id !== agent.id,
      );
      updateAgents?.(updatedAgents);
    } catch (error) {
      console.error('Error:', error);
    }
  };

  const handleDuplicate = async () => {
    try {
      const response = await userService.adoptAgent(agent.id ?? '', token);
      if (!response.ok) throw new Error('Failed to duplicate agent');
      const data = await response.json();
      if (userAgents) {
        const updatedAgents = [...userAgents, data.agent];
        dispatch(setAgents(updatedAgents));
      } else dispatch(setAgents([data.agent]));
    } catch (error) {
      console.error('Error:', error);
    }
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
          handleDelete();
          setDeleteConfirmation('INACTIVE');
        }}
        cancelLabel="Cancel"
        variant="danger"
      />
    </div>
  );
}
