import { useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  Copy,
  Download,
  ExternalLink,
  Folder,
  Pencil,
  Pin,
  PinOff,
  Trash2,
  Users,
} from 'lucide-react';

import userService from '../api/services/userService';
import { Avatar } from '../components/ui/avatar';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { Modal } from '../components/ui/modal';
import ConfirmationModal from '../modals/ConfirmationModal';
import MoveToFolderModal from '../modals/MoveToFolderModal';
import { ActiveState } from '../models/misc';
import { useSidebarLevel } from '../navigation/SidebarLevelProvider';
import ShareToTeamModal from '../teams/ShareToTeamModal';
import {
  selectAgents,
  selectToken,
  setAgents,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import {
  agentChatPath,
  agentEditPath,
  agentLogsPath,
  sharedAgentPath,
} from './paths';
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
  // Opening an agent is a level change, so it goes through the sidebar's
  // navigator: the panel starts sliding on the click rather than waiting for
  // the editor to mount.
  const { goToLevel } = useSidebarLevel();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const userAgents = useSelector(selectAgents);

  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');
  const [moveModalState, setMoveModalState] = useState<ActiveState>('INACTIVE');
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const openEditor = () => {
    if (agent.agent_type === 'workflow') {
      goToLevel(agentEditPath(agent.id, true));
    } else {
      goToLevel(agentEditPath(agent.id));
    }
  };

  const pinOption: MenuOption = {
    icon: agent.pinned ? PinOff : Pin,
    label: agent.pinned ? t('agents.card.unpin') : t('agents.card.pin'),
    onClick: () => togglePin(),
  };

  const menuOptionsConfig: Record<string, MenuOption[]> = {
    template: [
      {
        icon: Copy,
        label: t('modals.prompts.duplicate'),
        onClick: () => handleDuplicate(),
      },
    ],
    user: [
      {
        icon: Activity,
        label: t('agents.form.buttons.logs'),
        onClick: () => goToLevel(agentLogsPath(agent.id)),
      },
      {
        icon: Pencil,
        label: t('agents.edit'),
        onClick: openEditor,
      },
      {
        icon: Download,
        label: t('agents.exportAgent'),
        onClick: () => handleExport(),
      },
      // Sharing is an owner-only action: only show it for agents the user
      // owns ('user'), not agents shared into their workspace by a team.
      ...(agent.ownership === 'user'
        ? [
            {
              icon: Users,
              label: t('agents.shareWithTeam'),
              onClick: () => setShareModalOpen(true),
            },
          ]
        : []),
      ...(agent.status === 'published' ? [pinOption] : []),
      {
        icon: Folder,
        label: t('agents.folders.moveToFolder'),
        onClick: () => setMoveModalState('ACTIVE'),
      },
      {
        icon: Trash2,
        label: t('agents.form.buttons.delete'),
        onClick: () => setDeleteConfirmation('ACTIVE'),
        variant: 'destructive',
      },
    ],
    // Agents shared with the user via a team. They don't own it, so only
    // non-destructive, non-owner actions are offered: open the config
    // (editors can save, viewers see it read-only) and pin for quick access.
    // Logs / Export / Share / Move-to-folder / Delete stay owner-only.
    team: [
      {
        icon: Pencil,
        label: t('agents.edit'),
        onClick: openEditor,
      },
      ...(agent.status === 'published' ? [pinOption] : []),
    ],
    shared: [
      {
        icon: ExternalLink,
        label: t('agents.card.open'),
        onClick: () => navigate(sharedAgentPath(agent.shared_token)),
      },
      pinOption,
      {
        icon: Trash2,
        label: t('agents.card.remove'),
        onClick: () => handleHideSharedAgent(),
        variant: 'destructive',
      },
    ],
  };
  const menuOptions = menuOptionsConfig[section] || [];

  const handleClick = () => {
    // Team-shared agents open/run exactly like the user's own published
    // agents (the run + GetAgent routes authorize team grantees server-side).
    if (section === 'user' || section === 'team') {
      if (agent.status === 'published') {
        dispatch(setSelectedAgent(agent));
        navigate(agent.id ? agentChatPath(agent.id) : '/c/new');
      }
    }
    if (section === 'shared') {
      navigate(sharedAgentPath(agent.shared_token));
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
      if (!response.ok) {
        const message = await response
          .json()
          .then((data) => data?.message)
          .catch(() => null);
        // Server-side refusals (e.g. a workflow referencing too many
        // resources) carry an actionable message; flag it so the catch can
        // tell it apart from a transport error like "Failed to fetch".
        const error = new Error(message || t('agents.exportAgentFailed'));
        error.name = 'ExportRefused';
        throw error;
      }
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
      setExportError(
        error instanceof Error && error.name === 'ExportRefused'
          ? error.message
          : t('agents.exportAgentFailed'),
      );
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
      className={`bg-muted hover:bg-accent focus-visible:ring-ring/50 focus-visible:border-ring relative flex h-44 flex-col justify-between rounded-2xl px-4 py-5 outline-none focus-visible:ring-3 sm:w-48 sm:px-6 ${agent.status === 'published' && 'cursor-pointer'}`}
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
      <ActionMenu
        options={menuOptions}
        triggerLabel={t('agents.card.actions')}
        align="end"
        className="absolute top-3 right-3 z-10"
      />
      {/* Team access badge — pinned to the top row, left of the ⋯ menu
          (right-11 clears the 28px trigger at right-3) so the two align. */}
      {agent.ownership === 'team' && (
        <Badge variant="neutral" className="absolute top-4 right-11 z-10">
          <Users size={11} aria-hidden="true" />
          {agent.team_access === 'editor'
            ? t('agents.teamBadge.editor')
            : t('agents.teamBadge.viewer')}
        </Badge>
      )}
      <div className="w-full">
        <div className="flex w-full items-center gap-1 px-1">
          <Avatar
            src={agent.image}
            alt={`${agent.name}`}
            size="sm"
            shape="circle"
            imgClassName="h-7 w-7 object-contain"
          />
          {agent.status === 'draft' && (
            <p className="text-foreground text-xs opacity-50">
              ({t('agents.card.draft')})
            </p>
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
        message={t('agents.deleteConfirmation')}
        modalState={deleteConfirmation}
        setModalState={setDeleteConfirmation}
        submitLabel={t('agents.form.buttons.delete')}
        handleSubmit={() => {
          handleDelete();
          setDeleteConfirmation('INACTIVE');
        }}
        cancelLabel={t('cancel')}
        variant="danger"
      />
      <Modal
        open={exportError !== null}
        onOpenChange={(open) => {
          if (!open) setExportError(null);
        }}
        title={t('agents.exportAgentFailed')}
        size="sm"
        footer={
          <Button
            type="button"
            onClick={() => setExportError(null)}
            size="lg"
            shape="pill"
          >
            {t('agents.close')}
          </Button>
        }
      >
        <p className="text-muted-foreground text-sm">{exportError}</p>
      </Modal>
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
