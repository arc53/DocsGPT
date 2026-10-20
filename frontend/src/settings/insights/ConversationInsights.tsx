import { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Progress } from '@/components/ui/progress';
import { SectionHeader } from '@/components/ui/section-header';
import { cn } from '@/lib/utils';

import { canAgent } from '../../agents/agentAccess';
import type { Agent } from '../../agents/types';
import SkeletonLoader from '../../components/SkeletonLoader';
import StatCard from '../../components/StatCard';
import { useChartPalette } from '../../utils/chartUtils';
import {
  EMPTY_VALUE,
  formatCount,
  formatDate,
  headingLocale,
  intlLocale,
} from '../../utils/dateTimeUtils';
import AnalyticsChart from '../AnalyticsChart';
import DocsGaps from '../DocsGaps';
import { timeFilterKey } from '../TimeFilterSelect';
import type { ConversationInsights as Insights } from '../types';
import {
  ANSWER_STATUS_SERIES,
  capitalize,
  formatEstimate,
  formatShare,
  joinList,
  languageName,
  MIN_SAMPLE,
  NONE_OF_THESE,
  optionBars,
  optionName,
  shareOfDay,
  showsFigures,
  weakLanguages,
  type BarRow,
  type InsightsState,
} from './format';
import ChartPanel from './ChartPanel';
import ImplicitFeedbackPanel from './ImplicitFeedbackPanel';
import SentimentPanel from './SentimentPanel';
import ShareBars from './ShareBars';

const DOCS_URL =
  'https://docs.docsgpt.cloud/Using/analytics-and-logs#conversation-insights';

/** Labels the language note can name, by their inline (lower-case) names. */
const INLINE_LABELS = [
  'answer_status',
  'gap_type',
  'topic_effective',
  'reaction',
];

/**
 * Gap types never drawn: `none` is the leftover share of fully answered
 * answers, not a reason one fell short.
 */
const GAP_SKIP = ['none'];

/** Chart panels ahead of the bar panels in the grid. */
const CHARTS = 3;

type ConversationInsightsProps = {
  state: InsightsState;
  data: Insights | null;
  agentId?: string;
  /** The agent whose page this is: Turn on is only for who can edit it. */
  agent?: Agent;
  /** Opens the page's insights settings switched on (the off state's Turn on). */
  onTurnOn?: () => void;
  filterOption: string;
  onRetry: () => void;
  /**
   * The whole page (an agent's Insights), whose title already
   * names it: the section opens with its description, not a heading.
   */
  standalone?: boolean;
  /**
   * False when the page draws `InsightsIntro` in its own toolbar, beside the
   * window select (Settings › Insights), so the section opens with figures.
   */
  intro?: boolean;
};

/**
 * The insights description and, while labelling is partial, its coverage:
 * labelled of what the sweep will label, so answers older than its window
 * (never labelled) leave the count out.
 */
