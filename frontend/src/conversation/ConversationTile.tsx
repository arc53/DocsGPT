import { Check, Pencil, Share, Trash2, X } from 'lucide-react';
import {
  SyntheticEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';
import ConfirmationModal from '../modals/ConfirmationModal';
import { selectConversationId } from '../preferences/preferenceSlice';
import { ActiveState } from '../models/misc';
import { ShareConversationModal } from '../modals/ShareConversationModal';
import { useTranslation } from 'react-i18next';
import { Button } from '../components/ui/button';
import { IconButton } from '../components/ui/icon-button';
import { Input } from '../components/ui/input';
import { cn } from '../lib/utils';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { useOutsideAlerter } from '../hooks';

interface ConversationProps {
  name: string;
  id: string;
}
interface ConversationTileProps {
  conversation: ConversationProps;
  selectConversation: (arg1: string) => void;
  onConversationClick: () => void; //Callback to handle click on conversation tile regardless of selected or not
  onDeleteConversation: (arg1: string) => void;
  onSave: ({ name, id }: ConversationProps) => void;
}

export default function ConversationTile({
  conversation,
  selectConversation,
  onConversationClick,
  onDeleteConversation,
  onSave,
}: ConversationTileProps) {
  const conversationId = useSelector(selectConversationId);
  const tileRef = useRef<HTMLInputElement>(null);
  const [isEdit, setIsEdit] = useState(false);
  const [conversationName, setConversationsName] = useState('');
  const [isOpen, setOpen] = useState<boolean>(false);
  const [isShareModalOpen, setShareModalState] = useState<boolean>(false);
  const [isHovered, setIsHovered] = useState(false);
  const [deleteModalState, setDeleteModalState] =
    useState<ActiveState>('INACTIVE');
  const { t } = useTranslation();
  const isCurrent = conversationId === conversation.id;
  useEffect(() => {
    setConversationsName(conversation.name);
  }, [conversation.name]);

  function handleEditConversation() {
    setIsEdit(true);
    setOpen(false);
  }

  function handleSaveConversation(changedConversation: ConversationProps) {
    if (
      changedConversation.name.trim().length &&
      changedConversation.name.trim() !== conversation.name.trim()
    ) {
      onSave(changedConversation);
      setIsEdit(false);
    } else {
      onClear();
    }
  }

  const preventScroll = useCallback((event: WheelEvent | TouchEvent) => {
    event.preventDefault();
  }, []);

  useEffect(() => {
    const conversationsMainDiv = document.getElementById(
      'conversationsMainDiv',
    );

    if (conversationsMainDiv) {
      if (isOpen) {
        conversationsMainDiv.addEventListener('wheel', preventScroll, {
          passive: false,
        });
        conversationsMainDiv.addEventListener('touchmove', preventScroll, {
          passive: false,
        });
      } else {
        conversationsMainDiv.removeEventListener('wheel', preventScroll);
        conversationsMainDiv.removeEventListener('touchmove', preventScroll);
      }

      return () => {
        conversationsMainDiv.removeEventListener('wheel', preventScroll);
        conversationsMainDiv.removeEventListener('touchmove', preventScroll);
      };
    }
  }, [isOpen]);

  function onClear() {
    setConversationsName(conversation.name);
    setIsEdit(false);
  }

  const handleRenameKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    e.stopPropagation();
    if (e.key === 'Enter') {
      handleSaveConversation({
        id: conversation.id,
        name: conversationName,
      });
    } else if (e.key === 'Escape') {
      onClear();
    }
  };

  const menuOptions: MenuOption[] = [
    {
      icon: Share,
      label: t('convTile.share'),
      onClick: () => {
        setShareModalState(true);
        setOpen(false);
      },
    },
    {
      icon: Pencil,
      label: t('convTile.rename'),
      onClick: handleEditConversation,
    },
    {
      icon: Trash2,
      label: t('convTile.delete'),
      onClick: () => {
        setDeleteModalState('ACTIVE');
        setOpen(false);
      },
      variant: 'destructive',
    },
  ];

  useOutsideAlerter(
    tileRef,
    () => {
      if (isEdit) {
        onClear();
      }
    },
    [isEdit],
    true,
  );

  return (
    <>
      <div
        ref={tileRef}
        onMouseEnter={() => {
          setIsHovered(true);
        }}
        onMouseLeave={() => {
          if (!isEdit) {
            setIsHovered(false);
          }
        }}
        className="group relative mx-4 mt-4"
      >
        {isEdit ? (
          // The rename field takes the row's place; the row keeps its fill
          // and the Save / Cancel buttons sit where the menu was.
          <div className="bg-sidebar-accent flex h-9 items-center rounded-full pr-20 pl-3">
            <Input
              autoFocus
              type="text"
              variant="bare"
              className="w-full"
              value={conversationName}
              onChange={(e) => setConversationsName(e.target.value)}
              onKeyDown={handleRenameKeyDown}
            />
          </div>
        ) : (
          <Button
            variant="sidebar-item"
            asChild
            /* eslint-disable shadcn/no-restyle -- the link and its menu
               button are siblings, so the row keeps its fill while the
               pointer is on the button or the menu is open, and pr-10 keeps
               the label clear of the button. */
            className={cn(
              'group-hover:bg-sidebar-accent flex w-full pr-10',
              isOpen && 'bg-sidebar-accent',
            )}
            /* eslint-enable shadcn/no-restyle */
          >
            <Link
              to={`/c/${conversation.id}`}
              aria-current={isCurrent ? 'page' : undefined}
              onClick={(event) => {
                if (event.metaKey || event.ctrlKey || event.shiftKey) return;
                event.preventDefault();
                onConversationClick();
                if (!isCurrent) selectConversation(conversation.id);
              }}
            >
              <span className="truncate">{conversationName}</span>
            </Link>
          </Button>
        )}
        {(isCurrent || isHovered || isOpen || isEdit) && (
          <div className="absolute top-1 right-2 flex">
            {isEdit ? (
              <div className="flex gap-1">
                <IconButton
                  label={t('convTile.save')}
                  icon={Check}
                  variant="ghost-on-accent"
                  size="icon-xs"
                  onClick={(event: SyntheticEvent) => {
                    event.stopPropagation();
                    handleSaveConversation({
                      id: conversation.id,
                      name: conversationName,
                    });
                  }}
                />
                <IconButton
                  label={t('cancel')}
                  icon={X}
                  variant="ghost-on-accent"
                  size="icon-xs"
                  id={`img-${conversation.id}`}
                  onClick={(event: SyntheticEvent) => {
                    event.stopPropagation();
                    onClear();
                  }}
                />
              </div>
            ) : (
              <ActionMenu
                options={menuOptions}
                triggerLabel={t('convTile.menu')}
                open={isOpen}
                onOpenChange={setOpen}
              />
            )}
          </div>
        )}
      </div>
      <ConfirmationModal
        message={t('convTile.deleteWarning')}
        modalState={deleteModalState}
        setModalState={setDeleteModalState}
        handleSubmit={() => onDeleteConversation(conversation.id)}
        submitLabel={t('convTile.delete')}
      />
      {isShareModalOpen && (
        <ShareConversationModal
          close={() => {
            setShareModalState(false);
            isHovered && setIsHovered(false);
          }}
          conversationId={conversation.id}
        />
      )}
    </>
  );
}
