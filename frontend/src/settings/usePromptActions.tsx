import { Copy, Eye, Pencil, Trash2, Users } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import type { MenuOption } from '../components/ui/dropdown-menu';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, Prompt } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import PromptsModal from '../preferences/PromptsModal';
import { selectPrompt, selectToken } from '../preferences/preferenceSlice';
import ShareToTeamModal from '../teams/ShareToTeamModal';
import { can } from '../utils/accessUtils';
import { formatCount } from '../utils/dateTimeUtils';
import { agentUseCount } from '../utils/resourceUsage';

// Presets (`public`) carry no access fields and are never edited in place.
const canEditPrompt = (prompt: Prompt) =>
  prompt.type !== 'public' && can(prompt, 'edit');
const canDeletePrompt = (prompt: Prompt) =>
  prompt.type !== 'public' && can(prompt, 'delete');
const canSharePrompt = (prompt: Prompt) =>
  prompt.type !== 'public' && can(prompt, 'share');

type PromptActionsOptions = {
  prompts: Prompt[];
  /** A prompt was added or saved: the list loads again. */
  onSaved: () => void;
  /** A prompt was deleted on the server. */
  onDeleted: (prompt: Prompt) => void;
};

/**
 * What can be done to a prompt on the Prompts page: open it (Edit, or View
 * when the role can't edit), Add, Duplicate, Share with team and Delete,
 * with the dialogs they open.
 *
 * Args:
 *   prompts: The listed prompts (a copy's name must not repeat one).
 *   onSaved: Called after an add or a save.
 *   onDeleted: Called after a delete.
 *
 * Returns:
 *   `openPrompt`, `addPrompt`, `menuOptions(prompt)` and `modals`, to render.
 */
