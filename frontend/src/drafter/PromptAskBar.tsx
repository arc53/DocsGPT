import { Square, WandSparkles } from 'lucide-react';
import { type Ref, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Spinner } from '@/components/ui/spinner';

import { RETRYABLE } from './DraftPanel';
import type { PromptDraftResult } from './usePromptDrafter';
import type { DrafterSession } from './useDrafterSession';
import { WandButton } from './WandButton';

/**
 * The prompt modal's ask bar: one request, then Improve (a prompt with text)
 * or Write (an empty one). Each request starts a fresh turn on the prompt as
 * it is now. Under it, compactly: the running step with Stop, an error with
 * Try again, a plain reply, and the latest result's message and warnings.
 *
 * Args:
 *   session: The prompt drafter's session.
 *   mode: `improve` or `write` (the button's label and the placeholder).
 *   result: The latest result's message and warnings, or null.
 *   inputRef: The request field, for "Improve a copy" to focus.
 *   reviewing: An improvement is under review: the request field is hidden
 *     until it closes, and the result's message and warnings stay.
 */
export function PromptAskBar({
  session,
  mode,
  result,
  inputRef,
  reviewing = false,
}: {
  session: DrafterSession;
  mode: 'improve' | 'write';
  result: PromptDraftResult | null;
  inputRef?: Ref<HTMLInputElement>;
  reviewing?: boolean;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const { items, step, streaming } = session;

  const send = () => {
    if (streaming || reviewing || !text.trim()) return;
    // A prompt request is one turn on the text as it is now.
    session.reset();
    session.send(text);
    setText('');
  };

  const error = items.findLast((item) => item.kind === 'error');
  const reply = items.findLast((item) => item.kind === 'message');
  const warnings = result
    ? [
        ...result.checks.map((code) => t(`drafter.prompt.checks.${code}`)),
        ...result.warnings,
      ]
    : [];

  return (
    <div data-slot="prompt-ask-bar" className="flex flex-col gap-3">
      {!reviewing && (
        <form
          className="flex flex-col gap-2 sm:flex-row sm:items-center"
          onSubmit={(event) => {
            event.preventDefault();
            send();
          }}
        >
          <div className="min-w-0 flex-1">
            <Input
              ref={inputRef}
              shape="pill"
              leftIcon={
                <WandSparkles className="text-link size-4" aria-hidden="true" />
              }
              value={text}
              readOnly={streaming}
              aria-label={t('drafter.prompt.askLabel')}
              placeholder={
                mode === 'write'
                  ? t('drafter.prompt.writePlaceholder')
                  : t('drafter.prompt.improvePlaceholder')
              }
              onChange={(event) => setText(event.target.value)}
            />
          </div>
          {streaming ? (
            <Button
              type="button"
              variant="outline"
              size="field"
              shape="pill"
              onClick={session.stop}
            >
              <Square />
              {t('drafter.stop')}
            </Button>
          ) : (
            <WandButton mode={mode} onClick={send} disabled={!text.trim()} />
          )}
        </form>
      )}
      <div aria-live="polite" className="contents">
        {step && (
          <p
            className="text-muted-foreground flex items-center gap-2 text-sm"
            data-slot="drafter-step"
          >
            <Spinner size="xs" label={t(`drafter.steps.${step}`)} />
            {t(`drafter.steps.${step}`)}
          </p>
        )}
        {!step && error?.kind === 'error' && (
          <Alert variant="destructive" data-item="error">
            <AlertTitle>{t(`drafter.errors.${error.code}.title`)}</AlertTitle>
            <AlertDescription>
              <p>
                {error.code === 'invalid_output' || error.code === 'model_error'
                  ? t(`drafter.prompt.errors.${error.code}`)
                  : t(`drafter.errors.${error.code}.description`)}
              </p>
              {RETRYABLE.includes(error.code) && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  shape="pill"
                  className="mt-2"
                  onClick={session.retry}
                >
                  {t('drafter.retry')}
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}
        {!step && !error && reply?.kind === 'message' && !result && (
          <p className="text-sm wrap-break-word whitespace-pre-wrap">
            {reply.text}
          </p>
        )}
        {result && (result.message || result.reason) && (
          <p
            className="text-muted-foreground text-sm wrap-break-word"
            data-slot="prompt-draft-message"
          >
            {[result.message, result.reason].filter(Boolean).join(' ')}
          </p>
        )}
        {warnings.length > 0 && (
          <Alert variant="warning" data-slot="prompt-draft-warnings">
            <AlertTitle>{t('drafter.prompt.warningsTitle')}</AlertTitle>
            <AlertDescription>
              <ul className="flex list-disc flex-col gap-1 pl-4">
                {warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
      </div>
    </div>
  );
}
