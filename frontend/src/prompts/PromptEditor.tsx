import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ViewOnlyNotice from '../components/ViewOnlyNotice';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { Textarea } from '../components/ui/textarea';
import { DraftedField } from '../drafter/DraftedBadge';
import { PromptEditReview } from '../drafter/PromptEditReview';
import type { PromptDecision, PromptReview } from '../drafter/usePromptDrafter';
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
        className="bg-background pointer-events-none absolute inset-0 z-0 overflow-hidden rounded-2xl border border-transparent px-4 py-3"
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
          view on a short laptop screen; the page scrolls past that. */}
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

/** A field's Drafted mark and its undo. */
export type DraftedSlot = {
  drafted: boolean;
  onUndo: () => void;
};

export type PromptEditorProps = {
  /** Prefixes the text field's id, which the variable menus insert into. */
  idPrefix: string;
  name: string;
  setName: (name: string) => void;
  content: string;
  setContent: (content: string) => void;
  /** The name is disabled and the text read-only; no variable menus. */
  isReadOnly?: boolean;
  /** A shared prompt the caller's role can't change (not a built-in one). */
  showViewOnlyNotice?: boolean;
  /** An improve proposal under review, shown in place of the text and the menus. */
  review?: PromptReview | null;
  /** Accept or reject one of the review's changes; null takes a choice back. */
  onDecide?: (id: string, decision: PromptDecision | null) => void;
  draftedName?: DraftedSlot;
  draftedContent?: DraftedSlot;
  /** Under the name field, in red ("Name already exists"). */
  nameError?: string;
  /** The name and text are read-only while a draft runs. */
  locked?: boolean;
};

/**
 * A prompt's name and text with the variable menus, on the page's
 * background (the prompt view's editor). The text highlights its `{{ }}`
 * variables, and the System and Tool variables menus insert one at the
 * cursor. The drafter's parts: the Drafted marks with undo, an improve
 * proposal's review in place of the text (its per-change Accept and Reject
 * inline), and `locked` while a draft runs. A prompt to view has the name
 * disabled, the text read-only and no menus.
 */
export function PromptEditor({
  idPrefix,
  name,
  setName,
  content,
  setContent,
  isReadOnly = false,
  showViewOnlyNotice = false,
  review,
  onDecide,
  draftedName,
  draftedContent,
  nameError,
  locked = false,
}: PromptEditorProps) {
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
        <DraftedField
          drafted={draftedName?.drafted ?? false}
          onUndo={draftedName?.onUndo ?? (() => undefined)}
          fieldLabel={t('modals.prompts.promptName')}
        >
          <FormField
            label={t('modals.prompts.promptName')}
            error={nameError}
            labelSurface="background"
          >
            <Input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isReadOnly}
              readOnly={locked}
            />
          </FormField>
        </DraftedField>

        {review && onDecide ? (
          <PromptEditReview review={review} onDecide={onDecide} />
        ) : (
          <DraftedField
            drafted={draftedContent?.drafted ?? false}
            onUndo={draftedContent?.onUndo ?? (() => undefined)}
            fieldLabel={t('modals.prompts.promptText')}
          >
            <FormField
              label={t('modals.prompts.promptText')}
              labelSurface="background"
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

      {!isReadOnly && !(review && onDecide) && (
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
