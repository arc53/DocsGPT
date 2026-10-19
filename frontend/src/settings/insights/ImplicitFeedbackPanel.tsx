import { useId } from 'react';
import { useTranslation } from 'react-i18next';

import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionHeader } from '@/components/ui/section-header';

import { useChartPalette } from '../../utils/chartUtils';
import { formatCount, formatDate } from '../../utils/dateTimeUtils';
import AnalyticsChart from '../AnalyticsChart';
import type { ConversationInsights, InsightOption } from '../types';
import {
  formatEstimate,
  MIN_SAMPLE,
  rangePoints,
  REACTION_SERIES,
} from './format';
import TierBadge from './TierBadge';

/**
 * How users' next messages responded to answers, beside the thumbs: thanks,
 * asking again, and pushback or complaint, in the same green, amber and red
 * as the thumbs so the two read together. Neutral reactions (a new question,
 * a follow-up) are not drawn.
 */
export default function ImplicitFeedbackPanel({
  data,
}: {
  data: ConversationInsights;
}) {
  const { t } = useTranslation();
  const palette = useChartPalette();
  const legendId = useId();
  const reaction = data.totals.reaction;
  const enough = (reaction?.n ?? 0) >= MIN_SAMPLE;

  const colors = {
    thanks: palette.success,
    reAsk: palette.warning,
    pushbackOrComplaint: palette.destructive,
  };
  const series = Object.entries(REACTION_SERIES) as [
    keyof typeof REACTION_SERIES,
    readonly string[],
  ][];
  const datasets = series.map(([key, options]) => ({
    label: t(`settings.analytics.insights.options.reaction.${key}`),
    data: data.series.map((bucket) =>
      options.reduce(
        (sum, option) => sum + (bucket.labels.reaction?.options[option] ?? 0),
        0,
      ),
    ),
    backgroundColor: colors[key],
  }));
  const points = rangePoints(
    series
      .flatMap(([, options]) => options)
      .map((option) => reaction?.options[option])
      .filter((option): option is InsightOption => option !== undefined),
  );

  return (
    <Card
      variant="subtle"
      padding="lg"
      className="h-[345px] w-full overflow-hidden xl:w-1/2"
      data-testid="implicit-feedback"
    >
      <div className="flex flex-wrap items-center gap-2">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('settings.analytics.insights.panels.implicitFeedback')}
        />
        <TierBadge tier="estimated" points={enough ? points : undefined} />
      </div>
      <div className="relative h-[245px] w-full">
        {enough ? (
          <>
            <div
              id={legendId}
              className="flex flex-row items-center justify-end"
            ></div>
            <AnalyticsChart
              data={{
                labels: data.series.map((bucket) => formatDate(bucket.bucket)),
                datasets,
              }}
              legendID={legendId}
              maxTicksLimitInX={8}
              gridColor={palette.border}
              tickColor={palette.mutedForeground}
              isStacked
              tooltipCallbacks={{
                label: (item) =>
                  t('settings.analytics.insights.panels.tooltipCount', {
                    name: item.dataset.label,
                    value: formatEstimate(Number(item.raw)),
                    interpolation: { escapeValue: false },
                  }),
                footer: (items) => {
                  const n =
                    data.series[items[0]?.dataIndex ?? -1]?.labels.reaction
                      ?.n ?? 0;
                  return t('settings.analytics.insights.panels.ofReplies', {
                    count: n,
                    formatted: formatCount(n),
                  });
                },
              }}
            />
          </>
        ) : (
          <EmptyState
            size="xs"
            illustration="none"
            title={t('settings.analytics.insights.notEnoughReplies')}
          />
        )}
      </div>
    </Card>
  );
}
