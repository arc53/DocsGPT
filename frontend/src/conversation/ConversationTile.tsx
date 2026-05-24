import { X } from 'lucide-react';
import {
  SyntheticEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useSelector } from 'react-redux';
import Edit from '../assets/edit.svg';
import { useDarkTheme } from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';
import CheckMark2 from '../assets/checkMark2.svg';
import Trash from '../assets/red-trash.svg';
import Share from '../assets/share.svg';
import threeDots from '../assets/three-dots.svg';
import { selectConversationId } from '../preferences/preferenceSlice';
import { ActiveState } from '../models/misc';
import { ShareConversationModal } from '../modals/ShareConversationModal';
import { useTranslation } from 'react-i18next';
import { Button } from '../components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
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
  const [isDarkTheme] = useDarkTheme();
  const [isEdit, setIsEdit] = useState(false);
  const [conversationName, setConversationsName] = useState('');
  const [isOpen, setOpen] = useState<boolean>(false);
  const [isShareModalOpen, setShareModalState] = useState<boolean>(false);
  const [isHovered, setIsHovered] = useState(false);
  const [deleteModalState, setDeleteModalState] =
    useState<ActiveState>('INACTIVE');
  const { t } = useTranslation();
  useEffect(() => {
    setConversationsName(conversation.name);
  }, [conversation.name]);

  function handleEditConversation(event: SyntheticEvent) {
    event.stopPropagation();
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

  type ConversationMenuOption = {
    icon: string;
    label: string;
    onClick: (event: SyntheticEvent) => void;
    variant: 'default' | 'destructive';
    iconWidth?: number;
    iconHeight?: number;
  };

  const menuOptions: ConversationMenuOption[] = [
    {
      icon: Share,
      label: t('convTile.share'),
      onClick: (event: SyntheticEvent) => {
        event.stopPropagation();
        setShareModalState(true);
        setOpen(false);
      },
      variant: 'default',
      iconWidth: 14,
      iconHeight: 14,
    },
    {
      icon: Edit,
      label: t('convTile.rename'),
      onClick: handleEditConversation,
      variant: 'default',
    },
    {
      icon: Trash,
      label: t('convTile.delete'),
      onClick: (event: SyntheticEvent) => {
        event.stopPropagation();
        setDeleteModalState('ACTIVE');
        setOpen(false);
      },
      iconWidth: 18,
      iconHeight: 18,
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
        onClick={() => {
          onConversationClick();
          conversationId !== conversation.id &&
            selectConversation(conversation.id);
        }}
        className={`hover:bg-sidebar-accent mx-4 my-auto mt-4 flex h-9 cursor-pointer items-center justify-between gap-4 rounded-3xl pl-4 ${
          conversationId === conversation.id || isOpen || isHovered || isEdit
            ? 'bg-sidebar-accent'
            : ''
        }`}
      >
        <div className={`flex w-10/12 gap-4`}>
          {isEdit ? (
            <input
              autoFocus
              type="text"
              className="h-6 w-full rounded-2xl bg-transparent px-1 text-sm leading-6 font-normal outline-none"
              value={conversationName}
              onChange={(e) => setConversationsName(e.target.value)}
              onKeyDown={handleRenameKeyDown}
            />
          ) : (
            <p className="text-foreground dark:text-foreground my-auto overflow-hidden text-sm leading-6 font-normal text-ellipsis whitespace-nowrap">
              {conversationName}
            </p>
          )}
        </div>
        {(conversationId === conversation.id || isHovered || isOpen) && (
          <div className="dark:text-muted-foreground flex text-white">
            {isEdit ? (
              <div className="flex gap-1">
                <img
                  src={CheckMark2}
                  alt="Edit"
                  className="mr-2 h-4 w-4 cursor-pointer text-white hover:opacity-50"
                  id={`img-${conversation.id}`}
                  onClick={(event: SyntheticEvent) => {
                    event.stopPropagation();
                    handleSaveConversation({
                      id: conversation.id,
                      name: conversationName,
                    });
                  }}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Exit"
                  id={`img-${conversation.id}`}
                  className="mt-px mr-4 h-auto w-auto bg-transparent p-0 hover:bg-transparent hover:opacity-50"
                  onClick={(event: SyntheticEvent) => {
                    event.stopPropagation();
                    onClear();
                  }}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            ) : (
              <DropdownMenu open={isOpen} onOpenChange={setOpen}>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={(event: SyntheticEvent) => {
                      event.stopPropagation();
                    }}
                    className="mr-2 h-6 w-6 rounded-full"
                  >
                    <img src={threeDots} width={8} alt="menu" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-[144px]">
                  {menuOptions.map((option, index) => (
                    <DropdownMenuItem
                      key={index}
                      variant={option.variant}
                      onSelect={(event) => {
                        option.onClick(event as unknown as SyntheticEvent);
                      }}
                    >
                      <img
                        src={option.icon}
                        alt=""
                        width={option.iconWidth ?? 16}
                        height={option.iconHeight ?? 16}
                      />
                      <span>{option.label}</span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
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
