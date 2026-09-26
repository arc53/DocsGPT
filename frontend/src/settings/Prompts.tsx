import { ChevronDown, Copy, Eye, Pencil, Trash2, Users } from 'lucide-react';
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
import { FormField } from '../components/ui/form-field';
import { IconButton } from '../components/ui/icon-button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '../components/ui/popover';
import { SectionHeader } from '../components/ui/section-header';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, PromptProps } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import ShareToTeamModal from '../teams/ShareToTeamModal';
import PromptsModal from '../preferences/PromptsModal';
import { cn } from '@/lib/utils';

type PromptsDropdownProps = {
  className?: string;
};

type ExtendedPromptProps = PromptProps & {
  title?: string;
  /**
   * `label` (Settings → General): the title is the picker's floating label.
   * `heading` (the agent form): the title is a section heading above it.
   */
  titleAs?: 'label' | 'heading';
  dropdownProps?: PromptsDropdownProps;
  showAddButton?: boolean;
};

export default function Prompts({
  prompts,
  selectedPrompt,
  onSelectPrompt,
  setPrompts,
  title,
  titleAs = 'label',
  dropdownProps = {},
  showAddButton = true,
}: ExtendedPromptProps) {
  const token = useSelector(selectToken);
  const { t } = useTranslation();
  const pickerId = React.useId();
  const titleText = title ? title : t('settings.general.prompt');
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

  const [promptToShare, setPromptToShare] = React.useState<{
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

  const picker = (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="combobox"
          size="field"
          shape="pill"
          id={pickerId}
          role="combobox"
          aria-expanded={open}
          aria-label={titleAs === 'heading' ? titleText : undefined}
          data-placeholder={selectedPrompt?.name ? undefined : ''}
          className="min-w-0 flex-1 justify-between"
        >
          <span className="truncate">
            {selectedPrompt?.name || t('settings.general.promptActions.select')}
          </span>
          <span className="text-muted-foreground">
            <ChevronDown
              className={cn(
                'transition-transform duration-200',
                open && 'rotate-180',
              )}
            />
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-(--radix-popover-trigger-width) p-0"
      >
        <Command>
          <CommandInput
            placeholder={t('settings.sources.searchPlaceholder')}
            className="h-9"
          />
          <CommandList>
            <CommandEmpty>{t('settings.sources.noResults')}</CommandEmpty>
            {prompts.map((prompt) => {
              const isActive = selectedPrompt?.id === prompt.id;
              const canModify = prompt.type !== 'public';
              // Sharing is an owner-only action: hide it for public
              // prompts and prompts shared into the workspace by a
              // team.
              const canShare =
                prompt.type !== 'public' && prompt.type !== 'team';
              return (
                <CommandItem
                  key={prompt.id}
                  value={prompt.name}
                  checked={isActive}
                  onSelect={() => handleSelectPrompt(prompt)}
                  className="flex items-center justify-between"
                >
                  <span className="truncate">{prompt.name}</span>
                  <div className="flex shrink-0 items-center gap-1">
                    <IconButton
                      variant="ghost-on-accent"
                      size="icon-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        openEditModal(prompt);
                      }}
                      label={
                        canModify
                          ? t('settings.general.promptActions.edit')
                          : t('settings.general.promptActions.view')
                      }
                    >
                      {canModify ? (
                        <Pencil className="text-current" aria-hidden="true" />
                      ) : (
                        <Eye className="text-current" aria-hidden="true" />
                      )}
                    </IconButton>
                    <IconButton
                      variant="ghost-on-accent"
                      size="icon-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDuplicatePrompt(prompt);
                      }}
                      label={t('settings.general.promptActions.duplicate')}
                    >
                      <Copy className="text-current" aria-hidden="true" />
                    </IconButton>
                    {canShare && (
                      <IconButton
                        variant="ghost-on-accent"
                        size="icon-xs"
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpen(false);
                          setPromptToShare({
                            id: prompt.id,
                            name: prompt.name,
                          });
                        }}
                        label={t('agents.shareWithTeam')}
                      >
                        <Users className="text-current" aria-hidden="true" />
                      </IconButton>
                    )}
                    {canModify && (
                      <IconButton
                        variant="ghost-destructive-on-accent"
                        size="icon-xs"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeletePrompt(prompt.id);
                        }}
                        label={t('settings.general.promptActions.delete')}
                      >
                        <Trash2 className="text-current" aria-hidden="true" />
                      </IconButton>
                    )}
                  </div>
                </CommandItem>
              );
            })}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );

  return (
    <>
      <div>
        <div className="flex flex-col gap-3">
          {titleAs === 'heading' ? (
            <SectionHeader as="h2" title={titleText} />
          ) : null}
          <div className="flex flex-row flex-wrap items-end justify-start gap-6">
            <div
              className={cn(
                'flex w-56 items-center gap-1',
                dropdownProps.className,
              )}
            >
              {titleAs === 'label' ? (
                <FormField
                  label={titleText}
                  id={pickerId}
                  labelSurface="background"
                  className="min-w-0 flex-1"
                >
                  {picker}
                </FormField>
              ) : (
                picker
              )}
              {selectedPrompt?.id && selectedPrompt.type !== 'public' && (
                <IconButton
                  variant="ghost-muted"
                  size="icon-xs"
                  shape="pill"
                  onClick={() => openEditModal(selectedPrompt)}
                  label={t('settings.general.promptActions.edit')}
                  icon={Pencil}
                />
              )}
            </div>
            {showAddButton && (
              <Button
                type="button"
                size="field"
                shape="pill"
                className="w-20"
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
          variant="destructive"
        />
      )}
      {promptToShare && (
        <ShareToTeamModal
          resourceType="prompt"
          resourceId={promptToShare.id}
          resourceName={promptToShare.name}
          onClose={() => setPromptToShare(null)}
        />
      )}
    </>
  );
}
