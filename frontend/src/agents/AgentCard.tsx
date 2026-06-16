import { SyntheticEvent, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import userService from '../api/services/userService';
import Download from '../assets/download.svg';
import Duplicate from '../assets/duplicate.svg';
import Edit from '../assets/edit.svg';
import FolderIcon from '../assets/folder.svg';
import Link from '../assets/link-gray.svg';
import Monitoring from '../assets/monitoring.svg';
import Pin from '../assets/pin.svg';
import Trash from '../assets/red-trash.svg';
import ThreeDots from '../assets/three-dots.svg';
import UnPin from '../assets/unpin.svg';
import { Avatar } from '../components/ui/avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import ConfirmationModal from '../modals/ConfirmationModal';
import MoveToFolderModal from '../modals/MoveToFolderModal';
import { ActiveState } from '../models/misc';
import ShareToTeamModal from '../teams/ShareToTeamModal';

type AgentMenuOption = {
  icon: string | LucideIcon;
  label: string;
  onClick: (event: SyntheticEvent) => void;
  variant: 'default' | 'destructive';
  iconWidth?: number;
  iconHeight?: number;
};
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
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const userAgents = useSelector(selectAgents);

  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');
  const [moveModalState, setMoveModalState] = useState<ActiveState>('INACTIVE');
  const [shareModalOpen, setShareModalOpen] = useState(false);

  const menuOptionsConfig: Record<string, AgentMenuOption[]> = {
    template: [
      {
        icon: Duplicate,
        label: 'Duplicate',
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          handleDuplicate();
        },
        variant: 'default',
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
        variant: 'default',
        iconWidth: 14,
        iconHeight: 14,
      },
      {
        icon: Edit,
        label: 'Edit',
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          if (agent.agent_type === 'workflow') {
            navigate(`/agents/workflow/edit/${agent.id}`);
          } else {
            navigate(`/agents/edit/${agent.id}`);
          }
        },
        variant: 'default',
        iconWidth: 14,
        iconHeight: 14,
      },
      {
        icon: Download,
        label: t('agents.exportAgent'),
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          handleExport();
        },
        variant: 'default',
        iconWidth: 14,
        iconHeight: 14,
      },
      // Sharing is an owner-only action: only show it for agents the user
      // owns ('user'), not agents shared into their workspace by a team.
      ...(agent.ownership === 'user'
        ? [
            {
              icon: Users,
              label: t('agents.shareWithTeam'),
              onClick: (e: SyntheticEvent) => {
                e.stopPropagation();
                setShareModalOpen(true);
              },
              variant: 'default' as const,
              iconWidth: 14,
              iconHeight: 14,
            },
          ]
        : []),
      ...(agent.status === 'published'
        ? [
            {
              icon: agent.pinned ? UnPin : Pin,
              label: agent.pinned ? 'Unpin' : 'Pin agent',
              onClick: (e: SyntheticEvent) => {
                e.stopPropagation();
                togglePin();
              },
              variant: 'default' as const,
              iconWidth: 18,
              iconHeight: 18,
            },
          ]
        : []),
      {
        icon: FolderIcon,
        label: t('agents.folders.moveToFolder'),
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          setMoveModalState('ACTIVE');
        },
        variant: 'default',
        iconWidth: 16,
        iconHeight: 15,
      },
      {
        icon: Trash,
        label: 'Delete',
        onClick: (e: SyntheticEvent) => {
          e.stopPropagation();
          setDeleteConfirmation('ACTIVE');
        },
        variant: 'destructive',
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
        variant: 'default',
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
        variant: 'default',
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
        variant: 'destructive',
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
        navigate(agent.id ? `/agents/${agent.id}/c/new` : '/c/new');
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

  const handleExport = async () => {
    try {
      const response = await userService.exportAgent(agent.id ?? '', token);
      if (!response.ok) throw new Error('Failed to export agent');
      const yamlText = await response.text();
      const blob = new Blob([yamlText], { type: 'application/x-yaml' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${agent.slug || agent.name || 'agent'}.agent.yaml`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
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

  const handleMoveSuccess = (folderId: string | null) => {
    const updatedAgents = agents.map((prevAgent) => {
      if (prevAgent.id === agent.id) {
        return { ...prevAgent, folder_id: folderId ?? undefined };
      }
      return prevAgent;
    });
    updateAgents?.(updatedAgents);
  };
  return (
    <div
      role={agent.status === 'published' ? 'button' : undefined}
      tabIndex={agent.status === 'published' ? 0 : undefined}
      aria-label={agent.status === 'published' ? agent.name : undefined}
      className={`bg-muted hover:bg-accent focus-visible:ring-ring/50 focus-visible:border-ring relative flex h-44 flex-col justify-between rounded-2xl px-4 py-5 outline-none focus-visible:ring-[3px] sm:w-48 sm:px-6 ${agent.status === 'published' && 'cursor-pointer'}`}
      onClick={(e) => {
        e.stopPropagation();
        handleClick();
      }}
      onKeyDown={(e) => {
        if (
          agent.status === 'published' &&
          (e.key === 'Enter' || e.key === ' ')
        ) {
          e.preventDefault();
          handleClick();
        }
      }}
    >
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            onClick={(e) => e.stopPropagation()}
            className="absolute top-4 right-4 z-10 cursor-pointer"
            aria-label="agent-actions"
          >
            <img
              src={ThreeDots}
              alt={'use-agent'}
              className="h-[19px] w-[19px]"
            />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-[144px]">
          {menuOptions.map((option, index) => (
            <DropdownMenuItem
              key={index}
              variant={option.variant}
              onClick={(e) => e.stopPropagation()}
              onSelect={(event) => {
                option.onClick(event as unknown as SyntheticEvent);
              }}
            >
              {typeof option.icon === 'string' ? (
                <img
                  src={option.icon}
                  alt=""
                  width={option.iconWidth ?? 16}
                  height={option.iconHeight ?? 16}
                />
              ) : (
                <option.icon
                  size={Math.max(
                    option.iconWidth ?? 16,
                    option.iconHeight ?? 16,
                  )}
                  strokeWidth={1.75}
                  aria-hidden="true"
                />
              )}
              <span>{option.label}</span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <div className="w-full">
        <div className="flex w-full items-center gap-1 px-1">
          <Avatar
            src={agent.image}
            alt={`${agent.name}`}
            imgClassName="h-7 w-7 rounded-full object-contain"
          />
          {agent.status === 'draft' && (
            <p className="text-foreground text-xs opacity-50">{`(Draft)`}</p>
          )}
        </div>
        <div className="mt-2">
          <p
            title={agent.name}
            className="text-foreground truncate px-1 text-sm leading-relaxed font-semibold capitalize"
          >
            {agent.name}
          </p>
          <p className="dark:text-muted-foreground text-muted-foreground mt-1 h-20 overflow-auto px-1 text-xs leading-relaxed">
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
      <MoveToFolderModal
        modalState={moveModalState}
        setModalState={setMoveModalState}
        agentName={agent.name}
        agentId={agent.id ?? ''}
        currentFolderId={agent.folder_id}
        onMoveSuccess={handleMoveSuccess}
      />
      {shareModalOpen && agent.id && (
        <ShareToTeamModal
          resourceType="agent"
          resourceId={agent.id}
          resourceName={agent.name}
          onClose={() => setShareModalOpen(false)}
        />
      )}
    </div>
  );
}
