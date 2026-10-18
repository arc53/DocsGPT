import { useTranslation } from 'react-i18next';

import { Badge } from '../components/ui/badge';
import type { ActionInjection } from './types';

/** The score from which a tool description is flagged, as the server flags it. */
export const INJECTION_FLAG_THRESHOLD = 0.5;

/** Whether an action's description reads like a prompt injection. */
export function injectionFlagged(action: {
  injection?: ActionInjection;
}): boolean {
  return (action.injection?.p ?? 0) >= INJECTION_FLAG_THRESHOLD;
}

/**
 * Beside a flagged action's name: its description may carry instructions
 * planted for the AI. Warn only; the action keeps its permission.
 */
export function InjectionFlagBadge() {
  const { t } = useTranslation();
  return (
    <Badge variant="warning" className="shrink-0">
      {t('settings.connectors.injection.flagged')}
    </Badge>
  );
}
