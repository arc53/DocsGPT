import { ExternalLink, WandSparkles } from 'lucide-react';
import { ActiveState } from '../models/misc';
import { Button } from '../components/ui/button';

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Modal, ModalActions } from '../components/ui/modal';
import { ResourceUsage } from '../settings/types';
import { PromptAskBar } from '../drafter/PromptAskBar';
import { promptDrafterMode } from '../drafter/promptDraft';
import { useDrafterConfig } from '../drafter/useDrafterConfig';
import {
  type PromptDrafterAgent,
  usePromptDrafter,
} from '../drafter/usePromptDrafter';
import { formatCount } from '../utils/dateTimeUtils';
import { agentUseCount } from '../utils/resourceUsage';
import { PromptEditor } from '../prompts/PromptEditor';

export default function PromptsModal({
  existingPrompts,
  modalState,
  setModalState,
  type,
  newPromptName,
  setNewPromptName,
  newPromptContent,
  setNewPromptContent,
  editPromptName,
  setEditPromptName,
  editPromptContent,
  setEditPromptContent,
  currentPromptEdit,
  handleAddPrompt,
  handleEditPrompt,
  onDuplicate,
  duplicateSourceName,
  readOnly = false,
  drafterAgent = null,
  autoFocusAsk = false,
  pendingEdit = false,
}: {
  existingPrompts: { name: string; id: string; type: string }[];
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  type: 'ADD' | 'EDIT';
  newPromptName: string;
  setNewPromptName: (name: string) => void;
  newPromptContent: string;
  setNewPromptContent: (content: string) => void;
  editPromptName: string;
  setEditPromptName: (name: string) => void;
  editPromptContent: string;
  setEditPromptContent: (content: string) => void;
  currentPromptEdit: {
    name: string;
    id: string;
    type: string;
    content?: string;
    /** The agents that use it: a save changes every one of them. */
    used_by?: ResourceUsage | null;
  };
  /** Return the request's promise to show pending on Save while it runs. */
  handleAddPrompt?: () => void | Promise<unknown>;
  handleEditPrompt?: (id: string, type: string) => void | Promise<unknown>;
  onDuplicate?: () => void;
  duplicateSourceName?: string | null;
  /** Open an EDIT prompt as a view: the caller may not edit it. */
  readOnly?: boolean;
  /** The agent form it was opened from, so the drafter tailors the prompt to it. */
  drafterAgent?: PromptDrafterAgent | null;
  /** Put the cursor in the drafter's ask bar when it opens (an Improve entry). */
  autoFocusAsk?: boolean;
  /**
   * An ADD that edits a drafted prompt the agent form holds: titled Edit,
   * since the agent's save creates it.
   */
  pendingEdit?: boolean;
}) {
  const disableSave = React.useMemo(() => {
    if (type === 'EDIT') {
      const nameExists = existingPrompts.some(
        (prompt) =>
          prompt.name === editPromptName && prompt.id !== currentPromptEdit.id,
      );
      return !editPromptName || nameExists || editPromptContent.trim() === '';
    }
    const nameExists = existingPrompts.some(
      (prompt) => prompt.name === newPromptName,
    );
    return !newPromptName || nameExists || newPromptContent.trim() === '';
  }, [
    type,
    existingPrompts,
    editPromptName,
    editPromptContent,
    currentPromptEdit.id,
    newPromptName,
    newPromptContent,
  ]);

  const { t } = useTranslation();
  const isBuiltIn = currentPromptEdit.type === 'public';
  const isReadOnly = type === 'EDIT' && (readOnly || isBuiltIn);
  // A built-in prompt explains itself in the description (duplicate it to
  // edit); a shared one the role can't change gets the shared notice.
  const showViewOnlyNotice = isReadOnly && !isBuiltIn;
  const closeModal = () => setModalState('INACTIVE');

  // The drafter ("Draft with DocsGPT"): an ask bar that improves the prompt
  // with reviewed edits or writes an empty one. Hidden while it's off, and on
  // a prompt the caller can't change, which offers to improve a copy.
  const drafterConfig = useDrafterConfig();
  const drafterOn = drafterConfig?.enabled === true;
  const isAdd = type === 'ADD';
  const drafter = usePromptDrafter({
    mode: promptDrafterMode(type, isAdd ? newPromptContent : editPromptContent),
    promptId: isAdd ? null : currentPromptEdit.id || null,
    name: isAdd ? newPromptName : editPromptName,
    content: isAdd ? newPromptContent : editPromptContent,
    setName: isAdd ? setNewPromptName : setEditPromptName,
    setContent: isAdd ? setNewPromptContent : setEditPromptContent,
    agent: drafterAgent,
  });
  const resetDrafter = drafter.reset;
  const open = modalState === 'ACTIVE';
  // A new opening, another prompt, or Duplicate starts the drafter over.
  React.useEffect(() => {
    resetDrafter();
  }, [open, type, currentPromptEdit.id, resetDrafter]);

  const askRef = React.useRef<HTMLInputElement>(null);
  const [focusAsk, setFocusAsk] = React.useState(0);
  React.useEffect(() => {
    if (!open || (!autoFocusAsk && focusAsk === 0)) return;
    // After the dialog's own open focus.
    const frame = requestAnimationFrame(() => askRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [open, autoFocusAsk, focusAsk, type]);
  React.useEffect(() => {
    if (!open) setFocusAsk(0);
  }, [open]);

  const usedBy = agentUseCount(currentPromptEdit.used_by);
  const draftedSlot = (field: 'name' | 'content') => ({
    drafted: drafter.drafted.isDrafted(field),
    onUndo: () => drafter.drafted.undo(field),
  });
  const drafterTop = !drafterOn ? null : isReadOnly ? (
    onDuplicate && (
      <div>
        <Button
          type="button"
          variant="outline-primary"
          size="field"
          shape="pill"
          data-drafter-entry=""
          onClick={() => {
            onDuplicate();
            setFocusAsk((tick) => tick + 1);
          }}
        >
          <WandSparkles />
          {t('drafter.prompt.improveCopy')}
        </Button>
      </div>
    )
  ) : (
    <PromptAskBar
      session={drafter.session}
      mode={promptDrafterMode(
        type,
        isAdd ? newPromptContent : editPromptContent,
      )}
      result={drafter.result}
      inputRef={askRef}
      // A request mid-review would send the half-applied text and drop the
      // changes not chosen yet.
      reviewing={drafter.review !== null}
    />
  );
  // Save shows pending while the caller's request runs; a second click
  // meanwhile is ignored.
  const [saving, setSaving] = React.useState(false);
  const save = (submit: () => void | Promise<unknown>) => {
    if (saving) return;
    const result = submit();
    if (!result || typeof result.then !== 'function') return;
    setSaving(true);
    const done = () => setSaving(false);
    result.then(done, done);
  };

  let view;
  let title: string;
  let description: string | undefined;

  if (type === 'ADD') {
    title = pendingEdit
      ? t('modals.prompts.editPrompt')
      : duplicateSourceName
        ? t('modals.prompts.duplicatePrompt')
        : t('modals.prompts.addPrompt');
    description = pendingEdit
      ? t('modals.prompts.pendingDescription')
      : duplicateSourceName
        ? t('modals.prompts.duplicateDescription', {
            name: duplicateSourceName,
          })
        : t('modals.prompts.addDescription');
    view = (
      <PromptEditor
        idPrefix="new"
        name={newPromptName}
        setName={setNewPromptName}
        content={newPromptContent}
        setContent={setNewPromptContent}
        top={drafterTop}
        review={drafter.review}
        onDecide={drafter.decide}
        draftedName={draftedSlot('name')}
        draftedContent={draftedSlot('content')}
        locked={drafter.session.streaming}
      />
    );
  } else {
    title = t(
      isReadOnly ? 'modals.prompts.viewPrompt' : 'modals.prompts.editPrompt',
    );
    description = isBuiltIn
      ? t('modals.prompts.viewDescription')
      : isReadOnly
        ? undefined
        : t('modals.prompts.editDescription');
    view = (
      <PromptEditor
        idPrefix="edit"
        name={editPromptName}
        setName={setEditPromptName}
        content={editPromptContent}
        setContent={setEditPromptContent}
        isReadOnly={isReadOnly}
        showViewOnlyNotice={showViewOnlyNotice}
        top={drafterTop}
        review={drafter.review}
        onDecide={drafter.decide}
        draftedName={draftedSlot('name')}
        draftedContent={draftedSlot('content')}
        locked={drafter.session.streaming}
        contentHint={
          !isReadOnly && usedBy > 1
            ? t('drafter.prompt.usedBy', {
                count: usedBy,
                formatted: formatCount(usedBy),
              })
            : undefined
        }
      />
    );
  }

  const learnLink = (
    <Button variant="link" size="inline" asChild>
      <a
        href="https://docs.docsgpt.cloud/Agents/prompts"
        target="_blank"
        rel="noopener noreferrer"
      >
        {t('modals.prompts.learnAboutPrompts')}
        <ExternalLink />
      </a>
    </Button>
  );

  let footer: React.ReactNode;
  if (drafter.review) {
    // Reviewing an improvement: choose its changes before saving.
    footer = (
      <ModalActions
        footerStart={
          drafter.review.current === null ? (
            <Button
              type="button"
              variant="outline"
              size="lg"
              shape="pill"
              onClick={drafter.reviewOneByOne}
            >
              {t('drafter.prompt.reviewOneByOne')}
            </Button>
          ) : undefined
        }
        cancelLabel={t('drafter.prompt.discard')}
        onCancel={drafter.discard}
        submitLabel={t('drafter.prompt.acceptAll')}
        onSubmit={drafter.acceptAll}
      />
    );
  } else if (type === 'ADD') {
    footer = (
      <ModalActions
        footerStart={learnLink}
        cancelLabel={t('modals.prompts.cancel')}
        onCancel={closeModal}
        submitLabel={t('modals.prompts.save')}
        onSubmit={() => handleAddPrompt && save(handleAddPrompt)}
        pending={saving}
        disabled={disableSave || drafter.session.streaming}
      />
    );
  } else if (!isReadOnly) {
    footer = (
      <ModalActions
        footerStart={learnLink}
        cancelLabel={t('modals.prompts.cancel')}
        onCancel={closeModal}
        submitLabel={t('modals.prompts.save')}
        onSubmit={() =>
          handleEditPrompt &&
          save(() =>
            handleEditPrompt(currentPromptEdit.id, currentPromptEdit.type),
          )
        }
        pending={saving}
        disabled={disableSave || !editPromptName || drafter.session.streaming}
        submitProps={{
          title:
            disableSave && editPromptName ? t('modals.prompts.nameExists') : '',
        }}
      />
    );
  } else if (onDuplicate) {
    footer = (
      <ModalActions
        footerStart={learnLink}
        cancelLabel={t('common.close')}
        onCancel={closeModal}
        submitLabel={t('modals.prompts.duplicate')}
        onSubmit={onDuplicate}
      />
    );
  } else {
    // A prompt to view with nothing to do but close: the link and a lone
    // Close.
    footer = (
      <ModalActions
        footerStart={learnLink}
        cancelLabel={t('common.close')}
        onCancel={closeModal}
      />
    );
  }

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => {
        if (!o) {
          setModalState('INACTIVE');
          if (type === 'ADD') {
            setNewPromptName('');
            setNewPromptContent('');
          }
        }
      }}
      title={title}
      description={description}
      footer={footer}
      size="xl"
    >
      {view}
    </Modal>
  );
}