function useInsightsCopy(state: InsightsState, data: Insights | null) {
  const { t } = useTranslation();
  const coverage = data?.coverage;
  const count =
    state === 'partial' && coverage
      ? t('settings.analytics.insights.coverage', {
          labelled: formatCount(coverage.labelled_turns),
          total: formatCount(
            coverage.labelled_turns + coverage.unlabelled_recent_turns,
          ),
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
  return { count, description };
}

/**
 * The intro of insights as a page of its own: the description, its Learn
 * more link and the coverage count, as inline content for a paragraph (the
 * section's own, or a page toolbar's `intro`).
 */
export function InsightsIntro({
  state,
  data,
}: {
  state: InsightsState;
  data: Insights | null;
}) {
  const { count, description } = useInsightsCopy(state, data);
  return (
    <>
      {description}
      {count && (
        <>
          <span aria-hidden> · </span>
          <span className="tabular-nums">{count}</span>
        </>
      )}
    </>
  );
}

/**
 * Insights: what the decision model estimated about the
 * window's conversations, as rates, then the docs-gap
 * report. The body of an agent's Insights page and of Settings › Insights. It
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
  intro = true,
  onTurnOn,
}: ConversationInsightsProps) {
  const { t } = useTranslation();
  const { count, description } = useInsightsCopy(state, data);
  const canEditAgent = Boolean(agent) && canAgent(agent, 'edit');

  // Off on the server: nothing to show, and nothing the page can change.
  if (state === 'serverOff') return null;

  // The intro (what the figures are, how many answers are in) only sits
  // above figures: every other state says what it is itself.
  const header =
    !intro || !showsFigures(state) ? null : standalone ? (
      <p className="text-muted-foreground text-sm leading-6">
        <InsightsIntro state={state} data={data} />
      </p>
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
      <EmptyState
        size="sm"
        illustration="none"
        title={t('settings.analytics.insights.off.title')}
        description={t('settings.analytics.insights.off.description')}
        action={
          canEditAgent &&
          onTurnOn && (
            <Button
              type="button"
              variant="outline"
              size="field"
              shape="pill"
              onClick={onTurnOn}
            >
              {t('settings.analytics.insights.off.turnOn')}
            </Button>
          )
        }
      />
    );
  else if (state === 'noTraffic')
    body = (
      <EmptyState
        size="sm"
        illustration="none"
        title={t(
          `settings.analytics.insights.noConversations.${timeFilterKey(filterOption)}`,
        )}
        description={t(
          'settings.analytics.insights.noConversationsDescription',
        )}
      />
    );
  else if (state === 'analyzing' && data) body = <AnalyzingState data={data} />;
  else if (state === 'olderOnly' && data) body = <OlderOnlyState data={data} />;
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

/**
 * The sweep is still labelling the window's answers, newest first: how many
 * are done of those it will label (older ones it never does).
 */
function AnalyzingState({ data }: { data: Insights }) {
  const { t } = useTranslation();
  const { labelled_turns: done, unlabelled_recent_turns: waiting } =
    data.coverage;
  const total = done + waiting;
  const title = t('settings.analytics.insights.analyzing.title');
  return (
    <EmptyState
      size="sm"
      illustration="none"
      title={title}
      description={
        <span className="tabular-nums">
          {t('settings.analytics.insights.analyzing.progress', {
            count: total,
            labelled: formatCount(done),
            formatted: formatCount(total),
          })}
        </span>
      }
      action={
        // The action slot sizes to its content: a fixed width that fits a
        // phone's column, the description's width above it.
        <Progress
          className="w-64 sm:w-96"
          value={total > 0 ? (done / total) * 100 : 0}
          aria-label={title}
        />
      }
    />
  );
}

/** Every answer in the window is older than the labelling window: none will be labelled. */
function OlderOnlyState({ data }: { data: Insights }) {
  const { t, i18n } = useTranslation();
  const from = new Date(data.labelling_from);
  const date = Number.isNaN(from.getTime())
    ? EMPTY_VALUE
    : new Intl.DateTimeFormat(headingLocale(i18n.language), {
        day: 'numeric',
        month: 'short',
      }).format(from);
  return (
    <EmptyState
      size="sm"
      illustration="none"
      title={t('settings.analytics.insights.olderOnly.title')}
      description={t('settings.analytics.insights.olderOnly.description', {
        date,
        interpolation: { escapeValue: false },
      })}
    />
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
        {stats.map((key, index) => (
          <StatCard
            key={key}
            className={cn(
              index === stats.length - 1 && 'col-span-2 md:col-span-1',
            )}
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
      {tiles.map((tile, index) => (
        <StatCard
          key={tile.key}
          // The fifth spans the phone's two columns rather than sit alone.
          className={cn(
            index === tiles.length - 1 && 'col-span-2 md:col-span-1',
          )}
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

/** The panel grid: answer status over time, then the share-bar panels. */
function InsightPanels({ data }: { data: Insights }) {
  const { t } = useTranslation();
  const { totals } = data;

  const gapType = totals.gap_type;
  const gapRows = optionBars(
    gapType,
    (option) => optionName(t, 'gap_type', option),
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
    { last: [NONE_OF_THESE] },
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
      rate: yes && (tagTotals?.n ?? 0) >= MIN_SAMPLE ? yes.rate : undefined,
    };
  });

  const bars: Omit<BarsPanelProps, 'wide'>[] = [
    {
      title: t('settings.analytics.insights.panels.requestType'),
      n: totals.request_type?.n ?? 0,
      denominatorKey: 'shareOfMessages',
      rows: requestRows,
    },
    {
      title: t('settings.analytics.insights.panels.whyNot'),
      n: gapType?.n ?? 0,
      denominatorKey: 'shareOfAnswers',
      rows: gapRows,
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

/**
 * How questions were answered over time, each day as its share of that
 * day's four outcomes; greetings ("not a request") are left out.
 */
function AnswerStatusPanel({ data }: { data: Insights }) {
  const { t } = useTranslation();
  const palette = useChartPalette();
  const enough = (data.totals.answer_status?.n ?? 0) >= MIN_SAMPLE;
  // Declining when the docs have nothing is "no answer", not a failure: the
  // neutral grey Sentiment uses, so red stays for real negatives. The legend
  // reads each dataset's colour, so it shows the same map.
  const colors: Record<(typeof ANSWER_STATUS_SERIES)[number], string> = {
    'fully answered': palette.success,
    'partially answered': palette.warning,
    'declined, no information': palette.mutedForeground,
    'asked a clarifying question': palette.info,
  };
  const questions = (index: number) =>
    data.series[index]?.labels.answer_status?.n ?? 0;
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
            datasets: ANSWER_STATUS_SERIES.map((option) => ({
              label: optionName(t, 'answer_status', option),
              data: data.series.map((bucket, index) =>
                shareOfDay(
                  bucket.labels.answer_status?.options[option] ?? 0,
                  bucketTotal(index),
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
              const n = questions(items[0]?.dataIndex ?? -1);
              return t('settings.analytics.insights.panels.ofQuestions', {
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

type BarsPanelProps = {
  title: string;
  /** What every figure in the panel is a share of. */
  n: number;
  denominatorKey: 'shareOfAnswers' | 'shareOfMessages' | 'shareOfConversations';
  rows: BarRow[];
  /** Draw the rows even under the sample floor (they check their own). */
  alwaysRows?: boolean;
  /** Span both grid columns, with the bars in two columns. */
  wide?: boolean;
};

function BarsPanel({
  title,
  n,
  denominatorKey,
  rows,
  alwaysRows = false,
  wide = false,
}: BarsPanelProps) {
  const { t } = useTranslation();
  const enough = alwaysRows || n >= MIN_SAMPLE;
  return (
    <Card
      variant="subtle"
      padding="lg"
      className={cn('w-full', wide && 'xl:col-span-2')}
    >
      <SectionHeader as="h3" size="xs" title={title} />
      {!enough ? (
        <EmptyState
          size="sm"
          illustration="none"
          title={t('settings.analytics.insights.notEnoughShort')}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          size="sm"
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
          <ShareBars rows={rows} ariaLabel={title} columns={wide ? 2 : 1} />
        </>
      )}
    </Card>
  );
}
