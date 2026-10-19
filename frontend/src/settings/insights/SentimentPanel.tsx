import { useTranslation } from 'react-i18next';

import { useChartPalette } from '../../utils/chartUtils';
import { formatCount, formatDate } from '../../utils/dateTimeUtils';
import AnalyticsChart from '../AnalyticsChart';
import type { ConversationInsights } from '../types';
import {
  formatEstimate,
  formatShare,
  MIN_SAMPLE,
  optionName,
  SENTIMENT_SERIES,
} from './format';
import ChartPanel from './ChartPanel';

/**
 * The tone of users' replies over time: positive, neutral and negative.
 * Like frustration, only messages sent after an answer are read, so a
 * conversation's first message never counts.
 */
export default function SentimentPanel({
  data,
}: {
  data: ConversationInsights;
}) {
  const { t } = useTranslation();
  const palette = useChartPalette();
  const enough = (data.totals.sentiment?.n ?? 0) >= MIN_SAMPLE;
  const colors = {
    positive: palette.success,
    neutral: palette.mutedForeground,
    negative: palette.destructive,
  };
  const replies = (index: number) =>
    data.series[index]?.labels.sentiment?.n ?? 0;

  return (
    <ChartPanel
      title={t('settings.analytics.insights.panels.sentiment')}
      empty={
        enough ? undefined : t('settings.analytics.insights.notEnoughReplies')
      }
      data-testid="insight-sentiment"
      chart={(legendId) => (
        <AnalyticsChart
          data={{
            labels: data.series.map((bucket) => formatDate(bucket.bucket)),
            datasets: SENTIMENT_SERIES.map((option) => ({
              label: optionName(t, 'sentiment', option),
              data: data.series.map(
                (bucket) => bucket.labels.sentiment?.options[option] ?? 0,
              ),
              backgroundColor: colors[option],
            })),
          }}
          legendID={legendId}
          maxTicksLimitInX={8}
          gridColor={palette.border}
          tickColor={palette.mutedForeground}
          isStacked
          tooltipCallbacks={{
            label: (item) => {
              const value = Number(item.raw);
              const n = replies(item.dataIndex);
              return t('settings.analytics.insights.panels.tooltipValue', {
                name: item.dataset.label,
                value: formatEstimate(value),
                share: formatShare(n > 0 ? value / n : 0),
                interpolation: { escapeValue: false },
              });
            },
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
