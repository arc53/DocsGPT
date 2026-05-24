import { ChevronDown, Pencil, Trash2 } from 'lucide-react';
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
      onSelectPrompt(newPromptName, newPrompt.id, newPromptContent);
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

  const triggerClassName = cn(
    'border-border bg-card text-foreground hover:bg-accent flex w-56 items-center justify-between rounded-3xl border px-5 py-3 text-sm',
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
              <PopoverTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  className={cn('h-auto justify-between', triggerClassName)}
                >
                  <span
                    className={cn(
                      'truncate',
                      !selectedPrompt?.name && 'text-muted-foreground',
                    )}
                  >
                    {selectedPrompt?.name || 'Select a prompt'}
                  </span>
                  <ChevronDown
                    className={cn(
                      'text-muted-foreground ml-2 h-4 w-4 shrink-0 transition-transform',
                      open && 'rotate-180',
                    )}
                  />
                </Button>
              </PopoverTrigger>
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
                      const canDelete = prompt.type !== 'public';
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
                            {prompt.type !== 'public' && (
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setModalType('EDIT');
                                  setEditPromptName(prompt.name);
                                  handleFetchPromptContent(prompt.id);
                                  setCurrentPromptEdit({
                                    id: prompt.id,
                                    name: prompt.name,
                                    type: prompt.type,
                                  });
                                  setModalState('ACTIVE');
                                  setOpen(false);
                                }}
                                className="h-auto w-auto rounded p-1"
                                aria-label="Edit prompt"
                              >
                                <Pencil className="text-muted-foreground h-3.5 w-3.5" />
                              </Button>
                            )}
                            {canDelete && (
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeletePrompt(prompt.id);
                                }}
                                className="h-auto w-auto rounded p-1"
                                aria-label="Delete prompt"
                              >
                                <Trash2 className="text-muted-foreground h-3.5 w-3.5" />
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
                className="w-20 rounded-3xl py-3"
                onClick={() => {
                  setModalType('ADD');
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
