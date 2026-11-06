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
 * description, and Try again for the errors a second try can fix. The
 * DraftPanel draws its errors with it, and a screen shows one inline (the
 * Insights topic suggestions).
 *
 * Args:
 *   code: The error event's code.
 *   onRetry: Runs the turn again; left out where it can't (an older error).
 *   description: The recipe's own text in place of the code's description,
 *     which speaks of the agent form ("Nothing in the form changed").
 *   actions: More buttons after Try again (the panel's way on, Start over).
 */
export function DrafterErrorAlert({
  code,
  onRetry,
  description,
  actions,
}: {
  code: DrafterErrorCode;
  onRetry?: () => void;
  description?: string;
  actions?: ReactNode;
}) {
  const { t } = useTranslation();
  const retry = onRetry && RETRYABLE.includes(code);
  return (
    <Alert variant="destructive" data-item="error">
      <AlertTitle>{t(`drafter.errors.${code}.title`)}</AlertTitle>
      <AlertDescription>
        <p>{description ?? t(`drafter.errors.${code}.description`)}</p>
        {(retry || actions) && (
          <div className="mt-2 flex flex-wrap gap-2">
            {retry && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                shape="pill"
                onClick={onRetry}
              >
                {t('drafter.retry')}
              </Button>
            )}
            {actions}
          </div>
        )}
      </AlertDescription>
    </Alert>
  );
}
