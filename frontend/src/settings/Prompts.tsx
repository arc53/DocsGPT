import { Copy, Eye, Pencil, Trash2, Users } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { Button } from '../components/ui/button';
import { Combobox } from '../components/ui/combobox';
import { FormField } from '../components/ui/form-field';
import { IconButton } from '../components/ui/icon-button';
import { SectionHeader } from '../components/ui/section-header';
import { SettingRow } from '../components/ui/setting-row';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, Prompt, PromptProps } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import ShareToTeamModal from '../teams/ShareToTeamModal';
import PromptsModal from '../preferences/PromptsModal';
import { can } from '../utils/accessUtils';
import { cn } from '@/lib/utils';

// Presets (`public`) carry no access fields and are never edited in place.
const canEditPrompt = (prompt: Prompt) =>
  prompt.type !== 'public' && can(prompt, 'edit');
const canDeletePrompt = (prompt: Prompt) =>
  prompt.type !== 'public' && can(prompt, 'delete');
const canSharePrompt = (prompt: Prompt) =>
  prompt.type !== 'public' && can(prompt, 'share');

type PromptsDropdownProps = {
  className?: string;
};

type ExtendedPromptProps = PromptProps & {
  title?: string;
  /**
   * `row` (Settings → General): a SettingRow whose label names the picker.
   * `heading`: the title is a section heading above it.
   * `field` (the agent form): the title is the picker's floating FormField
   * label, like the fields around it.
   */
  titleAs?: 'row' | 'heading' | 'field';
  /** The surface behind a `field` picker, for its label's notch. */
  labelSurface?: 'card' | 'background' | 'muted';
  /** The row's muted description, for `titleAs="row"`. */
  description?: string;
  dropdownProps?: PromptsDropdownProps;
  showAddButton?: boolean;
};

