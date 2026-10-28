import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { SectionHeader } from '@/components/ui/section-header';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

import { useChartPalette } from '../../utils/chartUtils';
import { formatCount, headingLocale } from '../../utils/dateTimeUtils';
import AnalyticsChart from '../AnalyticsChart';
import type { ConversationInsights } from '../types';
import ChartPanel from './ChartPanel';
import {
  bucketLabel,
  formatEstimate,
  formatShare,
  MIN_SAMPLE,
  optionName,
  optionsRate,
  periodChange,
  REACTION_SERIES,
  readsOverTime,
  SENTIMENT_SERIES,
} from './format';
import InsightHeadline, { type MixPart, type MixTone } from './InsightHeadline';
import ShareBars from './ShareBars';

type View = 'reaction' | 'tone';

/** The reactions that say an answer didn't help: asking again, pushback, a complaint. */
const NOT_HELPED = [
  ...REACTION_SERIES.reAsk,
  ...REACTION_SERIES.pushbackOrComplaint,
];

const SENTIMENT_TONES: Record<(typeof SENTIMENT_SERIES)[number], MixTone> = {
  positive: 'success',
  neutral: 'muted',
  negative: 'destructive',
};

/**
 * How users replied to answers, read two ways from the same replies: their
 * reaction (thanks, asking again, pushback or complaint, or moving on) and
 * their tone. Only messages sent after an answer count, so a conversation's
 * first message never does. Each way opens with its headline against the
 * previous period; over time, good replies stack up from zero and bad ones
 * down, in counts, with the neutral kind left undrawn and named in the
 * headline. With too few buckets worth a trend, both mixes as bars instead.
 */
