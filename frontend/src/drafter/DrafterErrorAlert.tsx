import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

import type { DrafterErrorCode } from './drafterApi';

// Errors a second try can fix; the others need a setting changed first.
export const RETRYABLE: DrafterErrorCode[] = [
  'rate_limited',
  'invalid_output',
  'model_error',
];

/**
 * A drafter turn's error: a destructive Alert with the code's title and
 * description, and Try again for the errors a second try can fix, a link in
 * the Alert's colour at the end of the text. The DraftPanel draws its errors
 * with it, and a screen shows one inline (the Insights topic suggestions).
 *
 * Args:
 *   code: The error event's code.
 *   onRetry: Runs the turn again; left out where it can't (an older error).
 *   description: The recipe's own text in place of the code's description,
 *     which speaks of the agent form ("Nothing in the form changed").
 *   fix: Another link that fixes the error, after Try again (the panel's
 *     Start over for a refused conversation). A way past the error that
 *     isn't a fix goes under the Alert, not here.
 */
export function DrafterErrorAlert({
  code,
  onRetry,
  description,
  fix,
}: {
  code: DrafterErrorCode;
  onRetry?: () => void;
  description?: string;
  fix?: ReactNode;
}) {
  const { t } = useTranslation();
  const retry = onRetry && RETRYABLE.includes(code);
  return (
    <Alert variant="destructive" data-item="error">
      <AlertTitle>{t(`drafter.errors.${code}.title`)}</AlertTitle>
      <AlertDescription>
        <p>
          {description ?? t(`drafter.errors.${code}.description`)}
          {retry && (
            <>
              {' '}
              <Button
                type="button"
                variant="link"
                size="text"
                tone="current"
                onClick={onRetry}
              >
                {t('drafter.retry')}
              </Button>
            </>
          )}
          {fix && <> {fix}</>}
        </p>
      </AlertDescription>
    </Alert>
  );
}
