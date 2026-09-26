import {
  Bot,
  Check,
  ChevronDown,
  PanelLeft,
  Pencil,
  Share,
  SquarePen,
  Trash2,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import ProfileButton from '../components/ProfileButton';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { IconButton } from '../components/ui/icon-button';
import { Input } from '../components/ui/input';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ShareConversationModal } from '../modals/ShareConversationModal';
import { ActiveState } from '../models/misc';

interface MobileTopBarProps {
  onOpenSidebar: () => void;
  /** Omitted in sections (settings, admin), where there is no chat to leave. */
  onNewChat?: () => void;
  /** Chat or agent name. An empty chat and a section have none. */
  title?: string;
  /** Present on an agent chat: its image, shown before the title. */
  agentImage?: string;
  /** The open conversation; turns on Share, Rename and Delete. */
  conversationId?: string | null;
  onRename?: (conversation: { id: string; name: string }) => void;
  onDelete?: (id: string) => void;
  /** Set for an agent the user owns; adds "Edit agent" to the title menu. */
  editAgentPath?: string;
}

type TitleAction = {
  key: string;
  icon: LucideIcon;
  label: string;
  onSelect: () => void;
  destructive?: boolean;
};

/**
 * The phone-width top bar (below `lg`): sidebar toggle, the current chat or
 * agent name, then new chat and the account menu.
 *
 * It sits on the page surface with no border; the content fades out under a
 * gradient instead. On a conversation or agent the title opens a menu with
 * the chat's actions, so they are reachable without opening the sidebar.
 *
 * @param onOpenSidebar Opens the sidebar sheet.
 * @param onNewChat Starts a new chat; omit it to hide the button.
 * @param title The name shown next to the toggle.
 * @param agentImage The agent's image, when the chat belongs to one.
 * @param conversationId The open conversation, which enables its actions.
 * @param onRename Saves a new conversation name.
 * @param onDelete Deletes the conversation after confirmation.
 * @param editAgentPath The agent's editor route, for an owned agent.
 */
export default function MobileTopBar({
  onOpenSidebar,
  onNewChat,
  title,
  agentImage,
  conversationId,
  onRename,
  onDelete,
  editAgentPath,
}: MobileTopBarProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [isEditing, setIsEditing] = useState(false);
  const [draftName, setDraftName] = useState('');
  const [isShareOpen, setIsShareOpen] = useState(false);
  const [deleteModalState, setDeleteModalState] =
    useState<ActiveState>('INACTIVE');

  const actions: TitleAction[] = [];
  if (editAgentPath) {
    actions.push({
      key: 'edit-agent',
      icon: Bot,
      label: t('navigation.editAgent'),
      onSelect: () => navigate(editAgentPath),
    });
  }
  if (conversationId) {
    actions.push(
      {
        key: 'share',
        icon: Share,
        label: t('convTile.share'),
        onSelect: () => setIsShareOpen(true),
      },
      {
        key: 'rename',
        icon: Pencil,
        label: t('convTile.rename'),
        onSelect: () => {
          setDraftName(title ?? '');
          setIsEditing(true);
        },
      },
      {
        key: 'delete',
        icon: Trash2,
        label: t('convTile.delete'),
        onSelect: () => setDeleteModalState('ACTIVE'),
        destructive: true,
      },
    );
  }

  const saveName = () => {
    const name = draftName.trim();
    if (conversationId && name && name !== title?.trim()) {
      onRename?.({ id: conversationId, name });
    }
    setIsEditing(false);
  };

  const agentMark = agentImage !== undefined && (
    <Avatar
      src={agentImage}
      alt=""
      shape="circle"
      className="shrink-0 overflow-hidden"
      imgClassName="size-5 object-contain"
    />
  );

  const renderTitle = () => {
    if (isEditing) {
      return (
        <div className="bg-accent flex h-8 min-w-0 flex-1 items-center gap-1 rounded-md pr-1 pl-2">
          <Input
            autoFocus
            type="text"
            variant="bare"
            className="min-w-0 flex-1"
            aria-label={t('convTile.rename')}
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') saveName();
              else if (e.key === 'Escape') setIsEditing(false);
            }}
          />
          <IconButton
            label={t('convTile.save')}
            icon={Check}
            variant="ghost-on-accent"
            size="icon-xs"
            onClick={saveName}
          />
          <IconButton
            label={t('cancel')}
            icon={X}
            variant="ghost-on-accent"
            size="icon-xs"
            onClick={() => setIsEditing(false)}
          />
        </div>
      );
    }
    if (!title) return null;
    if (actions.length === 0) {
      return (
        <span
          data-testid="mobile-title"
          className="text-foreground flex min-w-0 items-center gap-1.5 px-2 text-sm font-medium"
        >
          {agentMark}
          <span className="truncate" title={title}>
            {title}
          </span>
        </span>
      );
    }
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            data-testid="mobile-title"
            // Button is shrink-0; shrink lets it narrow to its slot so the
            // name truncates instead of running under New Chat.
            className="min-w-0 shrink"
          >
            {agentMark}
            <span className="truncate" title={title}>
              {title}
            </span>
            <ChevronDown className="text-muted-foreground" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="min-w-48">
          {actions.map((action) => (
            <DropdownMenuItem
              key={action.key}
              variant={action.destructive ? 'destructive' : 'default'}
              onSelect={action.onSelect}
            >
              <action.icon aria-hidden />
              <span>{action.label}</span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  };

  return (
    <>
      <div className="bg-background relative z-10 flex h-14 w-full items-center gap-1 px-2 lg:hidden">
        <IconButton
          label={t('navigation.openSidebar')}
          side="bottom"
          variant="ghost-muted"
          size="icon"
          icon={PanelLeft}
          onClick={onOpenSidebar}
        />
        <div className="flex min-w-0 flex-1">{renderTitle()}</div>
        <div className="flex shrink-0 items-center gap-1 pr-1">
          {onNewChat && (
            <IconButton
              label={t('newChat')}
              side="bottom"
              variant="ghost-muted"
              size="icon"
              icon={SquarePen}
              onClick={onNewChat}
            />
          )}
          <ProfileButton size="xs" />
        </div>
        {/* Replaces a border: the content dissolves under the bar. */}
        <div
          aria-hidden
          className="from-background pointer-events-none absolute inset-x-0 top-full h-6 bg-linear-to-b to-transparent"
        />
      </div>
      {conversationId && (
        <ConfirmationModal
          message={t('convTile.deleteWarning')}
          modalState={deleteModalState}
          setModalState={setDeleteModalState}
          handleSubmit={() => onDelete?.(conversationId)}
          submitLabel={t('convTile.delete')}
          variant="destructive"
        />
      )}
      {isShareOpen && conversationId && (
        <ShareConversationModal
          close={() => setIsShareOpen(false)}
          conversationId={conversationId}
        />
      )}
    </>
  );
}