export default function Prompts({
  prompts,
  selectedPrompt,
  onSelectPrompt,
  setPrompts,
  title,
  titleAs = 'row',
  description,
  dropdownProps = {},
  showAddButton = true,
  labelSurface = 'card',
}: ExtendedPromptProps) {
  const token = useSelector(selectToken);
  const dispatch = useDispatch();
  const { t } = useTranslation();
  const showError = (message: string) =>
    dispatch(showActionToast({ variant: 'destructive', message }));
  const pickerId = React.useId();
  const titleText = title ? title : t('settings.general.prompt');
  const [newPromptName, setNewPromptName] = React.useState('');
  const [newPromptContent, setNewPromptContent] = React.useState('');
  const [editPromptName, setEditPromptName] = React.useState('');
  const [editPromptContent, setEditPromptContent] = React.useState('');
  const [currentPromptEdit, setCurrentPromptEdit] = React.useState<Prompt>({
    id: '',
    name: '',
    type: '',
  });
  // The open prompt's version, sent back so a save over someone else's
  // newer edit is refused (409) instead of overwriting it.
  const [editPromptUpdatedAt, setEditPromptUpdatedAt] = React.useState<
    string | null
  >(null);
  const [editReadOnly, setEditReadOnly] = React.useState(false);
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

  // Returned to ConfirmationModal: it stays pending while this runs, closes
  // on success and keeps a failure in the dialog.
  const confirmDeletePrompt = () => {
    if (!promptToDelete) return;
    return userService
      .deletePrompt({ id: promptToDelete.id }, token)
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to delete prompt');
        }
        setPrompts(prompts.filter((prompt) => prompt.id !== promptToDelete.id));
        // Only change selection if we're deleting the currently selected prompt
        if (
          prompts.length > 0 &&
          selectedPrompt &&
          selectedPrompt.id === promptToDelete.id
        ) {
          const firstPrompt = prompts.find((p) => p.id !== promptToDelete.id);
          if (firstPrompt) {
            onSelectPrompt(firstPrompt.name, firstPrompt.id, firstPrompt.type);
          }
        }
      });
  };

  const handleFetchPromptContent = async (id: string) => {
    try {
      const response = await userService.getSinglePrompt(id, token);
      if (!response.ok) {
        throw new Error('Failed to fetch prompt content');
      }
      const promptContent = await response.json();
      setEditPromptContent(promptContent.content);
      setEditPromptUpdatedAt(promptContent.updated_at ?? null);
    } catch (error) {
      console.error(error);
    }
  };

  const openEditModal = (prompt: Prompt) => {
    setModalType('EDIT');
    setEditReadOnly(!canEditPrompt(prompt));
    setEditPromptUpdatedAt(null);
    setEditPromptName(prompt.name);
    setEditPromptContent('');
    handleFetchPromptContent(prompt.id);
    setCurrentPromptEdit(prompt);
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

  const handleSaveChanges = (id: string, type: string) =>
    userService
      .updatePrompt(
        {
          id: id,
          name: editPromptName,
          content: editPromptContent,
          ...(editPromptUpdatedAt && {
            expected_updated_at: editPromptUpdatedAt,
          }),
        },
        token,
      )
      .then((response) => {
        if (!response.ok) {
          showError(
            t(
              response.status === 409
                ? 'settings.general.promptActions.editConflict'
                : 'settings.general.promptActions.saveFailed',
            ),
          );
          return;
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

  const picker = (
    <Combobox
      options={prompts.map((prompt) => ({
        value: prompt.id,
        label: prompt.name,
      }))}
      value={selectedPrompt?.id || null}
      valueOption={
        selectedPrompt?.name
          ? { value: selectedPrompt.id, label: selectedPrompt.name }
          : undefined
      }
      onValueChange={(id) => {
        const prompt = prompts.find((p) => p.id === id);
        if (prompt) handleSelectPrompt(prompt);
      }}
      open={open}
      onOpenChange={setOpen}
      placeholder={t('settings.general.promptActions.select')}
      searchPlaceholder={t('settings.sources.searchPlaceholder')}
      emptyText={t('settings.sources.noResults')}
      // A form field in NewAgent (square); a settings-row control elsewhere.
      shape={titleAs === 'field' ? 'default' : 'pill'}
      id={pickerId}
      aria-label={titleAs === 'heading' ? titleText : undefined}
      className={cn(titleAs === 'row' && 'sm:w-56')}
      renderItem={(option) => {
        const prompt = prompts.find((p) => p.id === option.value)!;
        const canEdit = canEditPrompt(prompt);
        return (
          <>
            <span className="min-w-0 flex-1 truncate" title={prompt.name}>
              {prompt.name}
            </span>
            <div className="flex shrink-0 items-center gap-1">
              <IconButton
                variant="ghost-on-accent"
                size="icon-xs"
                onClick={(e) => {
                  e.stopPropagation();
                  openEditModal(prompt);
                }}
                label={
                  canEdit
                    ? t('settings.general.promptActions.edit')
                    : t('settings.general.promptActions.view')
                }
              >
                {canEdit ? (
                  <Pencil className="text-current" aria-hidden="true" />
                ) : (
                  <Eye className="text-current" aria-hidden="true" />
                )}
              </IconButton>
              {can(prompt, 'duplicate') && (
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
              )}
              {canSharePrompt(prompt) && (
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
              {canDeletePrompt(prompt) && (
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
          </>
        );
      }}
    />
  );

  // The listed row carries the access fields; a stored selection may not.
  const selectedListed =
    prompts.find((prompt) => prompt.id === selectedPrompt?.id) ??
    selectedPrompt;
  const editButton = selectedPrompt?.id && canEditPrompt(selectedListed) && (
    <IconButton
      variant="ghost-muted"
      size="icon-xs"
      shape="pill"
      onClick={() => openEditModal(selectedListed)}
      label={t('settings.general.promptActions.edit')}
      icon={Pencil}
    />
  );

  // A prompt that belongs to this field, so a neutral pill rather than the
  // primary one reserved for a page's own action.
  const addButton = showAddButton && (
    <Button
      type="button"
      variant="outline"
      size="field"
      shape="pill"
      onClick={() => {
        setModalType('ADD');
        setDuplicateSource(null);
        setModalState('ACTIVE');
      }}
    >
      {t('settings.general.add')}
    </Button>
  );

  return (
    <>
      {titleAs === 'row' ? (
        <SettingRow
          label={titleText}
          description={description}
          htmlFor={pickerId}
          stack
        >
          <div className="flex items-center gap-2">
            <div className="flex min-w-0 flex-1 items-center gap-1 sm:flex-none">
              {picker}
              {editButton}
            </div>
            {addButton}
          </div>
        </SettingRow>
      ) : titleAs === 'field' ? (
        <div className="flex items-center gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-1">
            <FormField
              id={pickerId}
              label={titleText}
              labelSurface={labelSurface}
              className="min-w-0 flex-1"
            >
              {picker}
            </FormField>
            {editButton}
          </div>
          {addButton}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <SectionHeader as="h2" title={titleText} />
          <div className="flex flex-row flex-wrap items-end justify-start gap-6">
            <div
              className={cn(
                'flex w-56 items-center gap-1',
                dropdownProps.className,
              )}
            >
              {picker}
              {editButton}
            </div>
            {addButton}
          </div>
        </div>
      )}
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
        readOnly={editReadOnly}
        onDuplicate={
          can(
            prompts.find((prompt) => prompt.id === currentPromptEdit.id) ??
              currentPromptEdit,
            'duplicate',
          )
            ? handleDuplicateFromModal
            : undefined
        }
        duplicateSourceName={duplicateSource}
      />
      {promptToDelete && (
        <ConfirmationModal
          message={t('modals.prompts.deleteConfirmation', {
            interpolation: { escapeValue: false },
            name: promptToDelete.name,
          })}
          description={t('common.cantUndo')}
          modalState="ACTIVE"
          setModalState={() => setPromptToDelete(null)}
          submitLabel={t('modals.prompts.delete')}
          handleSubmit={confirmDeletePrompt}
          error={t('settings.general.promptActions.deleteFailed')}
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
