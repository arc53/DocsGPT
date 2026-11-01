import { ExternalLink, WandSparkles } from 'lucide-react';
import { ActiveState } from '../models/misc';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { FormField } from '../components/ui/form-field';
import { SectionHeader } from '../components/ui/section-header';
import ViewOnlyNotice from '../components/ViewOnlyNotice';

import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Modal, ModalActions } from '../components/ui/modal';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import { ResourceUsage, UserToolType } from '../settings/types';
import { DraftedField } from '../drafter/DraftedBadge';
import { PromptAskBar } from '../drafter/PromptAskBar';
import { PromptEditReview } from '../drafter/PromptEditReview';
import { promptDrafterMode } from '../drafter/promptDraft';
import { useDrafterConfig } from '../drafter/useDrafterConfig';
import {
  type PromptDrafterAgent,
  usePromptDrafter,
} from '../drafter/usePromptDrafter';
import { formatCount } from '../utils/dateTimeUtils';
import { agentUseCount } from '../utils/resourceUsage';

const variablePattern = /(\{\{\s*[^{}]+\s*\}\}|\{(?!\{)[^{}]+\})/g;

const highlightPromptVariables = (text: string): React.ReactNode[] => {
  if (!text) {
    return ['\u200B'];
  }
  variablePattern.lastIndex = 0;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = variablePattern.exec(text)) !== null) {
    const precedingText = text.slice(lastIndex, match.index);
    if (precedingText) {
      parts.push(precedingText);
    }
    parts.push(
      <span key={key++} className="prompt-variable-highlight">
        {match[0]}
      </span>,
    );
    lastIndex = match.index + match[0].length;
  }

  const remainingText = text.slice(lastIndex);
  if (remainingText) {
    parts.push(remainingText);
  }

  return parts.length > 0 ? parts : ['\u200B'];
};

const systemVariableOptionDefinitions = [
  {
    labelKey: 'modals.prompts.systemVariableOptions.sourceContent',
    value: 'source.content',
  },
  {
    labelKey: 'modals.prompts.systemVariableOptions.sourceSummaries',
    value: 'source.summaries',
  },
  {
    labelKey: 'modals.prompts.systemVariableOptions.sourceDocuments',
    value: 'source.documents',
  },
  {
    labelKey: 'modals.prompts.systemVariableOptions.sourceCount',
    value: 'source.count',
  },
  {
    // The built-in prompts' Citations section: a template prompt cites
    // with [n] once it has this (docs: Agents › Prompts › Citations).
    labelKey: 'modals.prompts.systemVariableOptions.citationRules',
    value: 'source.citation_rules',
  },
  {
    labelKey: 'modals.prompts.systemVariableOptions.systemDate',
    value: 'system.date',
  },
  {
    labelKey: 'modals.prompts.systemVariableOptions.systemTime',
    value: 'system.time',
  },
  {
    labelKey: 'modals.prompts.systemVariableOptions.systemTimestamp',
    value: 'system.timestamp',
  },
  {
    labelKey: 'modals.prompts.systemVariableOptions.systemRequestId',
    value: 'system.request_id',
  },
  {
    labelKey: 'modals.prompts.systemVariableOptions.systemUserId',
    value: 'system.user_id',
  },
  {
    labelKey: 'modals.prompts.systemVariableOptions.artifactsLookup',
    value: 'artifacts.artifact(id)',
  },
];

const buildSystemVariableOptions = (translate: (key: string) => string) =>
  systemVariableOptionDefinitions.map(({ value, labelKey }) => ({
    value,
    label: translate(labelKey),
  }));

type VariableMenuProps = {
  options: { label: string; value: string }[];
  label: string;
  textareaId: string;
  content: string;
  setContent: (content: string) => void;
};

