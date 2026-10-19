import { useId, type ReactNode } from 'react';

import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionHeader } from '@/components/ui/section-header';

type ChartPanelProps = {
  title: string;
  /** Beside the title: a tier badge. */
  badge?: ReactNode;
  /** The chart, given the id of the legend container it draws into. */
  chart: (legendId: string) => ReactNode;
  /** Drawn instead of the chart: why there is no figure yet. */
  empty?: string;
  'data-testid'?: string;
};

/**
 * One chart in the insights grid. The panel fills its grid row, whose height
 * the panel beside it may set; the chart is positioned out of flow, so it
 * fills that height without driving it (a canvas in flow grows its own row).
 */
export default function ChartPanel({
  title,
  badge,
  chart,
  empty,
  'data-testid': testId,
}: ChartPanelProps) {
  const legendId = useId();
  return (
    <Card
      variant="subtle"
      padding="lg"
      className="h-full min-h-[345px] w-full overflow-hidden"
      data-testid={testId}
    >
      <div className="flex flex-wrap items-center gap-2">
        <SectionHeader as="h3" size="xs" title={title} />
        {badge}
      </div>
      <div className="relative min-h-[245px] w-full flex-1">
        {empty ? (
          <EmptyState size="xs" illustration="none" title={empty} />
        ) : (
          <div className="absolute inset-0 flex flex-col">
            <div
              id={legendId}
              className="flex flex-row flex-wrap items-center justify-end"
            ></div>
            <div className="relative min-h-0 flex-1">{chart(legendId)}</div>
          </div>
        )}
      </div>
    </Card>
  );
}
