import { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionHeader } from '@/components/ui/section-header';
import { cn } from '@/lib/utils';

import { canAgent } from '../../agents/agentAccess';
import { agentEditPathFor } from '../../agents/paths';
import type { Agent } from '../../agents/types';
import SkeletonLoader from '../../components/SkeletonLoader';
import StatCard from '../../components/StatCard';
import { useChartPalette } from '../../utils/chartUtils';
import {
  EMPTY_VALUE,
  formatCount,
  formatDate,
  intlLocale,
} from '../../utils/dateTimeUtils';
import AnalyticsChart from '../AnalyticsChart';
import DocsGaps from '../DocsGaps';
import type { ConversationInsights as Insights } from '../types';
import {
  ANSWER_STATUS_SERIES,
  capitalize,
  drawnOptions,
  formatEstimate,
  formatEstimateRange,
  formatShare,
  formatShareRange,
  insightsState,
  joinList,
  languageName,
  MIN_SAMPLE,
  NONE_OF_THESE,
  optionBars,
  optionName,
  rangePoints,
  showsFigures,
  weakLanguages,
  type BarRow,
  type InsightsState,
} from './format';
import ChartPanel from './ChartPanel';
import ImplicitFeedbackPanel from './ImplicitFeedbackPanel';
import IntervalBars from './IntervalBars';
import SentimentPanel from './SentimentPanel';
import TierBadge from './TierBadge';
import { useConversationInsights } from './useConversationInsights';

const DOCS_URL =
  'https://docs.docsgpt.cloud/Using/analytics-and-logs#conversation-insights';

/** Labels the language note can name, by their inline (lower-case) names. */
const INLINE_LABELS = [
  'answer_status',
  'gap_type',
  'topic_effective',
  'reaction',
];

/** Gap types derived from signals not computed yet: drawn only once they carry mass. */
const GAP_SKIP = ['none'];

/** Chart panels ahead of the bar panels in the grid. */
const CHARTS = 3;

type ConversationInsightsProps = {
  state: InsightsState;
  data: Insights | null;
  agentId?: string;
  /** The agent whose page this is, for the link to its settings. */
  agent?: Agent;
  filterOption: string;
  onRetry: () => void;
  /**
   * The whole page (an agent's Insights), whose title already
   * names it: the section opens with its description, not a heading.
   */
  standalone?: boolean;
  /**
   * A page control at the end of a standalone page's description row
   * (Settings › Insights' time window, which has no toolbar to sit in).
   */
  actions?: ReactNode;
};

/**
 * Insights: what the decision model estimated about the
 * window's conversations, as rates with their ranges, then the docs-gap
 * report. A section of the account's Analytics, and an agent's own page. It
 * owns every off, empty and error message, so the panels and the report
 * render nothing in those states.
 */
export default function ConversationInsights({
  state,
  data,
  agentId,
  agent,
  filterOption,
  onRetry,
  standalone = false,
  actions,
}: ConversationInsightsProps) {
  const { t } = useTranslation();
  const canEditAgent = Boolean(agent) && canAgent(agent, 'edit');

  // Off on the server: nothing to show, and nothing the page can change.
  if (state === 'serverOff') return null;

  const coverage = data?.coverage;
  const count =
    state === 'partial' && coverage
      ? t('settings.analytics.insights.coverage', {
          labelled: formatCount(coverage.labelled_turns),
          total: formatCount(coverage.turns),
        })
      : undefined;
  const description = (
    <>
      {t('settings.analytics.insights.description')}{' '}
      <Button variant="link" size="text" asChild>
        <a href={DOCS_URL} target="_blank" rel="noopener noreferrer">
          {t('settings.analytics.insights.learnMore')}
        </a>
      </Button>
    </>
  );
  const intro = (
    <p className="text-muted-foreground text-sm leading-6">
      {description}
      {count && (
        <>
          <span aria-hidden> · </span>
          <span className="tabular-nums">{count}</span>
        </>
      )}
    </p>
  );
  const header = standalone ? (
    actions ? (
      // Analytics' description row: the text, then the control at the end.
      // The text takes the free width, so the control wraps under it only
      // where the two don't fit side by side (a phone).
      <div className="flex flex-row flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 flex-1 basis-xs">{intro}</div>
        {actions}
      </div>
    ) : (
      intro
    )
  ) : (
    <SectionHeader
      title={t('settings.analytics.insights.heading')}
      count={count}
      description={description}
    />
  );

  let body: ReactNode = null;
  if (state === 'loading') body = <InsightsSkeleton />;
  else if (state === 'error')
    body = (
      <EmptyState
        tone="destructive"
        size="sm"
        illustration="none"
        title={t('settings.analytics.insights.loadError')}
        onRetry={onRetry}
      />
    );
  else if (state === 'agentOff')
    body = (
      <Alert variant="info" role="note">
        <AlertDescription>
          {t('settings.analytics.insights.agentOff')}
          {agent && canEditAgent && (
            <>
              {' '}
              <Button variant="link" size="text" asChild>
                <Link to={agentEditPathFor(agent)}>
                  {t('settings.analytics.insights.agentOffLink')}
                </Link>
              </Button>
            </>
          )}
        </AlertDescription>
      </Alert>
    );
  else if (state === 'noTraffic')
    body = (
      <EmptyState
        size="sm"
        illustration="none"
        title={t('settings.analytics.insights.noTraffic')}
      />
    );
  else if (state === 'starting')
    body = (
      <EmptyState
        size="sm"
        illustration="none"
        title={t('settings.analytics.insights.starting')}
        description={t('settings.analytics.insights.startingDescription')}
      />
    );
  else if (showsFigures(state) && data)
    body = (
      <>
        <LanguageNote data={data} />
        <InsightTiles data={data} />
        <InsightPanels data={data} />
      </>
    );

  return (
    <>
      <section
        className={cn('flex flex-col gap-4', !standalone && 'mt-8')}
        data-testid="insights"
      >
        {header}
        {body}
      </section>
      {/* Its own section, the page rhythm's 32px below; only with figures,
          since the section above already says why there are none. */}
      {showsFigures(state) && data && (
        <DocsGaps
          agentId={agentId}
          agentName={agent?.name}
          filterOption={filterOption}
          hasTopics={
            Boolean(agentId) && (data.totals.topic_effective?.n ?? 0) > 0
          }
        />
      )}
    </>
  );
}

