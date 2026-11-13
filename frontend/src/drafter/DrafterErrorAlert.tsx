import type { MouseEvent, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from '@/components/ui/alert';

import { DRAFTER_PROMPT_CHARS, type DrafterErrorCode } from './drafterApi';

/** Where the task model is picked: Settings › General. */
export const TASK_MODEL_SETTINGS_PATH = '/settings/general';

// Errors a second try can fix; the others need a setting changed first.
export const RETRYABLE: DrafterErrorCode[] = [
  'rate_limited',
  'invalid_output',
  'model_error',
];

/**
 * A drafter turn's error: a destructive Alert with the code's title and
 * description, and Try again for the errors a second try can fix, a link in
 * the Alert's colour at the end of the text. A task model whose key was
 * refused (`model_auth`) names the model and links to changing it instead.
 * The DraftPanel draws its errors with it, and a screen shows one inline (the
 * Insights topic suggestions).
 *
 * Args:
 *   code: The error event's code.
 *   onRetry: Runs the turn again; left out where it can't (an older error).
 *   description: The recipe's own text in place of the code's description,
 *     which speaks of the agent form ("Nothing in the form changed").
 *   model: The task model's name, for a refused key's description.
 *   limit: A too-long prompt's limit in characters, when the refusal named
 *     it; else the server's usual one.
 *   onNavigate: The Change the task model link's click handler (a builder's
 *     leave guard).
 *   fix: Another link that fixes the error, after Try again (the panel's
 *     Start over for a refused conversation). A way past the error that
 *     isn't a fix goes under the Alert, not here.
 */
export function DrafterErrorAlert({
  code,
  onRetry,
  description,
  fix,
  model,
  limit,
  onNavigate,
}: {
  code: DrafterErrorCode;
  onRetry?: () => void;
  description?: string;
  fix?: ReactNode;
  model?: string | null;
  limit?: number;
  onNavigate?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  const { t } = useTranslation();
  const retry = onRetry && RETRYABLE.includes(code);
  const refusedKey = code === 'model_auth';
  const text =
    description ??
    (refusedKey
      ? model
        ? t('drafter.errors.model_auth.description', {
            model,
            interpolation: { escapeValue: false },
          })
        : t('drafter.errors.model_auth.descriptionNoModel')
      : code === 'prompt_too_long'
        ? t('drafter.errors.prompt_too_long.description', {
            limit: limit ?? DRAFTER_PROMPT_CHARS,
          })
        : t(`drafter.errors.${code}.description`));
  return (
    <Alert variant="destructive" data-item="error">
      <AlertTitle>{t(`drafter.errors.${code}.title`)}</AlertTitle>
      <AlertDescription>
        <p>
          {text}
          {retry && (
            <>
              {' '}
              <AlertAction onClick={onRetry}>{t('drafter.retry')}</AlertAction>
            </>
          )}
          {refusedKey && (
            <>
              {' '}
              <AlertAction asChild>
                <Link to={TASK_MODEL_SETTINGS_PATH} onClick={onNavigate}>
                  {t('drafter.errors.model_auth.fix')}
                </Link>
              </AlertAction>
            </>
          )}
          {fix && <> {fix}</>}
        </p>
      </AlertDescription>
    </Alert>
  );
}
