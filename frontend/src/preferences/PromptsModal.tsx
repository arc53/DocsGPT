import { ChevronDown } from 'lucide-react';
import { ActiveState } from '../models/misc';
import { Input } from '../components/ui/input';
import { Link } from 'react-router-dom';

import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Modal } from '../components/ui/modal';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import BookIcon from '../assets/book.svg';
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
  triggerClassName?: string;
  contentClassName?: string;
};

function VariableMenu({
  options,
  label,
  textareaId,
  content,
  setContent,
  triggerClassName,
  contentClassName,
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

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={`border-border bg-card text-foreground hover:bg-accent flex items-center justify-between rounded-3xl border px-5 py-3 text-xs sm:text-sm ${triggerClassName ?? ''}`}
        >
          <span className="truncate">{label}</span>
          <ChevronDown className="text-muted-foreground ml-2 h-4 w-4 shrink-0" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className={`max-h-72 overflow-y-auto ${contentClassName ?? ''}`}
      >
        {options.map((opt) => (
          <DropdownMenuItem
            key={opt.value}
            onSelect={() => handleSelect(opt.value)}
          >
            {opt.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

type PromptTextareaProps = {
  id: string;
  value: string;
  onChange: (event: React.ChangeEvent<HTMLTextAreaElement>) => void;
  ariaLabel: string;
};

function PromptTextarea({
  id,
  value,
  onChange,
  ariaLabel,
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

  return (
    <>
      <div
        className="bg-card pointer-events-none absolute inset-0 z-0 overflow-hidden rounded px-3 py-2"
        aria-hidden="true"
      >
        <div
          className="min-h-full text-base leading-normal wrap-break-word whitespace-pre-wrap text-transparent"
          style={{
            transform: `translate(${-scrollOffsets.left}px, ${-scrollOffsets.top}px)`,
          }}
        >
          {highlightedValue}
        </div>
      </div>
      <textarea
        id={id}
        className="peer border-border dark:border-border relative z-10 h-48 w-full resize-none rounded border-2 bg-transparent px-3 py-2 text-base text-gray-800 outline-none md:h-64 lg:h-80 dark:text-white"
        value={value}
        onChange={onChange}
        onScroll={handleScroll}
        placeholder=" "
        aria-label={ariaLabel}
      />
    </>
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
  setModalState,
  handleAddPrompt,
  newPromptName,
  setNewPromptName,
  newPromptContent,
  setNewPromptContent,
  disableSave,
}: {
  setModalState: (state: ActiveState) => void;
  handleAddPrompt?: () => void;
  newPromptName: string;
  setNewPromptName: (name: string) => void;
  newPromptContent: string;
  setNewPromptContent: (content: string) => void;
  disableSave: boolean;
}) {
  const { t } = useTranslation();
  const systemVariableOptions = React.useMemo(
    () => buildSystemVariableOptions(t),
    [t],
  );
  const toolVariables = useToolVariables();

  return (
    <div>
      <p className="mb-1 text-xl font-semibold text-[#2B2B2B] dark:text-white">
        {t('modals.prompts.addPrompt')}
      </p>
      <p className="dark:text-muted-foreground mb-6 text-sm text-[#6B6B6B]">
        {t('modals.prompts.addDescription')}
      </p>
      <div>
        <Input
          label={t('modals.prompts.promptName')}
          type="text"
          className="mb-5"
          value={newPromptName}
          onChange={(e) => setNewPromptName(e.target.value)}
          labelBgClassName="bg-card"
        />

        <div className="relative w-full">
          <PromptTextarea
            id="new-prompt-content"
            value={newPromptContent}
            onChange={(e) => setNewPromptContent(e.target.value)}
            ariaLabel={t('prompts.textAriaLabel')}
          />
          <label
            htmlFor="new-prompt-content"
            className={`absolute z-20 select-none ${
              newPromptContent ? '-top-2.5 left-3 text-xs' : ''
            } text-muted-foreground bg-card pointer-events-none max-w-[calc(100%-24px)] cursor-none overflow-hidden px-2 text-ellipsis whitespace-nowrap transition-all peer-placeholder-shown:top-2.5 peer-placeholder-shown:left-3 peer-placeholder-shown:text-base peer-focus:-top-2.5 peer-focus:left-3 peer-focus:text-xs`}
          >
            {t('modals.prompts.promptText')}
          </label>
        </div>
      </div>

      <div className="mt-6 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center sm:gap-4">
        <p className="flex flex-col text-sm font-medium text-gray-700 dark:text-gray-300">
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
            triggerClassName="w-[140px] sm:w-[185px]"
          />

          <VariableMenu
            options={toolVariables}
            label="Tool Variables"
            textareaId="new-prompt-content"
            content={newPromptContent}
            setContent={setNewPromptContent}
            triggerClassName="w-[140px] sm:w-[171px]"
          />
        </div>
      </div>
      <div className="mt-4 flex flex-col justify-between gap-4 text-sm sm:flex-row sm:gap-0">
        <div className="flex justify-start">
          <Link
            to="https://docs.docsgpt.cloud/Guides/Customising-prompts"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary flex items-center gap-2 text-sm font-medium hover:underline"
          >
            <img
              src={BookIcon}
              alt=""
              className="flex h-4 w-3 shrink-0 items-center justify-center"
              aria-hidden="true"
            />
            <span className="text-sm font-bold">
              {t('modals.prompts.learnAboutPrompts')}
            </span>
          </Link>
        </div>

        <div className="flex justify-end gap-2 sm:gap-4">
          <button
            onClick={() => setModalState('INACTIVE')}
            className="border-destructive text-destructive hover:bg-destructive rounded-3xl border px-5 py-2 text-sm font-medium transition-all hover:text-white"
          >
            {t('modals.prompts.cancel')}
          </button>

          <button
            onClick={handleAddPrompt}
            className="bg-primary hover:bg-primary/90 disabled:hover:bg-primary rounded-3xl px-6 py-2 text-sm font-medium text-white transition-all disabled:cursor-not-allowed disabled:opacity-50"
            disabled={disableSave}
          >
            {t('modals.prompts.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditPrompt({
  setModalState,
  handleEditPrompt,
  editPromptName,
  setEditPromptName,
  editPromptContent,
  setEditPromptContent,
  currentPromptEdit,
  disableSave,
}: {
  setModalState: (state: ActiveState) => void;
  handleEditPrompt?: (id: string, type: string) => void;
  editPromptName: string;
  setEditPromptName: (name: string) => void;
  editPromptContent: string;
  setEditPromptContent: (content: string) => void;
  currentPromptEdit: { name: string; id: string; type: string };
  disableSave: boolean;
}) {
  const { t } = useTranslation();
  const systemVariableOptions = React.useMemo(
    () => buildSystemVariableOptions(t),
    [t],
  );
  const toolVariables = useToolVariables();

  return (
    <div>
      <p className="mb-1 text-xl font-semibold text-[#2B2B2B] dark:text-white">
        {t('modals.prompts.editPrompt')}
      </p>
      <p className="dark:text-muted-foreground mb-6 text-sm text-[#6B6B6B]">
        {t('modals.prompts.editDescription')}
      </p>
      <div>
        <Input
          label={t('modals.prompts.promptName')}
          type="text"
          className="mb-5"
          value={editPromptName}
          onChange={(e) => setEditPromptName(e.target.value)}
          labelBgClassName="bg-card"
        />

        <div className="relative w-full">
          <PromptTextarea
            id="edit-prompt-content"
            value={editPromptContent}
            onChange={(e) => setEditPromptContent(e.target.value)}
            ariaLabel={t('prompts.textAriaLabel')}
          />
          <label
            htmlFor="edit-prompt-content"
            className={`absolute z-20 select-none ${
              editPromptContent ? '-top-2.5 left-3 text-xs' : ''
            } text-muted-foreground bg-card pointer-events-none max-w-[calc(100%-24px)] cursor-none overflow-hidden px-2 text-ellipsis whitespace-nowrap transition-all peer-placeholder-shown:top-2.5 peer-placeholder-shown:left-3 peer-placeholder-shown:text-base peer-focus:-top-2.5 peer-focus:left-3 peer-focus:text-xs`}
          >
            {t('modals.prompts.promptText')}
          </label>
        </div>
      </div>

      <div className="mt-6 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center sm:gap-4">
        <p className="flex flex-col text-sm font-medium text-gray-700 dark:text-gray-300">
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
            triggerClassName="w-[140px] sm:w-[185px]"
          />

          <VariableMenu
            options={toolVariables}
            label="Tool Variables"
            textareaId="edit-prompt-content"
            content={editPromptContent}
            setContent={setEditPromptContent}
            triggerClassName="w-[140px] sm:w-[171px]"
          />
        </div>
      </div>
      <div className="mt-4 flex flex-col justify-between gap-4 text-sm sm:flex-row sm:gap-0">
        <div className="flex justify-start">
          <Link
            to="https://docs.docsgpt.cloud/Guides/Customising-prompts"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary flex items-center gap-2 text-sm font-medium hover:underline"
          >
            <img
              src={BookIcon}
              alt=""
              className="flex h-4 w-3 shrink-0 items-center justify-center"
              aria-hidden="true"
            />
            <span className="text-sm font-bold">
              {t('modals.prompts.learnAboutPrompts')}
            </span>
          </Link>
        </div>

        <div className="flex justify-end gap-2 sm:gap-4">
          <button
            onClick={() => setModalState('INACTIVE')}
            className="border-destructive text-destructive hover:bg-destructive rounded-3xl border px-5 py-2 text-sm font-medium transition-all hover:text-white"
          >
            {t('modals.prompts.cancel')}
          </button>

          <button
            onClick={() => {
              handleEditPrompt &&
                handleEditPrompt(currentPromptEdit.id, currentPromptEdit.type);
            }}
            className="bg-primary hover:bg-primary/90 disabled:hover:bg-primary rounded-3xl px-6 py-2 text-sm font-medium text-white transition-all disabled:cursor-not-allowed disabled:opacity-50"
            disabled={
              currentPromptEdit.type === 'public' ||
              disableSave ||
              !editPromptName
            }
            title={
              disableSave && editPromptName
                ? t('modals.prompts.nameExists')
                : ''
            }
          >
            {t('modals.prompts.save')}
          </button>
        </div>
      </div>
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
}) {
  const [disableSave, setDisableSave] = React.useState(true);
  const handlePromptNameChange = (edit: boolean, newName: string) => {
    if (edit) {
      const nameExists = existingPrompts.find(
        (prompt) =>
          newName === prompt.name && prompt.id !== currentPromptEdit.id,
      );
      setDisableSave(
        !(
          newName &&
          !nameExists &&
          editPromptName &&
          editPromptContent.trim() !== ''
        ),
      );
      setEditPromptName(newName);
    } else {
      const nameExists = existingPrompts.find(
        (prompt) => newName === prompt.name,
      );
      setDisableSave(
        !(newName && !nameExists && newPromptContent.trim() !== ''),
      );
      setNewPromptName(newName);
    }
  };

  const handleContentChange = (edit: boolean, newContent: string) => {
    if (edit) {
      const nameValid =
        editPromptName &&
        !existingPrompts.find(
          (prompt) =>
            editPromptName === prompt.name &&
            prompt.id !== currentPromptEdit.id,
        );
      setDisableSave(!(nameValid && newContent.trim() !== ''));
      setEditPromptContent(newContent);
    } else {
      const nameValid =
        newPromptName &&
        !existingPrompts.find((prompt) => newPromptName === prompt.name);
      setDisableSave(!(nameValid && newContent.trim() !== ''));
      setNewPromptContent(newContent);
    }
  };

  let view;

  if (type === 'ADD') {
    view = (
      <AddPrompt
        setModalState={setModalState}
        handleAddPrompt={handleAddPrompt}
        newPromptName={newPromptName}
        setNewPromptName={handlePromptNameChange.bind(null, false)}
        newPromptContent={newPromptContent}
        setNewPromptContent={handleContentChange.bind(null, false)}
        disableSave={disableSave}
      />
    );
  } else if (type === 'EDIT') {
    view = (
      <EditPrompt
        setModalState={setModalState}
        handleEditPrompt={handleEditPrompt}
        editPromptName={editPromptName}
        setEditPromptName={handlePromptNameChange.bind(null, true)}
        editPromptContent={editPromptContent}
        setEditPromptContent={handleContentChange.bind(null, true)}
        currentPromptEdit={currentPromptEdit}
        disableSave={disableSave}
      />
    );
  } else {
    view = <></>;
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
      hideTitle
      title={type === 'ADD' ? 'Add Prompt' : 'Edit Prompt'}
      size="lg"
      className="bg-card dark:bg-card mx-4 mt-16 w-[95vw] max-w-[650px] rounded-2xl px-4 py-4 sm:px-6 sm:py-6 md:max-w-[860px] md:px-8 md:py-6 lg:max-w-[980px]"
      contentClassName="!overflow-visible"
    >
      {view}
    </Modal>
  );
}
