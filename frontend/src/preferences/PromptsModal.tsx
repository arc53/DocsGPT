import { Book } from 'lucide-react';
import { ActiveState } from '../models/misc';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { FormField } from '../components/ui/form-field';
import { Link } from 'react-router-dom';

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
import { UserToolType } from '../settings/types';

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
  /** Which variables the menu inserts; sets the trigger's width. */
  kind: 'system' | 'tool';
};

function VariableMenu({
  options,
  label,
  textareaId,
  content,
  setContent,
  kind,
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
        size="field"
        shape="pill"
        className={
          kind === 'system'
            ? 'w-[140px] sm:w-[185px]'
            : 'w-[140px] sm:w-[171px]'
        }
      >
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent align="start">
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
      <Textarea
        id={id}
        size="lg"
        resize="none"
        className="relative z-10 h-48 md:h-64 lg:h-80"
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

function AddPrompt({
  newPromptName,
  setNewPromptName,
  newPromptContent,
  setNewPromptContent,
}: {
  newPromptName: string;
  setNewPromptName: (name: string) => void;
  newPromptContent: string;
  setNewPromptContent: (content: string) => void;
}) {
  const { t } = useTranslation();
  const systemVariableOptions = React.useMemo(
    () => buildSystemVariableOptions(t),
    [t],
  );
  const toolVariables = useToolVariables();

  return (
    <div>
      <div className="flex flex-col gap-5">
        <FormField label={t('modals.prompts.promptName')}>
          <Input
            type="text"
            value={newPromptName}
            onChange={(e) => setNewPromptName(e.target.value)}
          />
        </FormField>

        <FormField label={t('modals.prompts.promptText')}>
          <PromptTextarea
            id="new-prompt-content"
            value={newPromptContent}
            onChange={(e) => setNewPromptContent(e.target.value)}
          />
        </FormField>
      </div>

      <div className="mt-6 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center sm:gap-4">
        <p className="text-foreground flex flex-col text-sm font-medium">
          <span className="font-bold">
            {t('modals.prompts.variablesLabel')}
          </span>
          <span className="text-muted-foreground text-xs font-medium">
            {t('modals.prompts.variablesDescription')}
          </span>
        </p>

        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <VariableMenu
            options={systemVariableOptions}
            label={t('modals.prompts.systemVariablesDropdownLabel')}
            textareaId="new-prompt-content"
            content={newPromptContent}
            setContent={setNewPromptContent}
            kind="system"
          />

          <VariableMenu
            options={toolVariables}
            label={t('modals.prompts.toolVariables')}
            textareaId="new-prompt-content"
            content={newPromptContent}
            setContent={setNewPromptContent}
            kind="tool"
          />
        </div>
      </div>
    </div>
  );
}

function EditPrompt({
  editPromptName,
  setEditPromptName,
  editPromptContent,
  setEditPromptContent,
  currentPromptEdit,
}: {
  editPromptName: string;
  setEditPromptName: (name: string) => void;
  editPromptContent: string;
  setEditPromptContent: (content: string) => void;
  currentPromptEdit: { name: string; id: string; type: string };
}) {
  const { t } = useTranslation();
  const systemVariableOptions = React.useMemo(
    () => buildSystemVariableOptions(t),
    [t],
  );
  const toolVariables = useToolVariables();
  const isReadOnly = currentPromptEdit.type === 'public';

  return (
    <div>
      <div className="flex flex-col gap-5">
        <FormField label={t('modals.prompts.promptName')}>
          <Input
            type="text"
            value={editPromptName}
            onChange={(e) => setEditPromptName(e.target.value)}
            disabled={isReadOnly}
          />
        </FormField>

        <FormField label={t('modals.prompts.promptText')}>
          <PromptTextarea
            id="edit-prompt-content"
            value={editPromptContent}
            onChange={(e) => setEditPromptContent(e.target.value)}
            readOnly={isReadOnly}
          />
        </FormField>
      </div>

      {!isReadOnly && (
        <div className="mt-6 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center sm:gap-4">
          <p className="text-foreground flex flex-col text-sm font-medium">
            <span className="font-bold">
              {t('modals.prompts.variablesLabel')}
            </span>
            <span className="text-muted-foreground text-xs font-medium">
              {t('modals.prompts.variablesDescription')}
            </span>
          </p>

          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <VariableMenu
              options={systemVariableOptions}
              label={t('modals.prompts.systemVariablesDropdownLabel')}
              textareaId="edit-prompt-content"
              content={editPromptContent}
              setContent={setEditPromptContent}
              kind="system"
            />

            <VariableMenu
              options={toolVariables}
              label={t('modals.prompts.toolVariables')}
              textareaId="edit-prompt-content"
              content={editPromptContent}
              setContent={setEditPromptContent}
              kind="tool"
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
  };
  handleAddPrompt?: () => void;
  handleEditPrompt?: (id: string, type: string) => void;
  onDuplicate?: () => void;
  duplicateSourceName?: string | null;
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
  const isReadOnly = type === 'EDIT' && currentPromptEdit.type === 'public';
  const closeModal = () => setModalState('INACTIVE');

  let view;
  let title: string;
  let description: string;

  if (type === 'ADD') {
    title = duplicateSourceName
      ? t('modals.prompts.duplicatePrompt')
      : t('modals.prompts.addPrompt');
    description = duplicateSourceName
      ? t('modals.prompts.duplicateDescription', {
          name: duplicateSourceName,
        })
      : t('modals.prompts.addDescription');
    view = (
      <AddPrompt
        newPromptName={newPromptName}
        setNewPromptName={setNewPromptName}
        newPromptContent={newPromptContent}
        setNewPromptContent={setNewPromptContent}
      />
    );
  } else {
    title = t(
      isReadOnly ? 'modals.prompts.viewPrompt' : 'modals.prompts.editPrompt',
    );
    description = t(
      isReadOnly
        ? 'modals.prompts.viewDescription'
        : 'modals.prompts.editDescription',
    );
    view = (
      <EditPrompt
        editPromptName={editPromptName}
        setEditPromptName={setEditPromptName}
        editPromptContent={editPromptContent}
        setEditPromptContent={setEditPromptContent}
        currentPromptEdit={currentPromptEdit}
      />
    );
  }

  const learnLink = (
    <Button variant="link" size="inline" asChild>
      <Link
        to="https://docs.docsgpt.cloud/Guides/Customising-prompts"
        target="_blank"
        rel="noopener noreferrer"
      >
        <Book />
        <span className="font-bold">
          {t('modals.prompts.learnAboutPrompts')}
        </span>
      </Link>
    </Button>
  );

  let footer: React.ReactNode;
  if (type === 'ADD') {
    footer = (
      <ModalActions
        footerStart={learnLink}
        cancelLabel={t('modals.prompts.cancel')}
        onCancel={closeModal}
        submitLabel={t('modals.prompts.save')}
        onSubmit={handleAddPrompt}
        disabled={disableSave}
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
          handleEditPrompt?.(currentPromptEdit.id, currentPromptEdit.type)
        }
        disabled={disableSave || !editPromptName}
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
        cancelLabel={t('modals.prompts.cancel')}
        onCancel={closeModal}
        submitLabel={t('modals.prompts.duplicate')}
        onSubmit={onDuplicate}
      />
    );
  } else {
    // A public prompt with nothing to do but close: the link and a lone
    // Cancel.
    footer = (
      <ModalActions
        footerStart={learnLink}
        cancelLabel={t('modals.prompts.cancel')}
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
      mobileVariant="sheet"
      contentClassName="!overflow-visible"
    >
      {view}
    </Modal>
  );
}