function InsightsSkeleton() {
  const { t } = useTranslation();
  const stats = [
    'fullyAnswered',
    'goalMet',
    'frustrated',
    'asksHuman',
    'docsGaps',
  ] as const;
  return (
    <>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
        {stats.map((key) => (
          <StatCard
            key={key}
            label={t(`settings.analytics.insights.stats.${key}`)}
            value={null}
            loading
          />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {(['answerStatus', 'whyNot'] as const).map((key) => (
          <Card
            key={key}
            variant="subtle"
            padding="lg"
            className="h-[345px] w-full overflow-hidden"
          >
            <SectionHeader
              as="h3"
              size="xs"
              title={t(`settings.analytics.insights.panels.${key}`)}
            />
            <SkeletonLoader count={1} component="analysis" />
          </Card>
        ))}
      </div>
    </>
  );
}

/** One note, under the header, when weaker languages make some labels less reliable. */
function LanguageNote({ data }: { data: Insights }) {
  const { t, i18n } = useTranslation();
  const warned = data.language_warnings.filter((label) =>
    INLINE_LABELS.includes(label),
  );
  if (warned.length === 0) return null;
  const locale = intlLocale(i18n.language);
  const { share, codes } = weakLanguages(
    data.languages,
    data.language_warnings,
  );
  if (codes.length === 0) return null;
  const languages = joinList(
    codes.map((code) =>
      languageName(
        code,
        locale,
        t('settings.analytics.insights.otherLanguages'),
      ),
    ),
    locale,
  );
  const labels = capitalize(
    joinList(
      warned.map((label) =>
        t(`settings.analytics.insights.labelNamesInline.${label}`),
      ),
      locale,
    ),
    locale,
  );
  return (
    <Alert variant="info" role="note">
      <AlertDescription>
        {t('settings.analytics.insights.languageNote', {
          share: formatShare(share, locale),
          languages,
          labels,
          interpolation: { escapeValue: false },
        })}
      </AlertDescription>
    </Alert>
  );
}

type Tile = {
  key: string;
  label: string;
  hint: string;
  value: string;
  sub: string;
};

/** The five headline tiles; each figure's own `n` is its denominator. */
function InsightTiles({ data }: { data: Insights }) {
  const { t } = useTranslation();
  const notEnough = (n: number) =>
    t('settings.analytics.insights.notEnough', { formatted: formatCount(n) });

  const rateTile = (
    key: string,
    label: string,
    option: string,
    subKey: string,
  ): Tile => {
    const totals = data.totals[label];
    const n = totals?.n ?? 0;
    const figure = totals?.options[option];
    const base = {
      key,
      label: t(`settings.analytics.insights.stats.${key}`),
      hint: t(`settings.analytics.insights.stats.${key}Hint`),
    };
    if (!figure || n < MIN_SAMPLE)
      return { ...base, value: EMPTY_VALUE, sub: notEnough(n) };
    return {
      ...base,
      value: formatShare(figure.rate),
      sub: t(`settings.analytics.insights.sub.${subKey}`, {
        count: n,
        formatted: formatCount(n),
        range: formatShareRange(figure.low, figure.high),
      }),
    };
  };

  const gaps = data.totals.gap_type;
  const gapsN = gaps?.n ?? 0;
  const docsMissing = gaps?.options['docs missing'];
  const docsGapsTile: Tile = {
    key: 'docsGaps',
    label: t('settings.analytics.insights.stats.docsGaps'),
    hint: t('settings.analytics.insights.stats.docsGapsHint'),
    ...(gapsN < MIN_SAMPLE
      ? { value: EMPTY_VALUE, sub: notEnough(gapsN) }
      : {
          value: formatEstimate(docsMissing?.expected ?? 0),
          sub: t('settings.analytics.insights.sub.inAnswers', {
            count: gapsN,
            formatted: formatCount(gapsN),
            range: docsMissing
              ? formatEstimateRange(
                  docsMissing.low * gapsN,
                  docsMissing.high * gapsN,
                )
              : formatCount(0),
          }),
        }),
  };

  const tiles: Tile[] = [
    rateTile('fullyAnswered', 'answer_status', 'fully answered', 'ofQuestions'),
    rateTile('goalMet', 'goal_met', 'yes', 'ofConversations'),
    rateTile('frustrated', 'frustrated', 'yes', 'ofReplies'),
    rateTile('asksHuman', 'asks_human', 'yes', 'ofReplies'),
    docsGapsTile,
  ];

  return (
    <div
      className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5"
      data-testid="insight-tiles"
    >
      {tiles.map((tile) => (
        <StatCard
          key={tile.key}
          data-testid={`insight-${tile.key}`}
          label={tile.label}
          value={tile.value}
          sub={tile.sub}
          hint={tile.hint}
        />
      ))}
    </div>
  );
}

/** The panel grid: answer status over time, then the interval-bar panels. */
function InsightPanels({ data }: { data: Insights }) {
  const { t } = useTranslation();
  const { totals } = data;

  const gapType = totals.gap_type;
  const notRetrievedShown =
    Math.round(gapType?.options['not retrieved']?.expected ?? 0) > 0;
  const gapRows = optionBars(
    gapType,
    (option) =>
      option === 'docs missing' && notRetrievedShown
        ? t('settings.analytics.insights.options.gapType.docsMissingOnly')
        : optionName(t, 'gap_type', option),
    { skip: GAP_SKIP, last: ['other'] },
  );
  const requestRows = optionBars(
    totals.request_type,
    (option) => optionName(t, 'request_type', option),
    { last: ['other'] },
  );
  const topic = totals.topic_effective;
  const topicRows = optionBars(
    topic,
    (option) =>
      option === NONE_OF_THESE
        ? t('settings.analytics.insights.panels.noneOfThese')
        : option,
    { last: [NONE_OF_THESE], ownerText: true },
  );
  const tagN = Math.max(
    0,
    ...data.tags.map((tag) => totals[`tag:${tag.id}`]?.n ?? 0),
  );
  const tagRows: BarRow[] = data.tags.map((tag) => {
    const tagTotals = totals[`tag:${tag.id}`];
    const yes = tagTotals?.options.yes;
    return {
      key: tag.id,
      label: tag.name,
      ownerText: true,
      value:
        yes && (tagTotals?.n ?? 0) >= MIN_SAMPLE
          ? { rate: yes.rate, low: yes.low, high: yes.high }
          : undefined,
    };
  });

  const bars: Omit<BarsPanelProps, 'wide'>[] = [
    {
      title: t('settings.analytics.insights.panels.requestType'),
      tier: 'estimated',
      n: totals.request_type?.n ?? 0,
      denominatorKey: 'shareOfMessages',
      rows: requestRows,
      points: rangePoints(drawnOptions(totals.request_type, requestRows)),
    },
    {
      title: t('settings.analytics.insights.panels.whyNot'),
      tier: 'estimated',
      n: gapType?.n ?? 0,
      denominatorKey: 'shareOfAnswers',
      rows: gapRows,
      points: rangePoints(drawnOptions(gapType, gapRows)),
    },
  ];
  if (data.tags.length > 0)
    bars.push({
      title: t('settings.analytics.insights.panels.tags'),
      n: tagN,
      denominatorKey: 'shareOfConversations',
      rows: tagRows,
      // A tag's own sample is checked per row: a new tag shows "—"
      // beside older ones.
      alwaysRows: true,
    });
  if (topic && topic.n > 0)
    bars.push({
      title: t('settings.analytics.insights.panels.topic'),
      tier: 'experimental',
      n: topic.n,
      denominatorKey: 'shareOfMessages',
      rows: topicRows,
    });

  // Rows of two with equal heights, paired by length: the three charts
  // first, the third beside request type's nine rows, then the two short
  // lists (why not, tags). An odd one out, usually topics, takes the whole
  // row and lays its bars in two columns.
  const odd = (CHARTS + bars.length) % 2 === 1;
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
      <AnswerStatusPanel data={data} />
      <SentimentPanel data={data} />
      <ImplicitFeedbackPanel data={data} />
      {bars.map((panel, index) => (
        <BarsPanel
          key={panel.title}
          {...panel}
          wide={odd && index === bars.length - 1}
        />
      ))}
    </div>
  );
}

function AnswerStatusPanel({ data }: { data: Insights }) {
  const { t } = useTranslation();
  const palette = useChartPalette();
  const enough = (data.totals.answer_status?.n ?? 0) >= MIN_SAMPLE;
  const colors = [
    palette.success,
    palette.warning,
    palette.destructive,
    palette.info,
  ];
  const bucketTotal = (index: number) =>
    ANSWER_STATUS_SERIES.reduce(
      (sum, option) =>
        sum + (data.series[index]?.labels.answer_status?.options[option] ?? 0),
      0,
    );
  return (
    <ChartPanel
      title={t('settings.analytics.insights.panels.answerStatus')}
      empty={
        enough ? undefined : t('settings.analytics.insights.notEnoughShort')
      }
      data-testid="insight-answer-status"
      chart={(legendId) => (
        <AnalyticsChart
          data={{
            labels: data.series.map((bucket) => formatDate(bucket.bucket)),
            datasets: ANSWER_STATUS_SERIES.map((option, index) => ({
              label: optionName(t, 'answer_status', option),
              data: data.series.map(
                (bucket) => bucket.labels.answer_status?.options[option] ?? 0,
              ),
              backgroundColor: colors[index],
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
              const total = bucketTotal(item.dataIndex);
              return t('settings.analytics.insights.panels.tooltipValue', {
                name: item.dataset.label,
                value: formatEstimate(value),
                share: formatShare(total > 0 ? value / total : 0),
                interpolation: { escapeValue: false },
              });
            },
          }}
        />
      )}
    />
  );
}

type BarsPanelProps = {
  title: string;
  tier?: 'estimated' | 'experimental';
  /** What every figure in the panel is a share of. */
  n: number;
  denominatorKey: 'shareOfAnswers' | 'shareOfMessages' | 'shareOfConversations';
  rows: BarRow[];
  points?: number;
  /** Draw the rows even under the sample floor (they check their own). */
  alwaysRows?: boolean;
  /** Span both grid columns, with the bars in two columns. */
  wide?: boolean;
};

function BarsPanel({
  title,
  tier,
  n,
  denominatorKey,
  rows,
  points,
  alwaysRows = false,
  wide = false,
}: BarsPanelProps) {
  const { t } = useTranslation();
  const enough = alwaysRows || n >= MIN_SAMPLE;
  const heading = <SectionHeader as="h3" size="xs" title={title} />;
  return (
    <Card
      variant="subtle"
      padding="lg"
      className={cn('w-full', wide && 'xl:col-span-2')}
    >
      {tier ? (
        <div className="flex flex-wrap items-center gap-2">
          {heading}
          <TierBadge
            tier={tier}
            points={tier === 'estimated' && enough ? points : undefined}
          />
        </div>
      ) : (
        heading
      )}
      {!enough ? (
        <EmptyState
          size="xs"
          illustration="none"
          title={t('settings.analytics.insights.notEnoughShort')}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          size="xs"
          illustration="none"
          title={t('settings.analytics.insights.panels.empty')}
        />
      ) : (
        <>
          {n > 0 && (
            <p className="text-muted-foreground text-xs">
              {t(`settings.analytics.insights.panels.${denominatorKey}`, {
                count: n,
                formatted: formatCount(n),
              })}
            </p>
          )}
          <IntervalBars rows={rows} ariaLabel={title} columns={wide ? 2 : 1} />
        </>
      )}
    </Card>
  );
}

type InsightsSectionProps = Omit<
  ConversationInsightsProps,
  'state' | 'data' | 'onRetry'
>;

/** `ConversationInsights` with its own fetch, for the window it is given. */
export function InsightsSection(props: InsightsSectionProps) {
  const insights = useConversationInsights(props.agentId, props.filterOption);
  return (
    <ConversationInsights
      {...props}
      state={insightsState(insights.status, insights.data)}
      data={insights.data}
      onRetry={insights.retry}
    />
  );
}
