import { useTranslation } from 'react-i18next';

import { useChartPalette } from '../../utils/chartUtils';
import { formatCount, formatDate } from '../../utils/dateTimeUtils';
import AnalyticsChart from '../AnalyticsChart';
import type { ConversationInsights } from '../types';
import { formatEstimate, MIN_SAMPLE, REACTION_SERIES } from './format';
import ChartPanel from './ChartPanel';

/**
 * How users' next messages responded to answers: thanks, asking again, and
 * pushback or complaint, in the same green, amber and red as the thumbs on
 * Analytics so the two read together. Neutral reactions (a new question,
 * a follow-up) are not drawn.
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
          tooltipCallbacks={{
            label: (item) =>
              t('settings.analytics.insights.panels.tooltipCount', {
                name: item.dataset.label,
                value: formatEstimate(Number(item.raw)),
                interpolation: { escapeValue: false },
              }),
            footer: (items) => {
              const n =
                data.series[items[0]?.dataIndex ?? -1]?.labels.reaction?.n ?? 0;
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