export default function usePromptActions({
  prompts,
  onSaved,
  onDeleted,
}: PromptActionsOptions) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const chatPrompt = useSelector(selectPrompt);

  const [modalState, setModalState] = React.useState<ActiveState>('INACTIVE');
  const [modalType, setModalType] = React.useState<'ADD' | 'EDIT'>('ADD');
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
  const [duplicateSource, setDuplicateSource] = React.useState<string | null>(
    null,
  );
  const [promptToDelete, setPromptToDelete] = React.useState<Prompt | null>(
    null,
  );
  const [promptToShare, setPromptToShare] = React.useState<Prompt | null>(null);

  const showError = (message: string) =>
    dispatch(showActionToast({ variant: 'destructive', message }));

  const addPrompt = () => {
    setModalType('ADD');
    setDuplicateSource(null);
    setNewPromptName('');
    setNewPromptContent('');
    setModalState('ACTIVE');
  };

  const handleAddPrompt = async () => {
    try {
      const response = await userService.createPrompt(
        { name: newPromptName, content: newPromptContent },
        token,
      );
      if (!response.ok) throw new Error('Failed to add prompt');
      setModalState('INACTIVE');
      setNewPromptName('');
      setNewPromptContent('');
      onSaved();
    } catch (error) {
      console.error(error);
    }
  };

  const fetchPromptContent = async (id: string) => {
    try {
      const response = await userService.getSinglePrompt(id, token);
      if (!response.ok) throw new Error('Failed to fetch prompt content');
      const prompt = await response.json();
      setEditPromptContent(prompt.content);
      setEditPromptUpdatedAt(prompt.updated_at ?? null);
    } catch (error) {
      console.error(error);
    }
  };

  /** Opens the prompt to edit, or to read when the role can't edit it. */
  const openPrompt = (prompt: Prompt) => {
    setModalType('EDIT');
    setEditReadOnly(!canEditPrompt(prompt));
    setEditPromptUpdatedAt(null);
    setEditPromptName(prompt.name);
    setEditPromptContent('');
    fetchPromptContent(prompt.id);
    setCurrentPromptEdit(prompt);
    setModalState('ACTIVE');
  };

  const copyName = (baseName: string) => {
    let candidate = `${baseName} copy`;
    let counter = 2;
    while (prompts.some((prompt) => prompt.name === candidate)) {
      candidate = `${baseName} copy ${counter}`;
      counter += 1;
    }
    return candidate;
  };

  const duplicatePrompt = async (prompt: Prompt) => {
    try {
      const response = await userService.getSinglePrompt(prompt.id, token);
      if (!response.ok) throw new Error('Failed to fetch prompt content');
      const content = await response.json();
      setModalType('ADD');
      setDuplicateSource(prompt.name);
      setNewPromptName(copyName(prompt.name));
      setNewPromptContent(content.content);
      setModalState('ACTIVE');
    } catch (error) {
      console.error(error);
    }
  };

  const duplicateFromModal = () => {
    setDuplicateSource(currentPromptEdit.name);
    setNewPromptName(copyName(currentPromptEdit.name));
    setNewPromptContent(editPromptContent);
    setModalType('ADD');
  };

  const handleSaveChanges = (id: string) =>
    userService
      .updatePrompt(
        {
          id,
          name: editPromptName,
          content: editPromptContent,
          ...(editPromptUpdatedAt && {
            expected_updated_at: editPromptUpdatedAt,
          }),
        },
        token,
      )
      .then((response: Response) => {
        if (!response.ok) {
          showError(
            t(
              response.status === 409
                ? 'settings.prompts.editConflict'
                : 'settings.prompts.saveFailed',
            ),
          );
          return;
        }
        setModalState('INACTIVE');
        onSaved();
      })
      .catch((error: unknown) => console.error(error));

  // Returned to ConfirmationModal: it stays pending while this runs, closes
  // on success and keeps a failure in the dialog.
  const confirmDelete = async () => {
    if (!promptToDelete) return;
    const response = await userService.deletePrompt(
      { id: promptToDelete.id },
      token,
    );
    if (!response.ok) throw new Error('Failed to delete prompt');
    onDeleted(promptToDelete);
    setPromptToDelete(null);
  };

  /** The confirm's consequence: the agents and chats that lose it. */
  const deleteDescription = (prompt: Prompt) => {
    const count = agentUseCount(prompt.used_by);
    const inChats = prompt.id === chatPrompt.id;
    const usage = { count, formatted: formatCount(count) };
    if (count > 0 && inChats)
      return t('settings.prompts.deleteUsedByInChats', usage);
    if (count > 0) return t('settings.prompts.deleteUsedBy', usage);
    if (inChats) return t('settings.prompts.deleteInChats');
    return t('common.cantUndo');
  };

  const menuOptions = (prompt: Prompt): MenuOption[] => {
    const options: MenuOption[] = [
      canEditPrompt(prompt)
        ? {
            icon: Pencil,
            label: t('settings.prompts.edit'),
            onClick: () => openPrompt(prompt),
            variant: 'default',
          }
        : {
            icon: Eye,
            label: t('settings.prompts.view'),
            onClick: () => openPrompt(prompt),
            variant: 'default',
          },
    ];
    if (can(prompt, 'duplicate'))
      options.push({
        icon: Copy,
        label: t('settings.prompts.duplicate'),
        onClick: () => duplicatePrompt(prompt),
        variant: 'default',
      });
    if (canSharePrompt(prompt))
      options.push({
        icon: Users,
        label: t('settings.prompts.shareWithTeam'),
        onClick: () => setPromptToShare(prompt),
        variant: 'default',
      });
    if (canDeletePrompt(prompt))
      options.push({
        icon: Trash2,
        label: t('settings.prompts.delete'),
        onClick: () => setPromptToDelete(prompt),
        variant: 'destructive',
        separatorBefore: true,
      });
    return options;
  };

  const modals = (
    <>
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
            ? duplicateFromModal
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
          description={deleteDescription(promptToDelete)}
          modalState="ACTIVE"
          setModalState={() => setPromptToDelete(null)}
          submitLabel={t('settings.prompts.delete')}
          handleSubmit={confirmDelete}
          error={t('settings.prompts.deleteFailed')}
          handleCancel={() => setPromptToDelete(null)}
          variant="destructive"
        />
      )}
      {promptToShare && (
        <ShareToTeamModal
          resourceType="prompt"
          resourceId={promptToShare.id}
          resourceName={promptToShare.name}
          onClose={() => {
            setPromptToShare(null);
            onSaved();
          }}
        />
      )}
    </>
  );

  return { openPrompt, addPrompt, menuOptions, modals };
}
