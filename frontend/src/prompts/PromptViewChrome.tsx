import { useTranslation } from 'react-i18next';

import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from '../components/ui/alert';
import { Button } from '../components/ui/button';
import ConfirmationModal from '../modals/ConfirmationModal';
import type { PromptDetail } from './usePromptDetail';

/** What Save and leave says when it can't save, by the reason it rejected. */
const LEAVE_ERRORS: Record<string, string> = {
  // Another try saves a copy: a save at the same version fails the same.
  conflict: 'settings.prompts.editConflictLeave',
  review: 'settings.prompts.saveBlocked.review',
  name: 'settings.prompts.saveBlocked.name',
  nameExists: 'modals.prompts.nameExists',
  content: 'settings.prompts.saveBlocked.content',
  template: 'modals.prompts.templateBroken',
};

/**
 * Save the open prompt. After a conflict a save at the same version fails
 * the same: it keeps the changes as a new prompt instead.
 */
export const savePrompt = (detail: PromptDetail, { quiet = false } = {}) =>
  detail.save({ quiet, asCopy: detail.conflict });

/**
 * Whether the prompt view's Save is off: nothing to save yet, or the
 * drafter holds the text (`drafterBusy`: a turn running, or a review open,
 * when the text holds only the changes chosen so far and the drawer's
 * Accept all or Discard ends it first).
 */
export const promptSaveDisabled = (
  detail: PromptDetail,
  drafterBusy: boolean,
) => !detail.canSave || drafterBusy;

/**
 * The prompt view's Save on its crumb row: Save as copy after a conflict,
 * else `label` (Save by default).
 */
export function PromptSaveButton({
  detail,
  disabled,
  label,
}: {
  detail: PromptDetail;
  disabled: boolean;
  label?: string;
}) {
  const { t } = useTranslation();
  return (
    <Button
      type="button"
      size="field"
      shape="pill"
      onClick={() => void savePrompt(detail)}
      disabled={disabled}
      loading={detail.saving}
    >
      {detail.conflict
        ? t('settings.prompts.saveAsCopy')
        : (label ?? t('modals.prompts.save'))}
    </Button>
  );
}

/**
 * The notice over an editable prompt whose save was refused over someone's
 * newer edit, with Save as copy; nothing otherwise.
 */
export function PromptConflictNotice({
  detail,
  disabled,
}: {
  detail: PromptDetail;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  if (!detail.conflict || detail.readOnly) return null;
  return (
    <Alert variant="warning" data-slot="prompt-conflict">
      <AlertTitle>{t('settings.prompts.conflict.title')}</AlertTitle>
      <AlertDescription>
        <p>
          {t('settings.prompts.conflict.description')}{' '}
          <AlertAction
            onClick={() => void detail.save({ asCopy: true })}
            disabled={disabled}
          >
            {t('settings.prompts.saveAsCopy')}
          </AlertAction>
        </p>
      </AlertDescription>
    </Alert>
  );
}

/**
 * Leaving a prompt with unsaved changes: Save and leave (a copy after a
 * conflict), or leave without saving. Pending while the save runs; a
 * refused save rejects, so its error stays in the dialog and the view
 * stays. A prompt that can't be saved yet (an open review, no name) rejects
 * with what stops it, which the dialog says.
 *
 * Args:
 *   detail: The open prompt.
 *   reviewing: The drafter's changes are under review in the text.
 *   onClose: Close the dialog (after a save, or with leave without saving).
 *   onLeave: Leave the prompt without saving.
 */
export function PromptLeaveDialog({
  detail,
  reviewing,
  onClose,
  onLeave,
}: {
  detail: PromptDetail;
  reviewing: boolean;
  onClose: () => void;
  onLeave: () => void;
}) {
  const { t } = useTranslation();
  return (
    <ConfirmationModal
      message={t('settings.prompts.unsavedChanges')}
      modalState="ACTIVE"
      setModalState={(state) => {
        if (state !== 'ACTIVE') onClose();
      }}
      submitLabel={
        detail.conflict
          ? t('settings.prompts.saveCopyAndLeave')
          : t('settings.prompts.saveAndLeave')
      }
      handleSubmit={async () => {
        if (reviewing) throw new Error('review');
        if (!detail.canSave) throw new Error(detail.saveBlocker ?? 'failed');
        const result = await savePrompt(detail, { quiet: true });
        if (result !== 'saved') throw new Error(result);
        onClose();
      }}
      error={(reason) =>
        t(
          LEAVE_ERRORS[reason instanceof Error ? reason.message : 'failed'] ??
            'settings.prompts.saveFailed',
        )
      }
      cancelLabel={t('settings.prompts.leaveWithoutSaving')}
      handleCancel={() => {
        onClose();
        onLeave();
      }}
    />
  );
}
