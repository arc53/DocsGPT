import { useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  Copy,
  Download,
  Eye,
  Folder,
  FolderInput,
  Pencil,
  Pin,
  PinOff,
  Trash2,
  Users,
} from 'lucide-react';

import { TEAM_ERROR_KEYS } from '../api/services/teamsService';
import userService from '../api/services/userService';
import RoleMeta, { showsRole } from '../components/RoleMeta';
import { canMoveToFolder } from '../components/folders/folderFiling';
// Safe on a store without the workspace slice (read as Personal).
import {
  selectCanEditFolders as selectCanCreate,
  selectFoldersInTeam as selectInTeam,
} from '../components/folders/folderWorkspace';
import MoveToFolderModal from '../components/folders/MoveToFolderModal';
import { MetaItem, MetaLine } from '../components/ui/meta-line';
import { Avatar } from '../components/ui/avatar';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Card,
  CardDescription,
  CardFooter,
  CardTitle,
} from '../components/ui/card';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { Modal } from '../components/ui/modal';
import ConfirmationModal from '../modals/ConfirmationModal';
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
import { can, canOpenShare } from '../utils/accessUtils';
import { cn } from '@/lib/utils';
import { downloadBlob } from '../utils/browserUtils';
import CreatorMeta, { showsCreator } from '../workspace/CreatorMeta';
import SharedFromMeta, { showsSharedFrom } from '../workspace/SharedFromMeta';
import { useMoveToWorkspace } from '../workspace/move/useMoveToWorkspace';
import { canAgent } from './agentAccess';
import { Agent } from './types';

type AgentCardProps = {
  agent: Agent;
  agents: Agent[];
  updateAgents?: (agents: Agent[]) => void;
  /** The list section it is in (`agents.config`). */
  section: string;
  /**
   * The caller's folder trail for the agent ("Customer-facing › EU"), shown
   * as a meta item where the list is flat (a search across folders).
   */
  folderLabel?: string;
  /** The agent moved to another workspace: reload the list it left. */
  onMovedToWorkspace?: () => void;
};

/**
 * An agent's tile in the agent list: its avatar, name and description, a
 * meta line (its folder in a flat list; who added a team agent or owns a
 * shared one; the reader's role on a shared one) and its ⋯, built from what
 * the reader's role allows.
 */
