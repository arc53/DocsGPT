import { Info } from 'lucide-react';
import { type ReactNode, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';

import type { DrafterQuestion } from './drafterApi';

type Answer = { picked: string[]; other: string | null };

const NO_ANSWER: Answer = { picked: [], other: null };

/** A question's answer as text: the picked labels, then the free text. */
function answerParts(question: DrafterQuestion, answer: Answer): string[] {
  const parts = question.options
    .filter((option) => answer.picked.includes(option.id))
    .map((option) => option.label);
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
  questions: DrafterQuestion[],
  answers: Record<string, Answer>,
): string {
  return questions
    .map((question) => {
      const answer = answers[question.id];
      if (!answer) return null;
      const parts = answerParts(question, answer);
      return parts.length > 0 ? `${question.text} → ${parts.join(', ')}` : null;
    })
    .filter((line): line is string => line !== null)
    .join('\n');
}

/**
 * The drafter's questions as cards of option rows: radios for a one-pick
 * question, checkboxes for a pick-any one (`multi`), and "Something else…"
 * last, which opens a free-text field under it. A question with no options
 * is a text field alone. One Send answers button sends
 * every answer as one message. An answered (or passed-over) card shows only
 * the question and what was picked.
 *
 * Args:
 *   questions: At most three questions, two to five options each (or none).
 *   active: Whether they can still be answered.
 *   onAnswer: Sends the composed answers.
 *   onSkip: When given, a Skip button beside Send answers drafts without
 *     answering.
 */
export function DrafterQuestions({
  questions,
  active,
  onAnswer,
  onSkip,
}: {
  questions: DrafterQuestion[];
  active: boolean;
  onAnswer: (message: string) => void;
  onSkip?: () => void;
}) {
  const { t } = useTranslation();
  const baseId = useId();
  const [answers, setAnswers] = useState<Record<string, Answer>>({});

  const answerOf = (id: string): Answer => answers[id] ?? NO_ANSWER;
  const update = (id: string, next: Answer) =>
    setAnswers((prev) => ({ ...prev, [id]: next }));

  // One pick: an option replaces the other choice and closes "Something
  // else"; `optionId` null is "Something else" itself.
  const pickOne = (question: DrafterQuestion, optionId: string | null) =>
    update(
      question.id,
      optionId === null
        ? { picked: [], other: answerOf(question.id).other ?? '' }
        : { picked: [optionId], other: null },
    );

  const toggle = (question: DrafterQuestion, optionId: string, on: boolean) => {
    const answer = answerOf(question.id);
    update(question.id, {
      ...answer,
      picked: on
        ? [...answer.picked, optionId]
        : answer.picked.filter((id) => id !== optionId),
    });
  };

  const message = composeAnswers(questions, answers);

  return (
    <div className="flex flex-col gap-3" data-slot="drafter-questions">
      {questions.map((question, index) => {
        const answer = answerOf(question.id);
        // Rows go by position (the radio values too): the option ids are
        // the model's own and could be anything.
        const rowId = (row: number) => `${baseId}-${question.id}-${row}`;
        const title = (
          <p className="text-sm font-medium wrap-break-word">
            {questions.length > 1 ? `${index + 1}. ` : ''}
            {question.text}
          </p>
        );

        if (!active) {
          const parts = answerParts(question, answer);
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
                <p className="text-sm wrap-break-word">{parts.join(', ')}</p>
              ) : (
                <p className="text-muted-foreground text-sm">
                  {t('drafter.notAnswered')}
                </p>
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
        ) => (
          <Input
            size="sm"
            autoFocus={autoFocus}
            value={value}
            aria-label={label}
            placeholder={placeholder}
            onChange={(event) =>
              update(question.id, { ...answer, other: event.target.value })
            }
            onKeyDown={(event) => {
              if (event.key === 'Enter' && message) {
                event.preventDefault();
                onAnswer(message);
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
                question.placeholder || t('drafter.somethingElsePlaceholder'),
                index === 0,
              )}
              {note}
            </Card>
          );
        }

        // Each option, then "Something else" (id null) last.
        const rows = [
          ...question.options.map(({ id, label }) => ({ id, label })),
          { id: null, label: t('drafter.somethingElse') },
        ];
        const otherRow = question.options.length;
        const row = (index: number, label: string, control: ReactNode) => (
          <div key={index} className="flex items-start gap-3">
            {control}
            <Label
              htmlFor={rowId(index)}
              className="leading-normal font-normal wrap-break-word"
            >
              {label}
            </Label>
          </div>
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
                {rows.map(({ id, label }, rowIndex) =>
                  row(
                    rowIndex,
                    label,
                    <Checkbox
                      id={rowId(rowIndex)}
                      className="mt-0.5"
                      checked={
                        id === null
                          ? answer.other !== null
                          : answer.picked.includes(id)
                      }
                      onCheckedChange={(checked) =>
                        id === null
                          ? update(question.id, {
                              ...answer,
                              other: checked === true ? '' : null,
                            })
                          : toggle(question, id, checked === true)
                      }
                    />,
                  ),
                )}
              </div>
            ) : (
              <RadioGroup
                aria-label={question.text}
                value={
                  answer.other !== null
                    ? String(otherRow)
                    : answer.picked.length > 0
                      ? String(
                          question.options.findIndex(
                            (option) => option.id === answer.picked[0],
                          ),
                        )
                      : ''
                }
                onValueChange={(value) =>
                  pickOne(question, rows[Number(value)].id)
                }
              >
                {rows.map(({ label }, rowIndex) =>
                  row(
                    rowIndex,
                    label,
                    <RadioGroupItem
                      id={rowId(rowIndex)}
                      value={String(rowIndex)}
                      className="mt-0.5"
                    />,
                  ),
                )}
              </RadioGroup>
            )}
            {answer.other !== null && (
              // In line with the row labels: the 16px control and its gap-3.
              <div className="pl-7">
                {textField(
                  answer.other,
                  t('drafter.somethingElseLabel'),
                  t('drafter.somethingElsePlaceholder'),
                  true,
                )}
              </div>
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
            onClick={() => onAnswer(message)}
          >
            {t('drafter.sendAnswers')}
          </Button>
          {onSkip && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              shape="pill"
              onClick={onSkip}
            >
              {t('drafter.skipQuestions')}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
