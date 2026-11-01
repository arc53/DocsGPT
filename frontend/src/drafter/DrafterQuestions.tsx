import { Check, Info, Pencil } from 'lucide-react';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ToggleChip } from '@/components/ui/toggle-chip';

import type { DrafterQuestion } from './drafterApi';

type Answer = { picked: string[]; other: string | null };

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
      const parts = question.options
        .filter((option) => answer.picked.includes(option.id))
        .map((option) => option.label);
      const other = answer.other?.trim();
      if (other) parts.push(other);
      return parts.length > 0 ? `${question.text} → ${parts.join(', ')}` : null;
    })
    .filter((line): line is string => line !== null)
    .join('\n');
}

/**
 * The drafter's questions as cards: each option a chip (one pick, or several
 * when `multi`), plus "Something else…" with a free-text field, then one
 * Send answers button that sends every answer as one message. Answered (or
 * passed-over) questions show read-only.
 *
 * Args:
 *   questions: At most three questions, two to five options each.
 *   active: Whether they can still be answered.
 *   onAnswer: Sends the composed answers.
 */
export function DrafterQuestions({
  questions,
  active,
  onAnswer,
}: {
  questions: DrafterQuestion[];
  active: boolean;
  onAnswer: (message: string) => void;
}) {
  const { t } = useTranslation();
  const baseId = useId();
  const [answers, setAnswers] = useState<Record<string, Answer>>({});

  const answerOf = (id: string): Answer =>
    answers[id] ?? { picked: [], other: null };
  const update = (id: string, next: Answer) =>
    setAnswers((prev) => ({ ...prev, [id]: next }));

  const toggle = (question: DrafterQuestion, optionId: string) => {
    const answer = answerOf(question.id);
    const on = answer.picked.includes(optionId);
    if (question.multi) {
      update(question.id, {
        ...answer,
        picked: on
          ? answer.picked.filter((id) => id !== optionId)
          : [...answer.picked, optionId],
      });
    } else {
      // One pick: a chip replaces the other choice and closes "Something else".
      update(question.id, { picked: on ? [] : [optionId], other: null });
    }
  };

  const toggleOther = (question: DrafterQuestion) => {
    const answer = answerOf(question.id);
    if (answer.other !== null) update(question.id, { ...answer, other: null });
    else
      update(question.id, {
        picked: question.multi ? answer.picked : [],
        other: '',
      });
  };

  const message = composeAnswers(questions, answers);

  return (
    <div className="flex flex-col gap-3" data-slot="drafter-questions">
      {questions.map((question, index) => {
        const answer = answerOf(question.id);
        const otherId = `${baseId}-${question.id}-other`;
        return (
          <Card
            key={question.id}
            variant="subtle"
            padding="sm"
            className="gap-2"
            data-question={question.id}
          >
            <p className="text-sm font-medium">
              {questions.length > 1 ? `${index + 1}. ` : ''}
              {question.text}
            </p>
            <div
              role="group"
              aria-label={question.text}
              className="flex flex-wrap gap-1.5"
            >
              {question.options.map((option) => {
                const on = answer.picked.includes(option.id);
                return (
                  <ToggleChip
                    key={option.id}
                    size="sm"
                    pressed={on}
                    disabled={!active}
                    onPressedChange={() => toggle(question, option.id)}
                    // A long option wraps inside the pill instead of
                    // running past the panel.
                    className="h-auto min-h-8 max-w-full"
                  >
                    {on && question.multi ? <Check /> : null}
                    <span className="min-w-0 py-1 text-left whitespace-normal">
                      {option.label}
                    </span>
                  </ToggleChip>
                );
              })}
              <ToggleChip
                size="sm"
                pressed={answer.other !== null}
                disabled={!active}
                onPressedChange={() => toggleOther(question)}
              >
                <Pencil />
                {t('drafter.somethingElse')}
              </ToggleChip>
            </div>
            {answer.other !== null && active && (
              <Input
                id={otherId}
                size="sm"
                autoFocus
                value={answer.other}
                aria-label={t('drafter.somethingElseLabel')}
                placeholder={t('drafter.somethingElsePlaceholder')}
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
            )}
            {question.note && (
              <p className="text-muted-foreground flex items-start gap-1.5 text-xs">
                <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                {question.note}
              </p>
            )}
          </Card>
        );
      })}
      {active && (
        <Button
          type="button"
          size="sm"
          shape="pill"
          className="self-start"
          disabled={!message}
          onClick={() => onAnswer(message)}
        >
          {t('drafter.sendAnswers')}
        </Button>
      )}
    </div>
  );
}
