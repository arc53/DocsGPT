import { ChevronDown, Copy, Eye, Pencil, Trash2 } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from '../components/ui/command';
import { Button } from '../components/ui/button';
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
  PopoverTrigger,
} from '../components/ui/popover';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, PromptProps } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import PromptsModal from '../preferences/PromptsModal';
import { cn } from '@/lib/utils';

type PromptsDropdownProps = {
  className?: string;
  contentClassName?: string;
};

type ExtendedPromptProps = PromptProps & {
  title?: string;
  titleClassName?: string;
  dropdownProps?: PromptsDropdownProps;
  showAddButton?: boolean;
};

export default function Prompts({
  prompts,
  selectedPrompt,
  onSelectPrompt,
  setPrompts,
  title,
  titleClassName = 'dark:text-foreground font-medium',
  dropdownProps = {},
  showAddButton = true,
}: ExtendedPromptProps) {
  const token = useSelector(selectToken);
  const { t } = useTranslation();
  const [newPromptName, setNewPromptName] = React.useState('');
  const [newPromptContent, setNewPromptContent] = React.useState('');
  const [editPromptName, setEditPromptName] = React.useState('');
  const [editPromptContent, setEditPromptContent] = React.useState('');
  const [currentPromptEdit, setCurrentPromptEdit] = React.useState({
    id: '',
    name: '',
    type: '',
  });
  const [modalType, setModalType] = React.useState<'ADD' | 'EDIT'>('ADD');
  const [duplicateSource, setDuplicateSource] = React.useState<string | null>(
    null,
  );
  const [modalState, setModalState] = React.useState<ActiveState>('INACTIVE');
  const [open, setOpen] = React.useState(false);

  const [promptToDelete, setPromptToDelete] = React.useState<{
    id: string;
    name: string;
  } | null>(null);

  const handleSelectPrompt = (prompt: {
    name: string;
    id: string;
    type: string;
  }) => {
    setEditPromptName(prompt.name);
    onSelectPrompt(prompt.name, prompt.id, prompt.type);
    setOpen(false);
  };

  const handleAddPrompt = async () => {
    try {
      const response = await userService.createPrompt(
        {
          name: newPromptName,
          content: newPromptContent,
        },
        token,
      );
      if (!response.ok) {
        throw new Error('Failed to add prompt');
      }
      const newPrompt = await response.json();
      if (setPrompts) {
        setPrompts([
          ...prompts,
          { name: newPromptName, id: newPrompt.id, type: 'private' },
        ]);
      }
      setModalState('INACTIVE');
      onSelectPrompt(newPromptName, newPrompt.id, 'private');
      setNewPromptName('');
      setNewPromptContent('');
    } catch (error) {
      console.error(error);
    }
  };

  const handleDeletePrompt = (id: string) => {
    const promptToRemove = prompts.find((prompt) => prompt.id === id);
    if (promptToRemove) {
      setPromptToDelete({ id, name: promptToRemove.name });
    }
  };

  const confirmDeletePrompt = () => {
    if (promptToDelete) {
      setPrompts(prompts.filter((prompt) => prompt.id !== promptToDelete.id));
      userService
        .deletePrompt({ id: promptToDelete.id }, token)
        .then((response) => {
          if (!response.ok) {
            throw new Error('Failed to delete prompt');
          }
          // Only change selection if we're deleting the currently selected prompt
          if (
            prompts.length > 0 &&
            selectedPrompt &&
            selectedPrompt.id === promptToDelete.id
          ) {
            const firstPrompt = prompts.find((p) => p.id !== promptToDelete.id);
            if (firstPrompt) {
              onSelectPrompt(
                firstPrompt.name,
                firstPrompt.id,
                firstPrompt.type,
              );
            }
          }
        })
        .catch((error) => {
          console.error(error);
        });
      setPromptToDelete(null);
    }
  };

  const handleFetchPromptContent = async (id: string) => {
    try {
      const response = await userService.getSinglePrompt(id, token);
      if (!response.ok) {
        throw new Error('Failed to fetch prompt content');
      }
      const promptContent = await response.json();
      setEditPromptContent(promptContent.content);
    } catch (error) {
      console.error(error);
    }
  };

  const openEditModal = (prompt: {
    id: string;
    name: string;
    type: string;
  }) => {
    setModalType('EDIT');
    setEditPromptName(prompt.name);
    setEditPromptContent('');
    handleFetchPromptContent(prompt.id);
    setCurrentPromptEdit({
      id: prompt.id,
      name: prompt.name,
      type: prompt.type,
    });
    setModalState('ACTIVE');
    setOpen(false);
  };

  const generateCopyName = (baseName: string) => {
    let candidate = `${baseName} copy`;
    let counter = 2;
    while (prompts.some((prompt) => prompt.name === candidate)) {
      candidate = `${baseName} copy ${counter}`;
      counter += 1;
    }
    return candidate;
  };

  const handleDuplicatePrompt = async (prompt: {
    id: string;
    name: string;
  }) => {
    try {
      const response = await userService.getSinglePrompt(prompt.id, token);
      if (!response.ok) {
        throw new Error('Failed to fetch prompt content');
      }
      const promptContent = await response.json();
      setModalType('ADD');
      setDuplicateSource(prompt.name);
      setNewPromptName(generateCopyName(prompt.name));
      setNewPromptContent(promptContent.content);
      setModalState('ACTIVE');
      setOpen(false);
    } catch (error) {
      console.error(error);
    }
  };

  const handleDuplicateFromModal = () => {
    setDuplicateSource(currentPromptEdit.name);
    setNewPromptName(generateCopyName(currentPromptEdit.name));
    setNewPromptContent(editPromptContent);
    setModalType('ADD');
  };

  const handleSaveChanges = (id: string, type: string) => {
    userService
      .updatePrompt(
        {
          id: id,
          name: editPromptName,
          content: editPromptContent,
        },
        token,
      )
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to update prompt');
        }
        if (setPrompts) {
          const existingPromptIndex = prompts.findIndex(
            (prompt) => prompt.id === id,
          );
          if (existingPromptIndex === -1) {
            setPrompts([
              ...prompts,
              { name: editPromptName, id: id, type: type },
            ]);
          } else {
            const updatedPrompts = [...prompts];
            updatedPrompts[existingPromptIndex] = {
              name: editPromptName,
              id: id,
              type: type,
            };
            setPrompts(updatedPrompts);
          }
        }
        setModalState('INACTIVE');
        onSelectPrompt(editPromptName, id, type);
      })
      .catch((error) => {
        console.error(error);
      });
  };

  const pillClassName = cn(
    'border-border bg-card text-foreground hover:bg-accent flex w-56 items-stretch rounded-3xl border text-sm transition-colors',
    dropdownProps.className,
  );

  return (
    <>
      <div>
        <div className="flex flex-col gap-3">
          <p className={titleClassName}>
            {title ? title : t('settings.general.prompt')}
          </p>
          <div className="flex flex-row flex-wrap items-end justify-start gap-6">
            <Popover open={open} onOpenChange={setOpen}>
              <PopoverAnchor asChild>
                <div className={pillClassName}>
                  <PopoverTrigger asChild>
                    <button
                      type="button"
                      className="focus-visible:ring-ring/50 flex min-w-0 flex-1 items-center rounded-l-3xl py-3 pl-5 text-left outline-none focus-visible:ring-[3px]"
                    >
                      <span
                        className={cn(
                          'truncate',
                          !selectedPrompt?.name && 'text-muted-foreground',
                        )}
                      >
                        {selectedPrompt?.name || 'Select a prompt'}
                      </span>
                    </button>
                  </PopoverTrigger>
                  {selectedPrompt?.id && selectedPrompt.type !== 'public' && (
                    <>
                      <button
                        type="button"
                        onClick={() => openEditModal(selectedPrompt)}
                        className="text-muted-foreground hover:bg-foreground/15 hover:text-foreground dark:hover:bg-foreground/20 focus-visible:ring-ring/50 mx-1 my-auto shrink-0 rounded-full p-1.5 transition-colors outline-none focus-visible:ring-[3px]"
                        aria-label="Edit prompt"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      <div
                        className="bg-border my-2.5 w-px shrink-0"
                        aria-hidden="true"
                      />
                    </>
                  )}
                  <button
                    type="button"
                    onClick={() => setOpen(!open)}
                    className="text-muted-foreground hover:bg-foreground/15 hover:text-foreground dark:hover:bg-foreground/20 focus-visible:ring-ring/50 my-auto mr-2.5 ml-1 shrink-0 rounded-full p-1.5 transition-colors outline-none focus-visible:ring-[3px]"
                    aria-label="Toggle prompt list"
                  >
                    <ChevronDown
                      className={cn(
                        'h-4 w-4 transition-transform',
                        open && 'rotate-180',
                      )}
                    />
                  </button>
                </div>
              </PopoverAnchor>
              <PopoverContent
                align="start"
                className={cn(
                  'w-(--radix-popover-trigger-width) p-0',
                  dropdownProps.contentClassName,
                )}
              >
                <Command>
                  <CommandInput placeholder="Search..." className="h-9" />
                  <CommandList>
                    <CommandEmpty>No results found</CommandEmpty>
                    {prompts.map((prompt) => {
                      const isActive = selectedPrompt?.id === prompt.id;
                      const canModify = prompt.type !== 'public';
                      return (
                        <CommandItem
                          key={prompt.id}
                          value={prompt.name}
                          onSelect={() => handleSelectPrompt(prompt)}
                          className={cn(
                            'flex items-center justify-between gap-2',
                            isActive && 'bg-accent font-medium',
                          )}
                        >
                          <span className="truncate">{prompt.name}</span>
                          <div className="flex shrink-0 items-center gap-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon-sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                openEditModal(prompt);
                              }}
                              className="group/btn hover:bg-foreground/15 dark:hover:bg-foreground/20 h-auto w-auto rounded p-1"
                              aria-label={
                                canModify ? 'Edit prompt' : 'View prompt'
                              }
                            >
                              {canModify ? (
                                <Pencil className="text-muted-foreground group-hover/btn:text-foreground h-3.5 w-3.5" />
                              ) : (
                                <Eye className="text-muted-foreground group-hover/btn:text-foreground h-3.5 w-3.5" />
                              )}
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon-sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDuplicatePrompt(prompt);
                              }}
                              className="group/btn hover:bg-foreground/15 dark:hover:bg-foreground/20 h-auto w-auto rounded p-1"
                              aria-label="Duplicate prompt"
                            >
                              <Copy className="text-muted-foreground group-hover/btn:text-foreground h-3.5 w-3.5" />
                            </Button>
                            {canModify && (
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeletePrompt(prompt.id);
                                }}
                                className="group/btn hover:bg-destructive/15 dark:hover:bg-destructive/25 h-auto w-auto rounded p-1"
                                aria-label="Delete prompt"
                              >
                                <Trash2 className="text-muted-foreground group-hover/btn:text-destructive h-3.5 w-3.5" />
                              </Button>
                            )}
                          </div>
                        </CommandItem>
                      );
                    })}
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
            {showAddButton && (
              <Button
                type="button"
                className="h-auto w-20 rounded-3xl border border-transparent py-3"
                onClick={() => {
                  setModalType('ADD');
                  setDuplicateSource(null);
                  setModalState('ACTIVE');
                }}
              >
                {t('settings.general.add')}
              </Button>
            )}
          </div>
        </div>
      </div>
      <PromptsModal
        existingPrompts={prompts}
        type={modalType}
        modalState={modalState}
        setModalState={setModalState}
        newPromptName={newPromptName}
        setNewPromptName={setNewPromptName}
        newPromptContent={newPromptContent}
        setNewPromptContent={setNewPromptContent}
        editPromptName={editPromptName}
        setEditPromptName={setEditPromptName}
        editPromptContent={editPromptContent}
        setEditPromptContent={setEditPromptContent}
        currentPromptEdit={currentPromptEdit}
        handleAddPrompt={handleAddPrompt}
        handleEditPrompt={handleSaveChanges}
        onDuplicate={handleDuplicateFromModal}
        duplicateSourceName={duplicateSource}
      />
      {promptToDelete && (
        <ConfirmationModal
          message={t('modals.prompts.deleteConfirmation', {
            name: promptToDelete.name,
          })}
          modalState="ACTIVE"
          setModalState={() => setPromptToDelete(null)}
          submitLabel={t('modals.deleteConv.delete')}
          handleSubmit={confirmDeletePrompt}
          handleCancel={() => setPromptToDelete(null)}
          variant="danger"
        />
      )}
    </>
  );
}
