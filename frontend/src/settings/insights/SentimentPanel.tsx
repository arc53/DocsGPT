import { useTranslation } from 'react-i18next';

import { useChartPalette } from '../../utils/chartUtils';
import { formatCount, formatDate } from '../../utils/dateTimeUtils';
import AnalyticsChart from '../AnalyticsChart';
import type { ConversationInsights } from '../types';
import {
  formatShare,
  MIN_SAMPLE,
  optionName,
  SENTIMENT_SERIES,
  shareOfDay,
} from './format';
import ChartPanel from './ChartPanel';

/**
 * The tone of users' replies over time: positive, neutral and negative,
 * each day as its share of that day's replies. Like frustration, only
 * messages sent after an answer are read, so a conversation's first message
 * never counts.
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
              data: data.series.map((bucket) =>
                shareOfDay(
                  bucket.labels.sentiment?.options[option] ?? 0,
                  bucket.labels.sentiment?.n ?? 0,
                ),
              ),
              backgroundColor: colors[option],
            })),
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
