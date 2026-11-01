import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

import type { DrafterErrorCode } from './drafterApi';
import { RETRYABLE } from './DraftPanel';

/**
 * A drafter turn's error outside the DraftPanel (inline, as the Insights
 * topic suggestions show one), drawn as the panel draws it: a destructive
 * Alert with the code's title and description, and Try again for the errors
 * a second try can fix.
 *
 * Args:
 *   code: The error event's code.
 *   onRetry: Runs the turn again; left out where it can't (an older error).
 *   description: The recipe's own text in place of the code's description,
 *     which speaks of the agent form ("Nothing in the form changed").
 */
export function DrafterErrorAlert({
  code,
  onRetry,
  description,
}: {
  code: DrafterErrorCode;
  onRetry?: () => void;
  description?: string;
}) {
  const { t } = useTranslation();
  return (
    <Alert variant="destructive" data-item="error">
      <AlertTitle>{t(`drafter.errors.${code}.title`)}</AlertTitle>
      <AlertDescription>
        <p>{description ?? t(`drafter.errors.${code}.description`)}</p>
        {onRetry && RETRYABLE.includes(code) && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            shape="pill"
            className="mt-2"
            onClick={onRetry}
          >
            {t('drafter.retry')}
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}
