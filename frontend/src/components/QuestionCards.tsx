import { Info } from 'lucide-react';
import { Fragment, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';

/**
 * One option. `input` is a placeholder: picking the option opens a field for
 * its value ("HR team email" → "hr@…"), sent as "<label>: <value>".
 * `exclusive` rules out the others in a pick-any question ("No topics").
 */
export type QuestionOption = {
  id: string;
  label: string;
  input?: string | null;
  exclusive?: boolean;
};

/** A clarifying question a model asks: the drafter's, or the chat's `ask_user`. */
export type Question = {
  id: string;
  text: string;
  note: string | null;
  multi: boolean;
  /** Empty for a question the user answers by typing. */
  options: QuestionOption[];
  /** A typed-answer question's example, shown in the empty field. */
  placeholder?: string | null;
};

/** Picked option ids, "Something else"'s text, and each picked option's value. */
type Answer = {
  picked: string[];
  other: string | null;
  values?: Record<string, string>;
};

const NO_ANSWER: Answer = { picked: [], other: null };

/** How many sets of cards keep their picks for a remount (see `memoryKey`). */
const REMEMBERED_MAX = 20;
const remembered = new Map<string, Record<string, Answer>>();

function remember(key: string, answers: Record<string, Answer>) {
  remembered.delete(key);
  remembered.set(key, answers);
  if (remembered.size > REMEMBERED_MAX)
    remembered.delete(remembered.keys().next().value as string);
}

/**
 * A question's answer as text: the picked labels ("<label>: <value>" for one
 * that takes a value), then the free text.
 */
function answerParts(question: Question, answer: Answer): string[] {
  const parts = question.options
    .filter((option) => answer.picked.includes(option.id))
    .map((option) => {
      const value = option.input ? answer.values?.[option.id]?.trim() : '';
      return value ? `${option.label}: ${value}` : option.label;
    });
  const other = answer.other?.trim();
  if (other) parts.push(other);
  return parts;
}

/**
 * Turn the picked options into the one user message the server expects:
 * a line per answered question, "<question> → <answer>, <answer>".
 *
 * Args:
 *   questions: The questions as asked.
 *   answers: Picked option ids and free text per question id.
 *
 * Returns:
 *   The message, or an empty string when nothing was answered.
 */
export function composeAnswers(
  questions: Question[],
  answers: Record<string, Answer>,
): string {
  const byId = answerTexts(questions, answers);
  return questions
    .filter((question) => byId[question.id])
    .map((question) => `${question.text} → ${byId[question.id]}`)
    .join('\n');
}

/** Each answered question's answer as text, by question id. */
function answerTexts(
  questions: Question[],
  answers: Record<string, Answer>,
): Record<string, string> {
  const texts: Record<string, string> = {};
  for (const question of questions) {
    const answer = answers[question.id];
    const parts = answer ? answerParts(question, answer) : [];
    if (parts.length > 0) texts[question.id] = parts.join(', ');
  }
  return texts;
}

/**
 * Clarifying questions as cards of option rows: radios for a one-pick
 * question, checkboxes for a pick-any one (`multi`), and "Something else…"
 * after them, which opens a free-text field under it. An option that takes a
 * value opens its own field under it once picked; an exclusive one ("No
 * topics") goes last, after a rule, and ticking it clears the others (and
 * the other way round). A question with no options is a text field alone. One Send answers button sends
 * every answer as one message. An answered (or passed-over) card shows only
 * the question and what was picked. The drafter and the chat's `ask_user`
 * both draw them.
 *
 * Args:
 *   questions: At most three questions, two to five options each (or none).
 *   active: Whether they can still be answered.
 *   onAnswer: Sends the composed answers; also given each answered
 *     question's answer as text, by id, for a record of them.
 *   onSkip: When given, a Skip button beside Send answers goes on without
 *     answering.
 *   skipLabel: The Skip button's label ("Skip and draft", "Just answer").
 *   answers: Once not active, each question's answer as text, by question
 *     id, in place of what was picked here (an answer saved with a chat).
 *   emptyLabel: Once not active, the line under a question with no answer:
 *     "Not answered" by default; null shows the question alone.
 *   className: Layout only (the gap between the cards).
 *   memoryKey: When given, what was picked outlives the cards: mounted again
 *     under the same key (answers the server refused, shown again for
 *     another try), they come back as they were left.
 */
export function QuestionCards({
  questions,
  active,
  onAnswer,
  onSkip,
  skipLabel,
  answers: givenAnswers,
  emptyLabel,
  className,
  memoryKey,
}: {
  questions: Question[];
  active: boolean;
  onAnswer: (message: string, answers: Record<string, string>) => void;
  onSkip?: () => void;
  skipLabel?: string;
  answers?: Record<string, string | null | undefined>;
  emptyLabel?: string | null;
  className?: string;
  memoryKey?: string;
}) {
  const { t } = useTranslation();
  const baseId = useId();
  const [answers, setAnswers] = useState<Record<string, Answer>>(
    () => (memoryKey && remembered.get(memoryKey)) || {},
  );

  const answerOf = (id: string): Answer => answers[id] ?? NO_ANSWER;
  const update = (id: string, next: Answer) =>
    setAnswers((prev) => {
      const merged = { ...prev, [id]: next };
      if (memoryKey) remember(memoryKey, merged);
      return merged;
    });

  // One pick: an option replaces the other choice and closes "Something
  // else"; `optionId` null is "Something else" itself. A typed value stays
  // in case the user comes back to its option.
  const pickOne = (question: Question, optionId: string | null) => {
    const answer = answerOf(question.id);
    update(
      question.id,
      optionId === null
        ? { ...answer, picked: [], other: answer.other ?? '' }
        : { ...answer, picked: [optionId], other: null },
    );
  };

  const exclusiveIds = (question: Question) =>
    question.options.filter((option) => option.exclusive).map(({ id }) => id);

  // Pick any; an exclusive option clears the rest, and anything else clears
  // the exclusive one. `optionId` null is "Something else".
  const toggle = (question: Question, optionId: string | null, on: boolean) => {
    const answer = answerOf(question.id);
    if (!on) {
      update(
        question.id,
        optionId === null
          ? { ...answer, other: null }
          : {
              ...answer,
              picked: answer.picked.filter((id) => id !== optionId),
            },
      );
      return;
    }
    const exclusive = exclusiveIds(question);
    if (optionId !== null && exclusive.includes(optionId)) {
      update(question.id, { ...answer, picked: [optionId], other: null });
      return;
    }
    const picked = answer.picked.filter((id) => !exclusive.includes(id));
    update(
      question.id,
      optionId === null
        ? { ...answer, picked, other: answer.other ?? '' }
        : { ...answer, picked: [...picked, optionId] },
    );
  };

  const setValue = (question: Question, optionId: string, value: string) => {
    const answer = answerOf(question.id);
    update(question.id, {
      ...answer,
      values: { ...answer.values, [optionId]: value },
    });
  };

  const message = composeAnswers(questions, answers);
  const submit = () => onAnswer(message, answerTexts(questions, answers));

  return (
    <div
      className={cn('flex flex-col gap-3', className)}
      data-slot="question-cards"
    >
      {questions.map((question, index) => {
        const answer = answerOf(question.id);
        // Rows go by position (the radio values too): the option ids are
        // the model's own and could be anything.
        const rowId = (row: string) => `${baseId}-${question.id}-${row}`;
        const title = (
          <p className="text-sm font-medium wrap-break-word">
            {questions.length > 1 ? `${index + 1}. ` : ''}
            {question.text}
          </p>
        );

        if (!active) {
          const given = givenAnswers?.[question.id];
          const parts = givenAnswers
            ? given
              ? [given]
              : []
            : answerParts(question, answer);
          const empty =
            emptyLabel === undefined ? t('questions.notAnswered') : emptyLabel;
          return (
            <Card
              key={question.id}
              variant="subtle"
              padding="sm"
              className="gap-1"
              data-question={question.id}
            >
              {title}
              {parts.length > 0 ? (
                <p className="text-sm wrap-break-word whitespace-pre-wrap">
                  {parts.join(', ')}
                </p>
              ) : (
                empty && (
                  <p className="text-muted-foreground text-sm">{empty}</p>
                )
              )}
            </Card>
          );
        }

        const note = question.note && (
          <p className="text-muted-foreground flex items-start gap-1.5 text-xs">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            {question.note}
          </p>
        );
        const textField = (
          value: string,
          label: string,
          placeholder: string,
          autoFocus: boolean,
          onChange: (value: string) => void = (next) =>
            update(question.id, { ...answer, other: next }),
        ) => (
          <Input
            size="sm"
            autoFocus={autoFocus}
            value={value}
            aria-label={label}
            placeholder={placeholder}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              // Not the Enter that picks an IME candidate (Japanese, Chinese).
              if (
                event.key === 'Enter' &&
                !event.nativeEvent.isComposing &&
                message
              ) {
                event.preventDefault();
                submit();
              }
            }}
          />
        );

        // No options: the answer is only the user's to type (a name, a
        // contact), so the card is the question and one field.
        if (question.options.length === 0) {
          return (
            <Card
              key={question.id}
              variant="subtle"
              padding="sm"
              className="gap-2"
              data-question={question.id}
            >
              {title}
              {textField(
                answer.other ?? '',
                question.text,
                question.placeholder || t('questions.somethingElsePlaceholder'),
                index === 0,
              )}
              {note}
            </Card>
          );
        }

        // The options, "Something else" (id null), then the exclusive ones
        // after a rule. Rows go by the option's position (the radio values
        // too), "other" for Something else.
        type Row = { key: string; id: string | null; option?: QuestionOption };
        const toRow = (option: QuestionOption): Row => ({
          key: String(question.options.indexOf(option)),
          id: option.id,
          option,
        });
        const rows: Row[] = [
          ...question.options.filter((option) => !option.exclusive).map(toRow),
          { key: 'other', id: null },
        ];
        const lastRows = question.options
          .filter((option) => option.exclusive)
          .map(toRow);
        const isOn = (row: Row) =>
          row.id === null
            ? answer.other !== null
            : answer.picked.includes(row.id);

        // A picked row's field, in line with the row labels (the 16px control
        // and its gap-3): Something else's free text, or an option's value.
        const fieldOf = (row: Row) => {
          if (!isOn(row)) return null;
          if (row.id === null)
            return textField(
              answer.other ?? '',
              t('questions.somethingElseLabel'),
              t('questions.somethingElsePlaceholder'),
              true,
            );
          const { option } = row;
          if (!option?.input) return null;
          return textField(
            answer.values?.[option.id] ?? '',
            option.label,
            option.input,
            true,
            (value) => setValue(question, option.id, value),
          );
        };
        const renderRow = (row: Row) => {
          const label = row.option?.label ?? t('questions.somethingElse');
          const control = question.multi ? (
            <Checkbox
              id={rowId(row.key)}
              className="mt-0.5"
              checked={isOn(row)}
              onCheckedChange={(checked) =>
                toggle(question, row.id, checked === true)
              }
            />
          ) : (
            <RadioGroupItem
              id={rowId(row.key)}
              value={row.key}
              className="mt-0.5"
            />
          );
          const field = fieldOf(row);
          return (
            <Fragment key={row.key}>
              <div className="flex items-start gap-3">
                {control}
                {/* An answer reads as a sentence, not a field name: normal
                    weight, and normal leading for a label that wraps
                    (DESIGN.md › Approved exceptions). */}
                <Label
                  htmlFor={rowId(row.key)}
                  className="leading-normal font-normal wrap-break-word"
                >
                  {label}
                </Label>
              </div>
              {field && <div className="pl-7">{field}</div>}
            </Fragment>
          );
        };
        const options = (
          <>
            {rows.map(renderRow)}
            {lastRows.length > 0 && <Separator />}
            {lastRows.map(renderRow)}
          </>
        );
        const pickedRow = [...rows, ...lastRows].find(
          (row) => row.id !== null && answer.picked[0] === row.id,
        );

        return (
          <Card
            key={question.id}
            variant="subtle"
            padding="sm"
            className="gap-2"
            data-question={question.id}
          >
            {title}
            {question.multi ? (
              <div
                role="group"
                aria-label={question.text}
                className="grid gap-3"
              >
                {options}
              </div>
            ) : (
              <RadioGroup
                aria-label={question.text}
                value={answer.other !== null ? 'other' : (pickedRow?.key ?? '')}
                onValueChange={(value) =>
                  pickOne(
                    question,
                    value === 'other'
                      ? null
                      : (question.options[Number(value)]?.id ?? null),
                  )
                }
              >
                {options}
              </RadioGroup>
            )}
            {note}
          </Card>
        );
      })}
      {active && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            shape="pill"
            disabled={!message}
            onClick={submit}
          >
            {t('questions.sendAnswers')}
          </Button>
          {onSkip && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              shape="pill"
              onClick={onSkip}
            >
              {skipLabel}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
