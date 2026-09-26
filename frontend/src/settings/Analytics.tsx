import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Title,
  Tooltip,
} from 'chart.js';
import { useEffect, useRef, useState } from 'react';
import { Bar } from 'react-chartjs-2';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { foldSeries, OTHER_SERIES_KEY } from './foldSeries';

import userService from '../api/services/userService';
import SkeletonLoader from '../components/SkeletonLoader';
import StatCard from '../components/StatCard';
import { Card } from '../components/ui/card';
import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { Switch } from '../components/ui/switch';
import { useLoaderState } from '../hooks';
import { selectToken } from '../preferences/preferenceSlice';
import {
  hoverColor,
  htmlLegendPlugin,
  useChartPalette,
} from '../utils/chartUtils';
import { formatDate } from '../utils/dateTimeUtils';
import UsageQuota from './components/UsageQuota';

import type { ChartData } from 'chart.js';
ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
);

type TokenGroupBy = 'none' | 'model' | 'agent' | 'source';

type AnalyticsProps = {
  agentId?: string;
};

export default function Analytics({ agentId }: AnalyticsProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const filterOptions = [
    { label: t('settings.analytics.filterOptions.hour'), value: 'last_hour' },
    {
      label: t('settings.analytics.filterOptions.last24Hours'),
      value: 'last_24_hour',
    },
    {
      label: t('settings.analytics.filterOptions.last7Days'),
      value: 'last_7_days',
    },
    {
      label: t('settings.analytics.filterOptions.last15Days'),
      value: 'last_15_days',
    },
    {
      label: t('settings.analytics.filterOptions.last30Days'),
      value: 'last_30_days',
    },
  ];

  const groupByOptions: { label: string; value: TokenGroupBy }[] = [
    { label: t('settings.analytics.groupOptions.total'), value: 'none' },
    { label: t('settings.analytics.groupOptions.model'), value: 'model' },
    // Grouping by agent is meaningless on a single agent's page.
    ...(agentId
      ? []
      : [
          {
            label: t('settings.analytics.groupOptions.agent'),
            value: 'agent' as TokenGroupBy,
          },
        ]),
    { label: t('settings.analytics.groupOptions.source'), value: 'source' },
  ];

  const [messagesData, setMessagesData] = useState<Record<
    string,
    number
  > | null>(null);
  const [tokenUsageData, setTokenUsageData] = useState<Record<
    string,
    number
  > | null>(null);
  const [tokenSeries, setTokenSeries] = useState<Record<
    string,
    Record<string, number>
  > | null>(null);
  const [feedbackData, setFeedbackData] = useState<Record<
    string,
    { positive: number; negative: number }
  > | null>(null);
  const [toolsData, setToolsData] = useState<
    { tool_name: string; calls: number; failures: number }[] | null
  >(null);
  const [scheduleData, setScheduleData] = useState<Record<
    string,
    { completed: number; failed: number; skipped: number }
  > | null>(null);

  const [timeFilter, setTimeFilter] = useState<{
    label: string;
    value: string;
  }>({
    label: t('settings.analytics.filterOptions.last30Days'),
    value: 'last_30_days',
  });
  const [tokenGroupBy, setTokenGroupBy] = useState<TokenGroupBy>('none');
  // Side-channel = tokens spent outside a user request (title generation,
  // history compression, RAG condensing).
  const [includeSideChannel, setIncludeSideChannel] = useState(false);

  const [loadingMessages, setLoadingMessages] = useLoaderState(true);
  const [loadingTokens, setLoadingTokens] = useLoaderState(true);
  const [loadingFeedback, setLoadingFeedback] = useLoaderState(true);
  const [loadingTools, setLoadingTools] = useLoaderState(true);
  const [loadingSchedules, setLoadingSchedules] = useLoaderState(true);
  // Re-read on every theme change; Chart.js can't read CSS variables.
  const palette = useChartPalette();
  const primaryColor = palette.primary;
  const seriesColor = (index: number) =>
    palette.series[index % palette.series.length];

  // Monotonic request ids, one per chart: a response only lands if no
  // newer request for that chart was issued meanwhile, so an
  // out-of-order response can't leave a chart showing data for a
  // different filter combination than the controls.
  const requestIds = useRef({
    messages: 0,
    tokens: 0,
    feedback: 0,
    tools: 0,
    schedules: 0,
  });

  const fetchMessagesData = async (agent_id?: string, filter?: string) => {
    const reqId = ++requestIds.current.messages;
    setLoadingMessages(true);
    try {
      const response = await userService.getMessageAnalytics(
        {
          api_key_id: agent_id,
          filter_option: filter,
        },
        token,
      );
      if (!response.ok) throw new Error('Failed to fetch analytics data');
      const data = await response.json();
      if (reqId !== requestIds.current.messages) return;
      setMessagesData(data.messages);
    } catch (error) {
      console.error(error);
    } finally {
      if (reqId === requestIds.current.messages) setLoadingMessages(false);
    }
  };

  const fetchTokenData = async (
    agent_id?: string,
    filter?: string,
    groupBy?: TokenGroupBy,
    sideChannel?: boolean,
  ) => {
    const reqId = ++requestIds.current.tokens;
    setLoadingTokens(true);
    try {
      const response = await userService.getTokenAnalytics(
        {
          api_key_id: agent_id,
          filter_option: filter,
          group_by: groupBy,
          include_side_channel: sideChannel,
        },
        token,
      );
      if (!response.ok) throw new Error('Failed to fetch analytics data');
      const data = await response.json();
      if (reqId !== requestIds.current.tokens) return;
      setTokenUsageData(data.token_usage);
      setTokenSeries(data.series);
    } catch (error) {
      console.error(error);
    } finally {
      if (reqId === requestIds.current.tokens) setLoadingTokens(false);
    }
  };

  const fetchFeedbackData = async (agent_id?: string, filter?: string) => {
    const reqId = ++requestIds.current.feedback;
    setLoadingFeedback(true);
    try {
      const response = await userService.getFeedbackAnalytics(
        {
          api_key_id: agent_id,
          filter_option: filter,
        },
        token,
      );
      if (!response.ok) throw new Error('Failed to fetch analytics data');
      const data = await response.json();
      if (reqId !== requestIds.current.feedback) return;
      setFeedbackData(data.feedback);
    } catch (error) {
      console.error(error);
    } finally {
      if (reqId === requestIds.current.feedback) setLoadingFeedback(false);
    }
  };

  const fetchToolsData = async (agent_id?: string, filter?: string) => {
    const reqId = ++requestIds.current.tools;
    setLoadingTools(true);
    try {
      const response = await userService.getToolAnalytics(
        {
          api_key_id: agent_id,
          filter_option: filter,
        },
        token,
      );
      if (!response.ok) throw new Error('Failed to fetch analytics data');
      const data = await response.json();
      if (reqId !== requestIds.current.tools) return;
      setToolsData(data.tools);
    } catch (error) {
      console.error(error);
    } finally {
      if (reqId === requestIds.current.tools) setLoadingTools(false);
    }
  };

  const fetchScheduleData = async (agent_id?: string, filter?: string) => {
    const reqId = ++requestIds.current.schedules;
    setLoadingSchedules(true);
    try {
      const response = await userService.getScheduleAnalytics(
        {
          api_key_id: agent_id,
          filter_option: filter,
        },
        token,
      );
      if (!response.ok) throw new Error('Failed to fetch analytics data');
      const data = await response.json();
      if (reqId !== requestIds.current.schedules) return;
      setScheduleData(data.runs);
    } catch (error) {
      console.error(error);
    } finally {
      if (reqId === requestIds.current.schedules) setLoadingSchedules(false);
    }
  };

  useEffect(() => {
    fetchMessagesData(agentId, timeFilter.value);
    fetchFeedbackData(agentId, timeFilter.value);
    fetchToolsData(agentId, timeFilter.value);
    fetchScheduleData(agentId, timeFilter.value);
  }, [agentId, timeFilter]);

  useEffect(() => {
    fetchTokenData(agentId, timeFilter.value, tokenGroupBy, includeSideChannel);
  }, [agentId, timeFilter, tokenGroupBy, includeSideChannel]);

  const totalMessages = Object.values(messagesData || {}).reduce(
    (sum, value) => sum + value,
    0,
  );
  const totalTokens = Object.values(tokenUsageData || {}).reduce(
    (sum, value) => sum + value,
    0,
  );
  const totalToolCalls = (toolsData || []).reduce(
    (sum, tool) => sum + tool.calls,
    0,
  );
  const feedbackTotals = Object.values(feedbackData || {}).reduce(
    (sum, value) => ({
      positive: sum.positive + value.positive,
      negative: sum.negative + value.negative,
    }),
    { positive: 0, negative: 0 },
  );
  const scheduleTotals = Object.values(scheduleData || {}).reduce(
    (sum, value) => ({
      completed: sum.completed + value.completed,
      failed: sum.failed + value.failed,
      skipped: sum.skipped + value.skipped,
    }),
    { completed: 0, failed: 0, skipped: 0 },
  );
  const scheduleRunsTotal = scheduleTotals.completed + scheduleTotals.failed;
  const scheduleSuccessRate =
    scheduleRunsTotal > 0
      ? `${Math.round((scheduleTotals.completed / scheduleRunsTotal) * 100)}%`
      : '—';

  const statCards: { label: string; value: string; hint?: string }[] = [
    {
      label: t('settings.analytics.stats.messages'),
      value: totalMessages.toLocaleString(),
    },
    {
      label: t('settings.analytics.stats.tokens'),
      value: totalTokens.toLocaleString(),
      hint: t('settings.analytics.stats.tokensHint'),
    },
    {
      label: t('settings.analytics.stats.toolCalls'),
      value: totalToolCalls.toLocaleString(),
    },
    {
      label: t('settings.analytics.stats.runSuccess'),
      value: scheduleSuccessRate,
    },
    {
      label: t('settings.analytics.stats.feedback'),
      value: `+${feedbackTotals.positive} / -${feedbackTotals.negative}`,
    },
  ];

  // Grouped series have no meaning of their own, so past five they fold into
  // "Other" instead of repeating a colour (DESIGN.md, chart colours).
  const tokenSeriesEntries = foldSeries(Object.entries(tokenSeries || {}));
  const tokenLabels = Object.keys(
    tokenSeriesEntries[0]?.[1] || tokenUsageData || {},
  ).map((item) => formatDate(item));
  const tokenDatasets = tokenSeriesEntries.map(([key, series], index) => ({
    label:
      tokenGroupBy === 'none'
        ? key === 'prompt'
          ? t('settings.analytics.promptTokens')
          : t('settings.analytics.generatedTokens')
        : key === OTHER_SERIES_KEY
          ? t('settings.analytics.otherSeries')
          : key,
    data: Object.values(series),
    backgroundColor: seriesColor(index),
  }));

  return (
    <div>
      {agentId ? null : <UsageQuota />}
      <div className="mb-5 flex flex-row flex-wrap items-center justify-between gap-3">
        <p className="text-muted-foreground text-sm leading-6">
          {t('settings.analytics.subtitle')}
        </p>
        <Select
          value={timeFilter.value}
          onValueChange={(value) => {
            const opt = filterOptions.find((o) => o.value === value);
            if (opt) setTimeFilter(opt);
          }}
        >
          <SelectTrigger className="w-[125px]" size="field" shape="pill">
            <SelectValue
              placeholder={t('settings.analytics.filterPlaceholder')}
            />
          </SelectTrigger>
          <SelectContent>
            {filterOptions.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Summary stat cards */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
        {statCards.map((card) => (
          <StatCard
            key={card.label}
            label={card.label}
            value={card.value}
            hint={card.hint}
          />
        ))}
      </div>

      {/* Messages Analytics */}
      <div className="mt-4 flex w-full flex-col gap-3 xl:flex-row">
        <Card
          variant="subtle"
          padding="lg"
          className="h-[345px] w-full overflow-hidden xl:w-1/2"
        >
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.analytics.messages')}
          />
          <div className="relative h-[245px] w-full">
            <div
              id="legend-container-1"
              className="flex flex-row items-center justify-end"
            ></div>
            {loadingMessages ? (
              <SkeletonLoader count={1} component={'analysis'} />
            ) : (
              <AnalyticsChart
                data={{
                  labels: Object.keys(messagesData || {}).map((item) =>
                    formatDate(item),
                  ),
                  datasets: [
                    {
                      label: t('settings.analytics.messages'),
                      data: Object.values(messagesData || {}),
                      backgroundColor: primaryColor,
                    },
                  ],
                }}
                legendID="legend-container-1"
                maxTicksLimitInX={8}
                gridColor={palette.border}
                tickColor={palette.mutedForeground}
                isStacked={false}
              />
            )}
          </div>
        </Card>

        {/* Token Usage Analytics */}
        <Card
          variant="subtle"
          padding="lg"
          className="h-[345px] w-full overflow-hidden xl:w-1/2"
        >
          <div className="flex flex-row flex-wrap items-center justify-start gap-3">
            <SectionHeader
              as="h3"
              size="xs"
              title={t('settings.analytics.tokenUsage')}
            />
            <Select
              value={tokenGroupBy}
              onValueChange={(value) => setTokenGroupBy(value as TokenGroupBy)}
            >
              <SelectTrigger className="w-[110px]" size="field" shape="pill">
                <SelectValue placeholder={t('settings.analytics.groupBy')} />
              </SelectTrigger>
              <SelectContent>
                {groupByOptions.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="ml-auto flex flex-row items-center gap-2">
              <p className="text-muted-foreground text-xs">
                {t('settings.analytics.includeSideChannel')}
              </p>
              <Switch
                aria-label={t('settings.analytics.includeSideChannel')}
                checked={includeSideChannel}
                onCheckedChange={setIncludeSideChannel}
              />
            </div>
          </div>
          <div className="relative h-[245px] w-full">
            <div
              id="legend-container-2"
              className="flex flex-row items-center justify-end"
            ></div>
            {loadingTokens ? (
              <SkeletonLoader count={1} component={'analysis'} />
            ) : (
              <AnalyticsChart
                data={{
                  labels: tokenLabels,
                  datasets: tokenDatasets,
                }}
                legendID="legend-container-2"
                maxTicksLimitInX={8}
                gridColor={palette.border}
                tickColor={palette.mutedForeground}
                isStacked={true}
              />
            )}
          </div>
        </Card>
      </div>

      {/* Scheduled runs + tool usage */}
      <div className="mt-4 flex w-full flex-col gap-3 xl:flex-row">
        <Card
          variant="subtle"
          padding="lg"
          className="h-[345px] w-full overflow-hidden xl:w-1/2"
        >
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.analytics.scheduledRuns')}
          />
          <div className="relative h-[245px] w-full">
            <div
              id="legend-container-4"
              className="flex flex-row items-center justify-end"
            ></div>
            {loadingSchedules ? (
              <SkeletonLoader count={1} component={'analysis'} />
            ) : (
              <AnalyticsChart
                data={{
                  labels: Object.keys(scheduleData || {}).map((item) =>
                    formatDate(item),
                  ),
                  datasets: [
                    {
                      label: t('settings.analytics.completed'),
                      data: Object.values(scheduleData || {}).map(
                        (item) => item.completed,
                      ),
                      backgroundColor: palette.success,
                    },
                    {
                      label: t('settings.analytics.failed'),
                      data: Object.values(scheduleData || {}).map(
                        (item) => item.failed,
                      ),
                      backgroundColor: palette.destructive,
                    },
                    {
                      label: t('settings.analytics.skipped'),
                      data: Object.values(scheduleData || {}).map(
                        (item) => item.skipped,
                      ),
                      backgroundColor: palette.warning,
                    },
                  ],
                }}
                legendID="legend-container-4"
                maxTicksLimitInX={8}
                gridColor={palette.border}
                tickColor={palette.mutedForeground}
                isStacked={true}
              />
            )}
          </div>
        </Card>

        <Card
          variant="subtle"
          padding="lg"
          className="h-[345px] w-full overflow-hidden xl:w-1/2"
        >
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.analytics.toolUsage')}
          />
          <div className="relative h-[245px] w-full">
            <div
              id="legend-container-5"
              className="flex flex-row items-center justify-end"
            ></div>
            {loadingTools ? (
              <SkeletonLoader count={1} component={'analysis'} />
            ) : (
              <AnalyticsChart
                data={{
                  labels: (toolsData || []).map((tool) => tool.tool_name),
                  datasets: [
                    {
                      label: t('settings.analytics.successful'),
                      data: (toolsData || []).map(
                        (tool) => tool.calls - tool.failures,
                      ),
                      backgroundColor: palette.success,
                    },
                    {
                      label: t('settings.analytics.failed'),
                      data: (toolsData || []).map((tool) => tool.failures),
                      backgroundColor: palette.destructive,
                    },
                  ],
                }}
                legendID="legend-container-5"
                maxTicksLimitInX={8}
                gridColor={palette.border}
                tickColor={palette.mutedForeground}
                isStacked={true}
              />
            )}
          </div>
        </Card>
      </div>

      {/* Feedback Analytics */}
      <div className="mt-4 flex w-full flex-col gap-3">
        <Card
          variant="subtle"
          padding="lg"
          className="h-[345px] w-full overflow-hidden"
        >
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.analytics.userFeedback')}
          />
          <div className="relative h-[245px] w-full">
            <div
              id="legend-container-3"
              className="flex flex-row items-center justify-end"
            ></div>
            {loadingFeedback ? (
              <SkeletonLoader count={1} component={'analysis'} />
            ) : (
              <AnalyticsChart
                data={{
                  labels: Object.keys(feedbackData || {}).map((item) =>
                    formatDate(item),
                  ),
                  datasets: [
                    {
                      label: t('settings.analytics.positiveFeedback'),
                      data: Object.values(feedbackData || {}).map(
                        (item) => item.positive,
                      ),
                      backgroundColor: palette.success,
                    },
                    {
                      label: t('settings.analytics.negativeFeedback'),
                      data: Object.values(feedbackData || {}).map(
                        (item) => item.negative,
                      ),
                      backgroundColor: palette.destructive,
                    },
                  ],
                }}
                legendID="legend-container-3"
                maxTicksLimitInX={8}
                gridColor={palette.border}
                tickColor={palette.mutedForeground}
                isStacked={false}
              />
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

type AnalyticsChartProps = {
  data: ChartData<'bar'>;
  legendID: string;
  maxTicksLimitInX: number;
  isStacked: boolean;
  /** Grid lines and axis borders (`--border`). */
  gridColor: string;
  /** Axis tick labels and legend text (`--muted-foreground`). */
  tickColor: string;
};

function AnalyticsChart({
  data,
  legendID,
  maxTicksLimitInX,
  isStacked,
  gridColor,
  tickColor,
}: AnalyticsChartProps) {
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
        // The HTML legend copies each item's fontColor, which is this.
        labels: { color: tickColor },
      },
      htmlLegend: {
        containerID: legendID,
      },
    },
    scales: {
      x: {
        grid: {
          lineWidth: 0.2,
          color: gridColor,
        },
        border: {
          width: 0.2,
          color: gridColor,
        },
        ticks: {
          maxTicksLimit: maxTicksLimitInX,
          color: tickColor,
        },
        stacked: isStacked,
      },
      y: {
        grid: {
          lineWidth: 0.2,
          color: gridColor,
        },
        border: {
          width: 0.2,
          color: gridColor,
        },
        ticks: {
          color: tickColor,
        },
        stacked: isStacked,
      },
    },
  };
  return (
    <Bar
      options={options}
      plugins={[htmlLegendPlugin]}
      data={{
        ...data,
        datasets: data.datasets.map((dataset) => ({
          ...dataset,
          hoverBackgroundColor:
            typeof dataset.backgroundColor === 'string'
              ? hoverColor(dataset.backgroundColor)
              : dataset.backgroundColor,
        })),
      }}
    />
  );
}
