import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';

import { Badge } from '../ui/badge';
import type { FoldedGraphTypes } from '../graphViewUtils';
import { seriesDotClass } from './graphCanvasUtils';

/** The 8px colour dot of a type's fold series (Other is muted). */
export function GraphTypeDot({
  fold,
  type,
  className,
}: {
  fold: FoldedGraphTypes;
  type: string | null | undefined;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-block size-2 shrink-0 rounded-full',
        seriesDotClass(fold.seriesOf(type)),
        className,
      )}
    />
  );
}

/** The dot for a fold series index (null for Other), for the legend. */
export function GraphSeriesDot({ series }: { series: number | null }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-block size-2 shrink-0 rounded-full',
        seriesDotClass(series),
      )}
    />
  );
}

/** The display label of a type: its folded spelling, or "Untyped". */
export function useGraphTypeLabel(fold: FoldedGraphTypes) {
  const { t } = useTranslation();
  return (type: string | null | undefined) =>
    fold.labelOf(type) || t('settings.sources.graphrag.view.untyped');
}

/** A neutral Badge with the type's dot and folded label. */
export function GraphTypeBadge({
  fold,
  type,
}: {
  fold: FoldedGraphTypes;
  type: string | null | undefined;
}) {
  const labelOf = useGraphTypeLabel(fold);
  return (
    <Badge variant="neutral" className="max-w-full min-w-0">
      <GraphTypeDot fold={fold} type={type} />
      <span className="truncate">{labelOf(type)}</span>
    </Badge>
  );
}
