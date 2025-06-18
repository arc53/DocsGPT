import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Title,
  Tooltip,
} from 'chart.js';
import { useEffect, useState } from 'react';
import { Bar } from 'react-chartjs-2';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Dropdown from '../components/Dropdown';
import SkeletonLoader from '../components/SkeletonLoader';
import { useLoaderState } from '../hooks';
import { selectToken } from '../preferences/preferenceSlice';
import { htmlLegendPlugin } from '../utils/chartUtils';
import { formatDate } from '../utils/dateTimeUtils';

import type { ChartData } from 'chart.js';
ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
);

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

  const [messagesData, setMessagesData] = useState<Record<
    string,
    number
  > | null>(null);
  const [tokenUsageData, setTokenUsageData] = useState<Record<
    string,
    number
  > | null>(null);
  const [feedbackData, setFeedbackData] = useState<Record<
    string,
    { positive: number; negative: number }
  > | null>(null);
  const [messagesFilter, setMessagesFilter] = useState<{
    label: string;
    value: string;
  }>({
    label: t('settings.analytics.filterOptions.last30Days'),
    value: 'last_30_days',
  });
  const [tokenUsageFilter, setTokenUsageFilter] = useState<{
    label: string;
    value: string;
  }>({
    label: t('settings.analytics.filterOptions.last30Days'),
    value: 'last_30_days',
  });
  const [feedbackFilter, setFeedbackFilter] = useState<{
    label: string;
    value: string;
  }>({
    label: t('settings.analytics.filterOptions.last30Days'),
    value: 'last_30_days',
  });

  const [loadingMessages, setLoadingMessages] = useLoaderState(true);
  const [loadingTokens, setLoadingTokens] = useLoaderState(true);
  const [loadingFeedback, setLoadingFeedback] = useLoaderState(true);

  const fetchMessagesData = async (agent_id?: string, filter?: string) => {
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
      setMessagesData(data.messages);
    } catch (error) {
      console.error(error);
    } finally {
      setLoadingMessages(false);
    }
  };

  const fetchTokenData = async (agent_id?: string, filter?: string) => {
    setLoadingTokens(true);
    try {
      const response = await userService.getTokenAnalytics(
        {
          api_key_id: agent_id,
          filter_option: filter,
        },
        token,
      );
      if (!response.ok) throw new Error('Failed to fetch analytics data');
      const data = await response.json();
      setTokenUsageData(data.token_usage);
    } catch (error) {
      console.error(error);
    } finally {
      setLoadingTokens(false);
    }
  };

  const fetchFeedbackData = async (agent_id?: string, filter?: string) => {
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
      setFeedbackData(data.feedback);
    } catch (error) {
      console.error(error);
    } finally {
      setLoadingFeedback(false);
    }
  };

  useEffect(() => {
    const id = agentId;
    const filter = messagesFilter;
    fetchMessagesData(id, filter?.value);
  }, [agentId, messagesFilter]);

  useEffect(() => {
    const id = agentId;
    const filter = tokenUsageFilter;
    fetchTokenData(id, filter?.value);
  }, [agentId, tokenUsageFilter]);

  useEffect(() => {
    const id = agentId;
    const filter = feedbackFilter;
    fetchFeedbackData(id, filter?.value);
  }, [agentId, feedbackFilter]);
  return (
    <div className="mt-12">
      {/* Messages Analytics */}
      <div className="mt-8 flex w-full flex-col gap-3 [@media(min-width:1080px)]:flex-row">
        <div className="h-[345px] w-full overflow-hidden rounded-2xl border border-silver px-6 py-5 dark:border-silver/40 [@media(min-width:1080px)]:w-1/2">
          <div className="flex flex-row items-center justify-start gap-3">
            <p className="font-bold text-jet dark:text-bright-gray">
              {t('settings.analytics.messages')}
            </p>
            <Dropdown
              size="w-[125px]"
              options={filterOptions}
              placeholder={t('settings.analytics.filterPlaceholder')}
              onSelect={(selectedOption: { label: string; value: string }) => {
                setMessagesFilter(selectedOption);
              }}
              selectedValue={messagesFilter ?? null}
              rounded="3xl"
              border="border"
              contentSize="text-sm"
            />
          </div>
          <div className="relative mt-px h-[245px] w-full">
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
                      backgroundColor: '#7D54D1',
                    },
                  ],
                }}
                legendID="legend-container-1"
                maxTicksLimitInX={8}
                isStacked={false}
              />
            )}
          </div>
        </div>

        {/* Token Usage Analytics */}
        <div className="h-[345px] w-full overflow-hidden rounded-2xl border border-silver px-6 py-5 dark:border-silver/40 [@media(min-width:1080px)]:w-1/2">
          <div className="flex flex-row items-center justify-start gap-3">
            <p className="font-bold text-jet dark:text-bright-gray">
              {t('settings.analytics.tokenUsage')}
            </p>
            <Dropdown
              size="w-[125px]"
              options={filterOptions}
              placeholder={t('settings.analytics.filterPlaceholder')}
              onSelect={(selectedOption: { label: string; value: string }) => {
                setTokenUsageFilter(selectedOption);
              }}
              selectedValue={tokenUsageFilter ?? null}
              rounded="3xl"
              border="border"
              contentSize="text-sm"
            />
          </div>
          <div className="relative mt-px h-[245px] w-full">
            <div
              id="legend-container-2"
              className="flex flex-row items-center justify-end"
            ></div>
            {loadingTokens ? (
              <SkeletonLoader count={1} component={'analysis'} />
            ) : (
              <AnalyticsChart
                data={{
                  labels: Object.keys(tokenUsageData || {}).map((item) =>
                    formatDate(item),
                  ),
                  datasets: [
                    {
                      label: t('settings.analytics.tokenUsage'),
                      data: Object.values(tokenUsageData || {}),
                      backgroundColor: '#7D54D1',
                    },
                  ],
                }}
                legendID="legend-container-2"
                maxTicksLimitInX={8}
                isStacked={false}
              />
            )}
          </div>
        </div>
      </div>

      {/* Feedback Analytics */}
      <div className="mt-8 flex w-full flex-col gap-3">
        <div className="h-[345px] w-full overflow-hidden rounded-2xl border border-silver px-6 py-5 dark:border-silver/40">
          <div className="flex flex-row items-center justify-start gap-3">
            <p className="font-bold text-jet dark:text-bright-gray">
              {t('settings.analytics.userFeedback')}
            </p>
            <Dropdown
              size="w-[125px]"
              options={filterOptions}
              placeholder={t('settings.analytics.filterPlaceholder')}
              onSelect={(selectedOption: { label: string; value: string }) => {
                setFeedbackFilter(selectedOption);
              }}
              selectedValue={feedbackFilter ?? null}
              rounded="3xl"
              border="border"
              contentSize="text-sm"
            />
          </div>
          <div className="relative mt-px h-[245px] w-full">
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
                      backgroundColor: '#7D54D1',
                    },
                    {
                      label: t('settings.analytics.negativeFeedback'),
                      data: Object.values(feedbackData || {}).map(
                        (item) => item.negative,
                      ),
                      backgroundColor: '#FF6384',
                    },
                  ],
                }}
                legendID="legend-container-3"
                maxTicksLimitInX={8}
                isStacked={false}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

type AnalyticsChartProps = {
  data: ChartData<'bar'>;
  legendID: string;
  maxTicksLimitInX: number;
  isStacked: boolean;
};

function AnalyticsChart({
  data,
  legendID,
  maxTicksLimitInX,
  isStacked,
}: AnalyticsChartProps) {
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
      },
      htmlLegend: {
        containerID: legendID,
      },
    },
    scales: {
      x: {
        grid: {
          lineWidth: 0.2,
          color: '#C4C4C4',
        },
        border: {
          width: 0.2,
          color: '#C4C4C4',
        },
        ticks: {
          maxTicksLimit: maxTicksLimitInX,
        },
        stacked: isStacked,
      },
      y: {
        grid: {
          lineWidth: 0.2,
          color: '#C4C4C4',
        },
        border: {
          width: 0.2,
          color: '#C4C4C4',
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
          hoverBackgroundColor: `${dataset.backgroundColor}CC`, // 80% opacity
        })),
      }}
    />
  );
}
