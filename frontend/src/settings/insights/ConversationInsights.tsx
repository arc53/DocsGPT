import { useId, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionHeader } from '@/components/ui/section-header';

import { canAgent } from '../../agents/agentAccess';
import { agentEditPathFor } from '../../agents/paths';
import type { Agent } from '../../agents/types';
import SkeletonLoader from '../../components/SkeletonLoader';
import StatCard from '../../components/StatCard';
import { selectIsAdmin } from '../../preferences/preferenceSlice';
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
import IntervalBars from './IntervalBars';
import TierBadge from './TierBadge';

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

type ConversationInsightsProps = {
  state: InsightsState;
  data: Insights | null;
  agentId?: string;
  /** The agent whose page this is, for the link to its settings. */
  agent?: Agent;
  filterOption: string;
  onRetry: () => void;
};

/**
 * The Conversation insights section of Analytics: what the decision model
 * estimated about the window's conversations, as rates with their ranges,
 * then the docs-gap report. It owns every off, empty and error message, so
 * the panels and the report render nothing in those states.
 */
export default function ConversationInsights({
  state,
  data,
  agentId,
  agent,
  filterOption,
  onRetry,
}: ConversationInsightsProps) {
  const { t } = useTranslation();
  const isAdmin = useSelector(selectIsAdmin);
  const canEditAgent = Boolean(agent) && canAgent(agent, 'edit');

  // Only someone who can act on a note sees it: the server switch is the
  // administrator's, the agent's own switch its editors'.
  if (state === 'serverOff' && !isAdmin) return null;
  if (state === 'agentOff' && !canEditAgent) return null;

  const coverage = data?.coverage;
  const header = (
    <SectionHeader
      title={t('settings.analytics.insights.heading')}
      count={
        state === 'partial' && coverage
          ? t('settings.analytics.insights.coverage', {
              labelled: formatCount(coverage.labelled_turns),
              total: formatCount(coverage.turns),
            })
          : undefined
      }
      description={
        <>
          {t('settings.analytics.insights.description')}{' '}
          <Button variant="link" size="text" asChild>
            <a href={DOCS_URL} target="_blank" rel="noopener noreferrer">
              {t('settings.analytics.insights.learnMore')}
            </a>
          </Button>
        </>
      }
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
  else if (state === 'serverOff')
    body = (
      <Alert variant="info" role="note">
        <AlertDescription>
          {t('settings.analytics.insights.serverOff')}
        </AlertDescription>
      </Alert>
    );
  else if (state === 'agentOff' && agent)
    body = (
      <Alert variant="info" role="note">
        <AlertDescription>
          {t('settings.analytics.insights.agentOff')}{' '}
          <Button variant="link" size="text" asChild>
            <Link to={agentEditPathFor(agent)}>
              {t('settings.analytics.insights.agentOffLink')}
            </Link>
          </Button>
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
      <section className="mt-8 flex flex-col gap-4" data-testid="insights">
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

  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
      <AnswerStatusPanel data={data} />
      <BarsPanel
        title={t('settings.analytics.insights.panels.whyNot')}
        tier="estimated"
        n={gapType?.n ?? 0}
        denominatorKey="shareOfAnswers"
        rows={gapRows}
        points={rangePoints(drawnOptions(gapType, gapRows))}
      />
      <BarsPanel
        title={t('settings.analytics.insights.panels.requestType')}
        tier="estimated"
        n={totals.request_type?.n ?? 0}
        denominatorKey="shareOfMessages"
        rows={requestRows}
        points={rangePoints(drawnOptions(totals.request_type, requestRows))}
      />
      {topic && topic.n > 0 && (
        <BarsPanel
          title={t('settings.analytics.insights.panels.topic')}
          tier="experimental"
          n={topic.n}
          denominatorKey="shareOfMessages"
          rows={topicRows}
        />
      )}
      {data.tags.length > 0 && (
        <BarsPanel
          title={t('settings.analytics.insights.panels.tags')}
          n={tagN}
          denominatorKey="shareOfConversations"
          rows={tagRows}
          // A tag's own sample is checked per row: a new tag shows "—"
          // beside older ones.
          alwaysRows
        />
      )}
    </div>
  );
}

function AnswerStatusPanel({ data }: { data: Insights }) {
  const { t } = useTranslation();
  const palette = useChartPalette();
  const legendId = useId();
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
  const title = t('settings.analytics.insights.panels.answerStatus');
  return (
    <Card
      variant="subtle"
      padding="lg"
      className="h-[345px] w-full overflow-hidden"
      data-testid="insight-answer-status"
    >
      <SectionHeader as="h3" size="xs" title={title} />
      <div className="relative h-[245px] w-full">
        {enough ? (
          <>
            <div
              id={legendId}
              className="flex flex-row flex-wrap items-center justify-end"
            ></div>
            <AnalyticsChart
              data={{
                labels: data.series.map((bucket) => formatDate(bucket.bucket)),
                datasets: ANSWER_STATUS_SERIES.map((option, index) => ({
                  label: optionName(t, 'answer_status', option),
                  data: data.series.map(
                    (bucket) =>
                      bucket.labels.answer_status?.options[option] ?? 0,
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
          </>
        ) : (
          <EmptyState
            size="xs"
            illustration="none"
            title={t('settings.analytics.insights.notEnoughShort')}
          />
        )}
      </div>
    </Card>
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
};

function BarsPanel({
  title,
  tier,
  n,
  denominatorKey,
  rows,
  points,
  alwaysRows = false,
}: BarsPanelProps) {
  const { t } = useTranslation();
  const enough = alwaysRows || n >= MIN_SAMPLE;
  const heading = <SectionHeader as="h3" size="xs" title={title} />;
  return (
    <Card variant="subtle" padding="lg" className="w-full">
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
          <IntervalBars rows={rows} ariaLabel={title} />
        </>
      )}
    </Card>
  );
}
