import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleTrigger } from '@/components/ui/collapsible';

import { promptCheckText } from './promptCheckText';
import { usePromptChecks } from './usePromptChecks';

type PromptChecksHintProps = {
  content: string;
  /** False on a text no one can change here: no checks, no hint. */
  enabled: boolean;
  /**
   * Opens the drafter's drawer and sends Review it. The host gives it only
   * while the drafter is on; without it there is no review link.
   */
  onReview?: () => void;
};

/**
 * The prompt field's hint: the no-model checks as an inline
 * toggle, "2 things to check", closed by default and absent when there are
 * none, opening a muted list worded per check (with its line), then "Review
 * the whole prompt with DocsGPT" when the host can send a review. A
 * template that won't parse is left out: the field's own error says so.
 * It's a hint, so Save never waits on it.
 */
export function PromptChecksHint({
  content,
  enabled,
  onReview,
}: PromptChecksHintProps) {
  const { t } = useTranslation();
  const id = useId();
  const [open, setOpen] = useState(false);
  const checks = usePromptChecks(content, enabled);
  const lines = checks.flatMap((check, index) => {
    if (check.code === 'template_invalid') return [];
    const text = promptCheckText(t, check);
    return text ? [{ key: `${check.code}-${index}`, text }] : [];
  });
  if (lines.length === 0) return null;

  return (
    <div data-slot="prompt-checks">
      <CollapsibleTrigger open={open} onOpenChange={setOpen} controls={id}>
        {t('prompts.checksHint.count', { count: lines.length })}
      </CollapsibleTrigger>
      <Collapsible id={id} open={open}>
        <div className="text-muted-foreground flex flex-col gap-1 pt-1 pl-6 text-xs">
          <ul className="flex list-disc flex-col gap-1 pl-4">
            {lines.map((line) => (
              <li key={line.key} className="wrap-break-word">
                {line.text}
              </li>
            ))}
          </ul>
          {onReview && (
            <p className="pt-0.5">
              <Button
                type="button"
                variant="link"
                size="text"
                onClick={onReview}
              >
                {t('prompts.checksHint.review')}
              </Button>
            </p>
          )}
        </div>
      </Collapsible>
    </div>
  );
}