export default function AgentCard({
  agent,
  agents,
  updateAgents,
  section,
  folderLabel,
  onMovedToWorkspace,
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
  const canCreate = useSelector(selectCanCreate);
  const inTeam = useSelector(selectInTeam);
  const moveToWorkspace = useMoveToWorkspace('agent');

  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');
  const [moveOpen, setMoveOpen] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string>();

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

  // Move to team… / Move to Personal…, when the agent may move.
  const moveOut = agent.id
    ? moveToWorkspace.menuOption(
        { ...agent, id: agent.id },
        { onMoved: onMovedToWorkspace },
      )
    : null;

  const ownedMenu: MenuOption[] = [
    ...(canAgent(agent, 'view_logs')
      ? [
          {
            icon: Activity,
            label: t('agents.form.buttons.logs'),
            onClick: () => goToLevel(agentLogsPath(agent.id)),
          },
        ]
      : []),
    // Opening the editor is `view`; a role that can't `edit` gets it as View.
    ...(can(agent, 'view')
      ? [
          can(agent, 'edit')
            ? { icon: Pencil, label: t('agents.edit'), onClick: openEditor }
            : { icon: Eye, label: t('agents.view'), onClick: openEditor },
        ]
      : []),
    ...(can(agent, 'export')
      ? [
          {
            icon: Download,
            label: t('agents.exportAgent'),
            onClick: () => handleExport(),
          },
        ]
      : []),
    ...(canOpenShare(agent)
      ? [
          {
            icon: Users,
            label: t('agents.shareWithTeam'),
            onClick: () => setShareModalOpen(true),
          },
        ]
      : []),
    ...(canAgent(agent, 'pin') ? [pinOption] : []),
    // A team's agent is filed only in the team's folders, never in yours.
    ...(can(agent, 'move_folder') && canMoveToFolder(agent, inTeam)
      ? [
          {
            icon: FolderInput,
            label: t('folders.moveToFolder'),
            onClick: () => setMoveOpen(true),
          },
        ]
      : []),
    ...(moveOut ? [moveOut] : []),
    ...(can(agent, 'delete')
      ? [
          {
            icon: Trash2,
            label: t('agents.form.buttons.delete'),
            onClick: () => setDeleteConfirmation('ACTIVE'),
            variant: 'destructive' as const,
            separatorBefore: true,
          },
        ]
      : []),
  ];

  const menuOptionsConfig: Record<string, MenuOption[]> = {
    // Duplicating a template creates an agent here: Personal, or Editor and
    // up in a team.
    template: canCreate
      ? [
          {
            icon: Copy,
            label: t('modals.prompts.duplicate'),
            onClick: () => handleDuplicate(),
          },
        ]
      : [],
    // The workspace's agents and Shared with you share one menu, built from
    // what the caller's role allows on this agent (`allowed_actions` from the
    // API). Editors get Logs, Edit, Export and Pin; viewers only Pin. Share,
    // Move and Delete stay with the owner unless the owner's switches widen
    // them.
    user: ownedMenu,
    sharedWithYou: ownedMenu,
    // Another team's agent: its `allowed_actions` hold only use and pin.
    teamShared: ownedMenu,
    // Discovered (link-opened) agents: the card itself opens the agent.
    shared: [
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

  // The workspace's agents and the ones shared with the caller or the team
  // open into a chat once published.
  const opensChat =
    section === 'user' ||
    section === 'sharedWithYou' ||
    section === 'teamShared';

  const handleClick = () => {
    // Shared agents open and run like the caller's own published ones (the
    // run and GetAgent routes authorize them server-side).
    if (opensChat) {
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
          .then((data) =>
            // A locked team's agents stay in; say so in the app's words.
            data?.error === 'team_locked'
              ? t(TEAM_ERROR_KEYS.team_locked)
              : data?.message,
          )
          .catch(() => null);
        // Server-side refusals (e.g. a workflow referencing too many
        // resources) carry an actionable message; flag it so the catch can
        // tell it apart from a transport error like "Failed to fetch".
        const error = new Error(message || t('agents.exportAgentFailed'));
        error.name = 'ExportRefused';
        throw error;
      }
      const yamlText = await response.text();
      downloadBlob(
        new Blob([yamlText], { type: 'application/x-yaml' }),
        `${agent.slug || agent.name || 'agent'}.agent.yaml`,
      );
    } catch (error) {
      console.error('Error:', error);
      setExportError(
        error instanceof Error && error.name === 'ExportRefused'
          ? error.message
          : t('agents.exportAgentFailed'),
      );
    }
  };

  // Returned to ConfirmationModal: it stays pending while this runs and
  // keeps a failure in the dialog (the server's message when it gives one).
  const handleDelete = async () => {
    setDeleteError(undefined);
    const response = await userService.deleteAgent(agent.id ?? '', token);
    if (!response.ok) {
      const message = await response
        .json()
        .then((data: { message?: string }) => data?.message)
        .catch(() => null);
      setDeleteError(message || undefined);
      throw new Error(message || 'Failed to delete agent');
    }
    const updatedAgents = agents.filter(
      (prevAgent) => prevAgent.id !== agent.id,
    );
    updateAgents?.(updatedAgents);
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
  // Same rule as handleClick: a Discovered card always opens, the
  // workspace's or a shared agent once it's published.
  const canOpen =
    section === 'shared' || (opensChat && agent.status === 'published');
  // Who added a team agent or owns a shared one, the reader's role on a
  // shared one, and the team another team's agent comes from; nothing on the
  // caller's own.
  const creator = showsCreator(agent);
  const role = showsRole(agent);
  const sharedFrom = showsSharedFrom(agent);
  const hasMeta = creator || role || sharedFrom || Boolean(folderLabel);
  const title = (
    <CardTitle title={agent.name} className="truncate">
      {agent.name}
    </CardTitle>
  );
  return (
    // DESIGN "A clickable card that holds a link": a stretched button on the
    // title opens the agent; the menu and badge sit above it as siblings.
    <Card
      variant="filled"
      interactive={canOpen ? 'within' : false}
      padding="lg"
      className="relative h-44 gap-1"
    >
      <div className="mb-1 flex w-full items-center gap-2 px-1">
        {/* Decorative: the title beside it names the agent. */}
        <Avatar
          src={agent.image}
          alt=""
          size="xs"
          shape="circle"
          imgClassName="size-7 object-contain"
        />
        {/* A state, so a pill (the workflow builder's Draft is the same). */}
        {agent.status === 'draft' && (
          <Badge variant="neutral">{t('agents.card.draft')}</Badge>
        )}
      </div>
      {canOpen ? (
        <button
          type="button"
          onClick={handleClick}
          className="w-full min-w-0 cursor-pointer px-1 text-left outline-none after:absolute after:inset-0 after:rounded-2xl"
        >
          {title}
        </button>
      ) : (
        <div className="px-1">{title}</div>
      )}
      <CardDescription
        size="xs"
        // A meta line (its folder, who added it, a role) takes the third line.
        className={cn('mx-1', hasMeta ? 'line-clamp-2' : 'line-clamp-3')}
      >
        {agent.description}
      </CardDescription>
      {/* The agent's folder, who added it and the reader's role are facts
          about it: the meta line, not pills. */}
      {hasMeta ? (
        <CardFooter className="mx-1 mt-auto">
          <MetaLine>
            {folderLabel ? (
              <MetaItem icon={<Folder />} title={folderLabel}>
                {folderLabel}
              </MetaItem>
            ) : null}
            {creator ? <CreatorMeta item={agent} /> : null}
            {sharedFrom ? <SharedFromMeta item={agent} /> : null}
            {role ? <RoleMeta item={agent} /> : null}
          </MetaLine>
        </CardFooter>
      ) : null}
      {/* After the open target, so Tab reaches the agent before its menu. */}
      {menuOptions.length > 0 && (
        <div className="absolute top-3 right-3 z-10">
          <ActionMenu
            options={menuOptions}
            triggerLabel={t('agents.card.actions')}
            align="end"
          />
        </div>
      )}
      <ConfirmationModal
        message={t('agents.deleteConfirmation', {
          interpolation: { escapeValue: false },
          name: agent.name,
        })}
        description={t('agents.deleteConsequence')}
        modalState={deleteConfirmation}
        setModalState={setDeleteConfirmation}
        submitLabel={t('agents.form.buttons.delete')}
        handleSubmit={handleDelete}
        error={deleteError ?? t('agents.deleteFailed')}
        cancelLabel={t('cancel')}
        variant="destructive"
      />
      <Modal
        mobileVariant="dialog"
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
      {moveOpen && agent.id ? (
        <MoveToFolderModal
          open
          onOpenChange={setMoveOpen}
          kind="agent"
          subject={{
            kind: 'items',
            ids: [agent.id],
            name: agent.name,
            folderId: agent.folder_id ?? null,
          }}
          onMoved={handleMoveSuccess}
        />
      ) : null}
      {shareModalOpen && agent.id && (
        <ShareToTeamModal
          resourceType="agent"
          resourceId={agent.id}
          resourceName={agent.name}
          onClose={() => setShareModalOpen(false)}
          onMoved={onMovedToWorkspace}
        />
      )}
      {moveToWorkspace.dialog}
    </Card>
  );
}