function VariableMenu({
  options,
  label,
  textareaId,
  content,
  setContent,
}: VariableMenuProps) {
  const handleSelect = (value: string) => {
    const textarea = document.getElementById(textareaId) as HTMLTextAreaElement;
    if (!textarea) return;
    const cursorPosition = textarea.selectionStart;
    const textBefore = content.slice(0, cursorPosition);
    const textAfter = content.slice(cursorPosition);

    // Add leading space if needed
    const needsSpace =
      cursorPosition > 0 && content.charAt(cursorPosition - 1) !== ' ';

    const newText =
      textBefore + (needsSpace ? ' ' : '') + `{{ ${value} }}` + textAfter;
    setContent(newText);

    setTimeout(() => {
      textarea.focus();
      const insertedLen = value.length + 6 + (needsSpace ? 1 : 0);
      textarea.setSelectionRange(
        cursorPosition + insertedLen,
        cursorPosition + insertedLen,
      );
    }, 0);
  };

  // An insert menu on a Select that never keeps a value: the placeholder
  // stands in for the label, and every pick inserts and resets to "".
  return (
    <Select value="" onValueChange={handleSelect}>
      <SelectTrigger
        // Sized to the label; a phone stacks the two menus full width.
        className="w-full sm:w-fit"
      >
        <SelectValue placeholder={label} />
      </SelectTrigger>
      {/* As wide as its longest option and opening leftward from the
          trigger's right end, so a long tool action never runs off the
          dialog; capped so it scrolls instead of filling the window. */}
      <SelectContent align="end" fit capped>
        {options.map((opt) => (
          <SelectItem key={opt.value} value={opt.value}>
            {opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

type PromptTextareaProps = {
  id: string;
  value: string;
  onChange: (event: React.ChangeEvent<HTMLTextAreaElement>) => void;
  readOnly?: boolean;
};

function PromptTextarea({
  id,
  value,
  onChange,
  readOnly = false,
}: PromptTextareaProps) {
  const [scrollOffsets, setScrollOffsets] = React.useState({ top: 0, left: 0 });
  const highlightedValue = React.useMemo(
    () => highlightPromptVariables(value),
    [value],
  );

  const handleScroll = (event: React.UIEvent<HTMLTextAreaElement>) => {
    const { scrollTop, scrollLeft } = event.currentTarget;
    setScrollOffsets({
      top: scrollTop,
      left: scrollLeft,
    });
  };

  // One relative box holding the highlight overlay and the Textarea, so it
  // can be a FormField's single child; the FormField label comes later in
  // the DOM, so at the Textarea's z-10 it still paints on top.
  return (
    <div className="relative w-full">
      <div
        className="bg-card pointer-events-none absolute inset-0 z-0 overflow-hidden rounded-2xl border border-transparent px-4 py-3"
        aria-hidden="true"
      >
        <div
          className="min-h-full translate-x-(--scroll-x) translate-y-(--scroll-y) text-base wrap-break-word whitespace-pre-wrap text-transparent md:text-sm"
          style={
            {
              '--scroll-x': `${-scrollOffsets.left}px`,
              '--scroll-y': `${-scrollOffsets.top}px`,
            } as React.CSSProperties
          }
        >
          {highlightedValue}
        </div>
      </div>
      {/* Capped to the window height so the variable menus below it stay in
          view on a short laptop screen; the modal body scrolls past that. */}
      <Textarea
        id={id}
        size="lg"
        resize="none"
        className="relative z-10 h-48 max-h-[35dvh] md:h-64 lg:h-80"
        value={value}
        onChange={onChange}
        onScroll={handleScroll}
        readOnly={readOnly}
      />
    </div>
  );
}

// Custom hook for fetching tool variables
const useToolVariables = () => {
  const token = useSelector(selectToken);
  const [toolVariables, setToolVariables] = React.useState<
    { label: string; value: string }[]
  >([]);

  React.useEffect(() => {
    const fetchToolVariables = async () => {
      try {
        const response = await userService.getUserTools(token);
        const data = await response.json();

        if (data.success && data.tools) {
          const filteredActions: { label: string; value: string }[] = [];

          data.tools.forEach((tool: UserToolType) => {
            if (tool.actions && tool.status) {
              // Only include active tools
              tool.actions.forEach((action: any) => {
                if (action.active) {
                  const canUseAction =
                    !action.parameters?.properties ||
                    Object.entries(action.parameters.properties).every(
                      ([paramName, param]: [string, any]) => {
                        // Parameter is usable if:
                        // 1. It's filled by LLM (true) OR
                        // 2. It has a value in the tool config
                        return (
                          param.filled_by_llm === true ||
                          (tool.config &&
                            tool.config[paramName] &&
                            tool.config[paramName] !== '')
                        );
                      },
                    );

                  if (canUseAction) {
                    const toolIdentifier = tool.id ?? tool.name;
                    if (!toolIdentifier) {
                      return;
                    }
                    filteredActions.push({
                      label: `${action.name} (${tool.displayName || tool.name})`,
                      value: `tools['${toolIdentifier}'].${action.name}`,
                    });
                  }
                }
              });
            }
          });

          setToolVariables(filteredActions);
        }
      } catch (error) {
        console.error('Error fetching tool variables:', error);
      }
    };

    fetchToolVariables();
  }, [token]);

  return toolVariables;
};

type DraftedSlot = {
  drafted: boolean;
  onUndo: () => void;
};

/**
 * A prompt's name and text with the variable menus, for Add (`new`) and
 * Edit (`edit`). The drafter's slots: `top` (the ask bar or "Improve a
 * copy"), `review` (an improve proposal shown in place of the text and the
 * menus), the Drafted marks, and `locked` (the name and text are read-only
 * while a draft runs).
 */
function PromptFields({
  idPrefix,
  name,
  setName,
  content,
  setContent,
  isReadOnly = false,
  showViewOnlyNotice = false,
  top,
  review,
  draftedName,
  draftedContent,
  contentHint,
  locked = false,
}: {
  idPrefix: 'new' | 'edit';
  name: string;
  setName: (name: string) => void;
  content: string;
  setContent: (content: string) => void;
  isReadOnly?: boolean;
  /** A shared prompt the caller's role can't change (not a built-in one). */
  showViewOnlyNotice?: boolean;
  top?: React.ReactNode;
  review?: React.ReactNode;
  draftedName?: DraftedSlot;
  draftedContent?: DraftedSlot;
  contentHint?: React.ReactNode;
  locked?: boolean;
}) {
  const { t } = useTranslation();
  const systemVariableOptions = React.useMemo(
    () => buildSystemVariableOptions(t),
    [t],
  );
  const toolVariables = useToolVariables();
  const textareaId = `${idPrefix}-prompt-content`;

  return (
    <div>
      <div className="flex flex-col gap-5">
        {showViewOnlyNotice && <ViewOnlyNotice />}
        {top}
        <DraftedField
          drafted={draftedName?.drafted ?? false}
          onUndo={draftedName?.onUndo ?? (() => undefined)}
          fieldLabel={t('modals.prompts.promptName')}
        >
          <FormField label={t('modals.prompts.promptName')}>
            <Input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isReadOnly}
              readOnly={locked}
            />
          </FormField>
        </DraftedField>

        {review ?? (
          <DraftedField
            drafted={draftedContent?.drafted ?? false}
            onUndo={draftedContent?.onUndo ?? (() => undefined)}
            fieldLabel={t('modals.prompts.promptText')}
          >
            <FormField
              label={t('modals.prompts.promptText')}
              hint={contentHint}
            >
              <PromptTextarea
                id={textareaId}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                readOnly={isReadOnly || locked}
              />
            </FormField>
          </DraftedField>
        )}
      </div>

      {!isReadOnly && !review && (
        <div className="mt-6 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center sm:gap-4">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('modals.prompts.variablesLabel')}
            description={t('modals.prompts.variablesDescription')}
          />

          <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center sm:gap-3">
            <VariableMenu
              options={systemVariableOptions}
              label={t('modals.prompts.systemVariablesDropdownLabel')}
              textareaId={textareaId}
              content={content}
              setContent={setContent}
            />

            <VariableMenu
              options={toolVariables}
              label={t('modals.prompts.toolVariables')}
              textareaId={textareaId}
              content={content}
              setContent={setContent}
            />
          </div>
        </div>
      )}
    </div>
  );
}

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
  const review = drafter.review ? (
    <PromptEditReview review={drafter.review} onDecide={drafter.decide} />
  ) : undefined;

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
      <PromptFields
        idPrefix="new"
        name={newPromptName}
        setName={setNewPromptName}
        content={newPromptContent}
        setContent={setNewPromptContent}
        top={drafterTop}
        review={review}
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
      <PromptFields
        idPrefix="edit"
        name={editPromptName}
        setName={setEditPromptName}
        content={editPromptContent}
        setContent={setEditPromptContent}
        isReadOnly={isReadOnly}
        showViewOnlyNotice={showViewOnlyNotice}
        top={drafterTop}
        review={review}
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
