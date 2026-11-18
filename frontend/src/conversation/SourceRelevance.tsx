import { useTranslation } from 'react-i18next';

import { cn } from '../lib/utils';
import { relevanceBand } from './chatCompanion';

/**
 * A source's relevance as a small muted label ("Strong match"), with the
 * percentage in its tooltip. Renders nothing for a source without a score, so
 * answers from before relevance scoring, or with it off, look as they did.
 */
export default function SourceRelevance({
  relevance,
  className,
}: {
  relevance?: number | null;
  className?: string;
}) {
  const { t } = useTranslation();
  const band = relevanceBand(relevance);
  if (band === null) return null;
  return (
    <span
      className={cn('text-muted-foreground text-xs', className)}
      title={t('conversation.sources.relevance.tooltip', {
        percent: Math.round((relevance as number) * 100),
      })}
    >
      {t(`conversation.sources.relevance.${band}`)}
    </span>
  );
}
