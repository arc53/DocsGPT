import { useTranslation } from 'react-i18next';

import { useChartPalette } from '../../utils/chartUtils';
import { formatCount, headingLocale } from '../../utils/dateTimeUtils';
import AnalyticsChart from '../AnalyticsChart';
import type { ConversationInsights, InsightSeriesBucket } from '../types';
import ChartPanel from './ChartPanel';
import {
  ANSWER_STATUS_SERIES,
  bucketLabel,
  formatEstimate,
  formatShare,
  MIN_SAMPLE,
  optionName,
  periodChange,
  readsOverTime,
} from './format';
import InsightHeadline, { type MixTone } from './InsightHeadline';
import ShareBars from './ShareBars';

type Outcome = (typeof ANSWER_STATUS_SERIES)[number];

// Declining when the docs have nothing is "no answer", not a failure: the
// neutral grey, so red stays for real negatives.
const TONES: Record<Outcome, MixTone> = {
  'fully answered': 'success',
  'partially answered': 'warning',
  'declined, no information': 'muted',
  'asked a clarifying question': 'info',
};

/** A bucket's questions: its four outcomes, greetings ("not a request") left out. */
const questions = (bucket: InsightSeriesBucket) =>
  ANSWER_STATUS_SERIES.reduce(
    (sum, option) => sum + (bucket.labels.answer_status?.options[option] ?? 0),
    0,
  );

/**
 * How questions were answered: the period's fully-answered share against the
 * previous period, then each bucket's questions stacked by outcome, so a
 * quiet week is a short column. With too few buckets worth a trend, the
 * period's outcomes as bars instead.
 */
export default function AnswerStatusPanel({
  data,
}: {
  data: ConversationInsights;
}) {
  const { t, i18n } = useTranslation();
  const palette = useChartPalette();
  const title = t('settings.analytics.insights.panels.answerStatus');
  const totals = data.totals.answer_status;
  const n = totals?.n ?? 0;
  if (!totals || n < MIN_SAMPLE)
    return (
      <ChartPanel
        title={title}
        empty={t('settings.analytics.insights.notEnoughShort')}
        data-testid="insight-answer-status"
      />
    );

  const colors: Record<MixTone, string> = {
    success: palette.success,
    warning: palette.warning,
    destructive: palette.destructive,
    info: palette.info,
    muted: palette.mutedForeground,
  };
  const mix = ANSWER_STATUS_SERIES.map((option) => ({
    key: option,
    label: optionName(t, 'answer_status', option),
    share: totals.options[option]?.rate ?? 0,
    tone: TONES[option],
  }));
  const fully = totals.options['fully answered']?.rate ?? 0;
  const previous = data.previous?.answer_status;
  const sizes = data.series.map(questions);
  const overTime = readsOverTime(sizes);
  const summary = (
    <InsightHeadline
      value={formatShare(fully)}
      label={t('settings.analytics.insights.stats.fullyAnswered')}
      sub={t('settings.analytics.insights.sub.ofQuestions', {
        count: n,
        formatted: formatCount(n),
      })}
      change={periodChange(
        fully,
        previous && {
          n: previous.n,
          rate: previous.options['fully answered']?.rate ?? 0,
        },
      )}
      mix={overTime ? mix : undefined}
    />
  );

  if (!overTime)
    return (
      <ChartPanel
        title={title}
        summary={summary}
        data-testid="insight-answer-status"
      >
        <ShareBars
          ariaLabel={title}
          rows={mix.map(({ key, label, share, tone }) => ({
            key,
            label,
            rate: share,
            tone,
          }))}
        />
      </ChartPanel>
    );

  const unit = data.bucket_unit ?? 'day';
  const locale = headingLocale(i18n.language);
  return (
    <ChartPanel
      title={title}
      summary={summary}
      data-testid="insight-answer-status"
      chart={() => (
        <AnalyticsChart
          data={{
            labels: data.series.map((bucket) =>
              bucketLabel(bucket, unit, locale),
            ),
            datasets: ANSWER_STATUS_SERIES.map((option) => ({
              label: optionName(t, 'answer_status', option),
              data: data.series.map(
                (bucket) => bucket.labels.answer_status?.options[option] ?? 0,
              ),
              backgroundColor: colors[TONES[option]],
            })),
          }}
          maxTicksLimitInX={8}
          gridColor={palette.border}
          tickColor={palette.mutedForeground}
          isStacked
          columnTooltip
          tooltipCallbacks={{
            label: (item) =>
              t('settings.analytics.insights.panels.tooltipItem', {
                name: item.dataset.label,
                value: formatEstimate(Number(item.raw)),
                interpolation: { escapeValue: false },
              }),
            footer: (items) => {
              const count = Math.round(sizes[items[0]?.dataIndex ?? -1] ?? 0);
              return t('settings.analytics.insights.panels.ofQuestions', {
                count,
                formatted: formatCount(count),
              });
            },
          }}
        />
      )}
    />
  );
}
