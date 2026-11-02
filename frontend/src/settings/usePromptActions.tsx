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
import type { PromptDrafterAgent } from '../drafter/usePromptDrafter';
import {
  canDeletePrompt,
  canEditPrompt,
  canSharePrompt,
  copyName,
} from '../prompts/promptAccess';

type PromptActionsOptions = {
  prompts: Prompt[];
  /** A prompt was added, saved or shared: the list loads again. */
  onSaved: () => void;
  /** A prompt was deleted on the server. */
  onDeleted: (prompt: Prompt) => void;
  /** A prompt was created in the modal (a copy): its id and name. */
  onCreated?: (prompt: { id: string; name: string }) => void;
  /** The agent form the modal is opened from, for the drafter. */
  drafterAgent?: PromptDrafterAgent | null;
  /** The menu's Edit / View: the host opens the prompt (its detail view). */
  onOpen?: (prompt: Prompt) => void;
  /** The menu's Duplicate: the host opens a copy. */
  onDuplicate?: (prompt: Prompt) => void;
};

/**
 * What can be done to a prompt: the ⋯ menu (Edit or View and Duplicate
 * through the host's `onOpen` and `onDuplicate`, Share with team and Delete
 * with their dialogs), and the agent form's Improve, which opens the prompt
 * modal with the drafter's ask bar.
 *
 * Args:
 *   prompts: The listed prompts (a copy's name must not repeat one).
 *   onSaved: Called after a save in the modal or a share.
 *   onDeleted: Called after a delete.
 *   onCreated: Called with a prompt the modal created.
 *   drafterAgent: The agent the prompt is for, when opened from its form.
 *   onOpen: Opens a prompt from its menu.
 *   onDuplicate: Opens a copy from its menu.
 *
 * Returns:
 *   `menuOptions(prompt, detail)`, `dialogs` (delete and share) to render,
 *   and for the agent form `improvePrompt`, `improveCopy` and `modals`
 *   (the prompt modal and the dialogs).
 */
export default function usePromptActions({
  prompts,
  onSaved,
  onDeleted,
  onCreated,
  drafterAgent = null,
  onOpen,
  onDuplicate,
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
  // Opened by an Improve entry: the cursor starts in the drafter's ask bar.
  const [focusAsk, setFocusAsk] = React.useState(false);

  const showError = (message: string) =>
    dispatch(showActionToast({ variant: 'destructive', message }));

  const handleAddPrompt = async () => {
    try {
      const response = await userService.createPrompt(
        { name: newPromptName, content: newPromptContent },
        token,
      );
      if (!response.ok) throw new Error('Failed to add prompt');
      const created = onCreated
        ? ((await response.json()) as { id?: string } | null)
        : null;
      setModalState('INACTIVE');
      setNewPromptName('');
      setNewPromptContent('');
      onSaved();
      if (created?.id) onCreated?.({ id: created.id, name: newPromptName });
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

  /** Opens the prompt in the modal: to edit, or to read when the role can't. */
  const openPrompt = (prompt: Prompt, askFirst = false) => {
    setFocusAsk(askFirst);
    setModalType('EDIT');
    setEditReadOnly(!canEditPrompt(prompt));
    setEditPromptUpdatedAt(null);
    setEditPromptName(prompt.name);
    setEditPromptContent('');
    fetchPromptContent(prompt.id);
    setCurrentPromptEdit(prompt);
    setModalState('ACTIVE');
  };

  const duplicatePrompt = async (prompt: Prompt, askFirst = false) => {
    setFocusAsk(askFirst);
    try {
      const response = await userService.getSinglePrompt(prompt.id, token);
      if (!response.ok) throw new Error('Failed to fetch prompt content');
      const content = await response.json();
      setModalType('ADD');
      setDuplicateSource(prompt.name);
      setNewPromptName(copyName(prompt.name, prompts));
      setNewPromptContent(content.content);
      setModalState('ACTIVE');
    } catch (error) {
      console.error(error);
    }
  };

  /** Opens the prompt with the drafter's ask bar ready; a copy when it can't be edited. */
  const improvePrompt = (prompt: Prompt) => {
    if (canEditPrompt(prompt)) openPrompt(prompt, true);
    else void duplicatePrompt(prompt, true);
  };

  /** Duplicates the prompt and opens the copy with the ask bar ready. */
  const improveCopy = (prompt: Prompt) => void duplicatePrompt(prompt, true);

  const duplicateFromModal = () => {
    setDuplicateSource(currentPromptEdit.name);
    setNewPromptName(copyName(currentPromptEdit.name, prompts));
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

  /**
   * A prompt's ⋯ items; `detail` (the open prompt's own ⋯) leaves out Edit
   * and View.
   */
  const menuOptions = (prompt: Prompt, detail = false): MenuOption[] => {
    const options: MenuOption[] = [];
    if (onOpen && !detail)
      options.push(
        canEditPrompt(prompt)
          ? {
              icon: Pencil,
              label: t('settings.prompts.edit'),
              onClick: () => onOpen(prompt),
              variant: 'default',
            }
          : {
              icon: Eye,
              label: t('settings.prompts.view'),
              onClick: () => onOpen(prompt),
              variant: 'default',
            },
      );
    if (onDuplicate && can(prompt, 'duplicate'))
      options.push({
        icon: Copy,
        label: t('settings.prompts.duplicate'),
        onClick: () => onDuplicate(prompt),
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

  const dialogs = (
    <>
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
        drafterAgent={drafterAgent}
        autoFocusAsk={focusAsk}
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
      {dialogs}
    </>
  );

  return {
    improvePrompt,
    improveCopy,
    menuOptions,
    dialogs,
    modals,
  };
}
