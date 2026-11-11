import { useId, type ReactNode } from 'react';

import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionHeader } from '@/components/ui/section-header';
import { cn } from '@/lib/utils';

import SkeletonLoader from '../../components/SkeletonLoader';

type ChartPanelProps = {
  title: string;
  /**
   * Controls after the title, in its row (a group-by select, a switch); one
   * pushed to the end takes `ml-auto`.
   */
  actions?: ReactNode;
  /** In flow under the title row: the panel's headline figure. */
  summary?: ReactNode;
  /** The chart, given the id of the legend container it draws into. */
  chart?: (legendId: string) => ReactNode;
  /**
   * In flow, in place of a chart: a body that sizes itself, such as share
   * bars when there is too little to draw over time.
   */
  children?: ReactNode;
  /** A skeleton in place of the chart while its data loads; the title stays. */
  loading?: boolean;
  /** The fetch failed: what to say, with Retry, in place of the chart. */
  error?: string;
  onRetry?: () => void;
  /** Drawn instead of the chart: why there is no figure yet. */
  empty?: string;
  /** Layout only: the panel's share of its row. */
  className?: string;
  'data-testid'?: string;
};

/**
 * One chart panel on Analytics and Insights. The panel fills its grid row,
 * whose height the panel beside it may set; the chart is positioned out of
 * flow, so it fills that height without driving it (a canvas in flow grows
 * its own row). The panels sit straight under the page's h1, so the title
 * is an h2.
 */
export default function ChartPanel({
  title,
  actions,
  summary,
  chart,
  children,
  loading = false,
  error,
  onRetry,
  empty,
  className,
  'data-testid': testId,
}: ChartPanelProps) {
  const legendId = useId();
  const heading = <SectionHeader as="h2" size="xs" title={title} />;
  let body: ReactNode;
  // Out of flow like the chart, so its bars stand on the panel's floor.
  if (loading)
    body = (
      <div className="absolute inset-0">
        <SkeletonLoader count={1} component="analysis" />
      </div>
    );
  else if (error)
    body = (
      <EmptyState
        tone="destructive"
        size="sm"
        illustration="none"
        title={error}
        onRetry={onRetry}
      />
    );
  else if (empty)
    body = <EmptyState size="sm" illustration="none" title={empty} />;
  else if (children)
    body = <div className="flex flex-col gap-3">{children}</div>;
  else
    body = (
      <div className="absolute inset-0 flex flex-col">
        <div
          id={legendId}
          className="flex flex-row flex-wrap items-center justify-end"
        ></div>
        <div className="relative min-h-0 flex-1">{chart?.(legendId)}</div>
      </div>
    );
  return (
    <Card
      variant="subtle"
      padding="lg"
      className={cn('h-full min-h-[345px] w-full overflow-hidden', className)}
      data-testid={testId}
    >
      {actions ? (
        <div className="flex flex-row flex-wrap items-center gap-3">
          {heading}
          {actions}
        </div>
      ) : (
        heading
      )}
      {!loading && !error && !empty && summary}
      <div className="relative min-h-[245px] w-full flex-1">{body}</div>
    </Card>
  );
}
