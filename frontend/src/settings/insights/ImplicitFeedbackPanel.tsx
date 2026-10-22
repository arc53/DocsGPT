import { useTranslation } from 'react-i18next';

import { useChartPalette } from '../../utils/chartUtils';
import { formatCount, formatDate } from '../../utils/dateTimeUtils';
import AnalyticsChart from '../AnalyticsChart';
import type { ConversationInsights } from '../types';
import { formatShare, MIN_SAMPLE, REACTION_SERIES, shareOfDay } from './format';
import ChartPanel from './ChartPanel';

/**
 * How users' next messages responded to answers: thanks, asking again, and
 * pushback or complaint, in the same green, amber and red as the thumbs on
 * Analytics so the two read together. Each day is its share of that day's
 * replies; neutral reactions (a new question, a follow-up) are not drawn,
 * so they are the gap above a column.
 */
export default function ImplicitFeedbackPanel({
  data,
}: {
  data: ConversationInsights;
}) {
  const { t } = useTranslation();
  const palette = useChartPalette();
  const enough = (data.totals.reaction?.n ?? 0) >= MIN_SAMPLE;

  const colors = {
    thanks: palette.success,
    reAsk: palette.warning,
    pushbackOrComplaint: palette.destructive,
  };
  const series = Object.entries(REACTION_SERIES) as [
    keyof typeof REACTION_SERIES,
    readonly string[],
  ][];
  const replies = (index: number) =>
    data.series[index]?.labels.reaction?.n ?? 0;
  const datasets = series.map(([key, options]) => ({
    label: t(`settings.analytics.insights.options.reaction.${key}`),
    data: data.series.map((bucket) =>
      shareOfDay(
        options.reduce(
          (sum, option) => sum + (bucket.labels.reaction?.options[option] ?? 0),
          0,
        ),
        bucket.labels.reaction?.n ?? 0,
      ),
    ),
    backgroundColor: colors[key],
  }));

  return (
    <ChartPanel
      title={t('settings.analytics.insights.panels.implicitFeedback')}
      empty={
        enough ? undefined : t('settings.analytics.insights.notEnoughReplies')
      }
      data-testid="implicit-feedback"
      chart={(legendId) => (
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
          share
          tooltipCallbacks={{
            label: (item) =>
              t('settings.analytics.insights.panels.tooltipShare', {
                name: item.dataset.label,
                value: formatShare(Number(item.raw)),
                interpolation: { escapeValue: false },
              }),
            footer: (items) => {
              const n = replies(items[0]?.dataIndex ?? -1);
              return t('settings.analytics.insights.panels.ofReplies', {
                count: n,
                formatted: formatCount(n),
              });
            },
          }}
        />
      )}
    />
  );
}