export default function RepliesPanel({ data }: { data: ConversationInsights }) {
  const { t, i18n } = useTranslation();
  const palette = useChartPalette();
  const [view, setView] = useState<View>('reaction');
  const title = t('settings.analytics.insights.panels.replies');
  const reaction = data.totals.reaction;
  const sentiment = data.totals.sentiment;
  const n = reaction?.n ?? 0;
  if (!reaction || n < MIN_SAMPLE)
    return (
      <ChartPanel
        title={title}
        empty={t('settings.analytics.insights.notEnoughReplies')}
        data-testid="insight-replies"
      />
    );

  const toneN = sentiment?.n ?? 0;
  const hasTone = Boolean(sentiment) && toneN >= MIN_SAMPLE;
  const colors: Record<MixTone, string> = {
    success: palette.success,
    warning: palette.warning,
    destructive: palette.destructive,
    info: palette.info,
    muted: palette.mutedForeground,
  };
  const ofReplies = (count: number) =>
    t('settings.analytics.insights.sub.ofReplies', {
      count,
      formatted: formatCount(count),
    });

  const reactionParts: MixPart[] = [
    {
      key: 'thanks',
      label: t('settings.analytics.insights.options.reaction.thanks'),
      share: optionsRate(reaction, REACTION_SERIES.thanks),
      tone: 'success',
    },
    {
      key: 'reAsk',
      label: t('settings.analytics.insights.options.reaction.reAsk'),
      share: optionsRate(reaction, REACTION_SERIES.reAsk),
      tone: 'warning',
    },
    {
      key: 'pushbackOrComplaint',
      label: t(
        'settings.analytics.insights.options.reaction.pushbackOrComplaint',
      ),
      share: optionsRate(reaction, REACTION_SERIES.pushbackOrComplaint),
      tone: 'destructive',
    },
  ];
  const drawn = reactionParts.reduce((sum, part) => sum + part.share, 0);
  reactionParts.push({
    key: 'movedOn',
    label: t('settings.analytics.insights.options.reaction.movedOn'),
    share: Math.max(0, 1 - drawn),
    tone: 'muted',
  });
  const toneParts: MixPart[] = SENTIMENT_SERIES.map((option) => ({
    key: option,
    label: optionName(t, 'sentiment', option),
    share: sentiment?.options[option]?.rate ?? 0,
    tone: SENTIMENT_TONES[option],
  }));

  const notHelped = optionsRate(reaction, NOT_HELPED);
  const previousReaction = data.previous?.reaction;
  const reactionHeadline = (withMix: boolean) => (
    <InsightHeadline
      value={formatShare(notHelped)}
      label={t('settings.analytics.insights.headline.askedAgainOrPushedBack')}
      sub={ofReplies(n)}
      change={periodChange(
        notHelped,
        previousReaction && {
          n: previousReaction.n,
          rate: optionsRate(previousReaction, NOT_HELPED),
        },
      )}
      mix={withMix ? reactionParts : undefined}
    />
  );

  const sizes = data.series.map((bucket) => bucket.labels.reaction?.n ?? 0);
  if (!readsOverTime(sizes)) {
    const group = (heading: string, parts: MixPart[]) => (
      <div className="flex flex-col gap-2">
        <SectionHeader as="h3" size="sm" title={heading} />
        <ShareBars
          ariaLabel={heading}
          rows={parts.map(({ key, label, share, tone }) => ({
            key,
            label,
            rate: share,
            tone,
          }))}
        />
      </div>
    );
    return (
      <ChartPanel
        title={title}
        summary={reactionHeadline(false)}
        data-testid="insight-replies"
      >
        {group(t('settings.analytics.insights.panels.reaction'), reactionParts)}
        {hasTone &&
          group(t('settings.analytics.insights.panels.tone'), toneParts)}
      </ChartPanel>
    );
  }

  const shown: View = view === 'tone' && hasTone ? 'tone' : 'reaction';
  const negative = sentiment?.options.negative?.rate ?? 0;
  const previousTone = data.previous?.sentiment;
  const summary =
    shown === 'reaction' ? (
      reactionHeadline(true)
    ) : (
      <InsightHeadline
        value={formatShare(negative)}
        label={optionName(t, 'sentiment', 'negative')}
        sub={ofReplies(toneN)}
        change={periodChange(
          negative,
          previousTone && {
            n: previousTone.n,
            rate: previousTone.options.negative?.rate ?? 0,
          },
        )}
        mix={toneParts}
      />
    );

  // Up from zero for the good kind, down for the bad; the neutral kind is
  // in the headline only.
  const label = shown === 'reaction' ? 'reaction' : 'sentiment';
  const series: {
    name: string;
    options: readonly string[];
    tone: MixTone;
    sign: 1 | -1;
  }[] =
    shown === 'reaction'
      ? [
          {
            name: reactionParts[0].label,
            options: REACTION_SERIES.thanks,
            tone: 'success',
            sign: 1,
          },
          {
            name: reactionParts[1].label,
            options: REACTION_SERIES.reAsk,
            tone: 'warning',
            sign: -1,
          },
          {
            name: reactionParts[2].label,
            options: REACTION_SERIES.pushbackOrComplaint,
            tone: 'destructive',
            sign: -1,
          },
        ]
      : [
          {
            name: toneParts[0].label,
            options: ['positive'],
            tone: 'success',
            sign: 1,
          },
          {
            name: toneParts[2].label,
            options: ['negative'],
            tone: 'destructive',
            sign: -1,
          },
        ];
  const unit = data.bucket_unit ?? 'day';
  const locale = headingLocale(i18n.language);
  const bucketReplies = (index: number) =>
    data.series[index]?.labels[label]?.n ?? 0;

  return (
    <ChartPanel
      title={title}
      actions={
        hasTone && (
          <ToggleGroup
            type="single"
            size="xs"
            className="ml-auto"
            value={shown}
            onValueChange={(value) => {
              if (value) setView(value as View);
            }}
            aria-label={title}
          >
            <ToggleGroupItem value="reaction">
              {t('settings.analytics.insights.panels.reaction')}
            </ToggleGroupItem>
            <ToggleGroupItem value="tone">
              {t('settings.analytics.insights.panels.tone')}
            </ToggleGroupItem>
          </ToggleGroup>
        )
      }
      summary={
        <>
          {summary}
          <p className="text-muted-foreground text-xs">
            {t(
              shown === 'reaction'
                ? 'settings.analytics.insights.panels.notDrawnMovedOn'
                : 'settings.analytics.insights.panels.notDrawnNeutral',
            )}
          </p>
        </>
      }
      data-testid="insight-replies"
      chart={() => (
        <AnalyticsChart
          data={{
            labels: data.series.map((bucket) =>
              bucketLabel(bucket, unit, locale),
            ),
            datasets: series.map((item) => ({
              label: item.name,
              // `|| 0`: an empty bucket drawn down is 0, not -0.
              data: data.series.map(
                (bucket) =>
                  item.sign *
                    item.options.reduce(
                      (sum, option) =>
                        sum + (bucket.labels[label]?.options[option] ?? 0),
                      0,
                    ) || 0,
              ),
              backgroundColor: colors[item.tone],
            })),
          }}
          maxTicksLimitInX={8}
          gridColor={palette.border}
          tickColor={palette.mutedForeground}
          isStacked
          columnTooltip
          diverging
          tooltipCallbacks={{
            label: (item) =>
              t('settings.analytics.insights.panels.tooltipItem', {
                name: item.dataset.label,
                value: formatEstimate(Math.abs(Number(item.raw))),
                interpolation: { escapeValue: false },
              }),
            footer: (items) => {
              const count = bucketReplies(items[0]?.dataIndex ?? -1);
              return t('settings.analytics.insights.panels.ofReplies', {
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
