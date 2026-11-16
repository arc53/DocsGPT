import { Copy, Eye, Pencil, Trash2, Users } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import type { MenuOption } from '../components/ui/dropdown-menu';
import ConfirmationModal from '../modals/ConfirmationModal';
import { Prompt } from '../models/misc';
import { selectPrompt, selectToken } from '../preferences/preferenceSlice';
import ShareToTeamModal from '../teams/ShareToTeamModal';
import { can } from '../utils/accessUtils';
import { formatCount } from '../utils/dateTimeUtils';
import { agentUseCount } from '../utils/resourceUsage';
import {
  canDeletePrompt,
  canEditPrompt,
  canSharePrompt,
} from '../prompts/promptAccess';

type PromptActionsOptions = {
  /** A prompt was shared: the list loads again. */
  onSaved: () => void;
  /** A prompt was deleted on the server. */
  onDeleted: (prompt: Prompt) => void;
  /** The menu's Edit / View: the host opens the prompt (its detail view). */
  onOpen: (prompt: Prompt) => void;
  /** The menu's Duplicate: the host opens a copy. */
  onDuplicate: (prompt: Prompt) => void;
};

/**
 * What can be done to a prompt: the ⋯ menu (Edit or View and Duplicate
 * through the host's `onOpen` and `onDuplicate`, Share with team and Delete
 * with their dialogs).
 *
 * Args:
 *   onSaved: Called after a share.
 *   onDeleted: Called after a delete.
 *   onOpen: Opens a prompt from its menu.
 *   onDuplicate: Opens a copy from its menu.
 *
 * Returns:
 *   `menuOptions(prompt, detail)` and `dialogs` (delete and share) to
 *   render.
 */
export default function usePromptActions({
  onSaved,
  onDeleted,
  onOpen,
  onDuplicate,
}: PromptActionsOptions) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const chatPrompt = useSelector(selectPrompt);

  const [promptToDelete, setPromptToDelete] = React.useState<Prompt | null>(
    null,
  );
  const [promptToShare, setPromptToShare] = React.useState<Prompt | null>(null);

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
    if (!detail)
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
    if (can(prompt, 'duplicate'))
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

  return { menuOptions, dialogs };
}
