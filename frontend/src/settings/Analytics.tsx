import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Title,
  Tooltip,
} from 'chart.js';
import React from 'react';
import { Bar } from 'react-chartjs-2';

import userService from '../api/services/userService';
import Dropdown from '../components/Dropdown';
import { htmlLegendPlugin } from '../utils/chartUtils';
import { formatDate } from '../utils/dateTimeUtils';
import { APIKeyData } from './types';

import type { ChartData } from 'chart.js';
ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
);

const filterOptions = [
  { label: 'Hour', value: 'last_hour' },
  { label: '24 Hours', value: 'last_24_hour' },
  { label: '7 Days', value: 'last_7_days' },
  { label: '15 Days', value: 'last_15_days' },
  { label: '30 Days', value: 'last_30_days' },
];

export default function Analytics() {
  const [messagesData, setMessagesData] = React.useState<Record<
    string,
    number
  > | null>(null);
  const [tokenUsageData, setTokenUsageData] = React.useState<Record<
    string,
    number
  > | null>(null);
  const [feedbackData, setFeedbackData] = React.useState<Record<
    string,
    {
      positive: number;
      negative: number;
    }
  > | null>(null);
  const [chatbots, setChatbots] = React.useState<APIKeyData[]>([]);
  const [selectedChatbot, setSelectedChatbot] =
    React.useState<APIKeyData | null>();
  const [messagesFilter, setMessagesFilter] = React.useState<{
    label: string;
    value: string;
  }>({ label: '30 Days', value: 'last_30_days' });
  const [tokenUsageFilter, setTokenUsageFilter] = React.useState<{
    label: string;
    value: string;
  }>({ label: '30 Days', value: 'last_30_days' });
  const [feedbackFilter, setFeedbackFilter] = React.useState<{
    label: string;
    value: string;
  }>({ label: '30 Days', value: 'last_30_days' });

  const fetchChatbots = async () => {
    try {
      const response = await userService.getAPIKeys();
      if (!response.ok) {
        throw new Error('Failed to fetch Chatbots');
      }
      const chatbots = await response.json();
      setChatbots(chatbots);
    } catch (error) {
      console.error(error);
    }
  };

  const fetchMessagesData = async (chatbot_id?: string, filter?: string) => {
    try {
      const response = await userService.getMessageAnalytics({
        api_key_id: chatbot_id,
        filter_option: filter,
      });
      if (!response.ok) {
        throw new Error('Failed to fetch analytics data');
      }
      const data = await response.json();
      setMessagesData(data.messages);
    } catch (error) {
      console.error(error);
    }
  };

  const fetchTokenData = async (chatbot_id?: string, filter?: string) => {
    try {
      const response = await userService.getTokenAnalytics({
        api_key_id: chatbot_id,
        filter_option: filter,
      });
      if (!response.ok) {
        throw new Error('Failed to fetch analytics data');
      }
      const data = await response.json();
      setTokenUsageData(data.token_usage);
    } catch (error) {
      console.error(error);
    }
  };

  const fetchFeedbackData = async (chatbot_id?: string, filter?: string) => {
    try {
      const response = await userService.getFeedbackAnalytics({
        api_key_id: chatbot_id,
        filter_option: filter,
      });
      if (!response.ok) {
        throw new Error('Failed to fetch analytics data');
      }
      const data = await response.json();
      setFeedbackData(data.feedback);
    } catch (error) {
      console.error(error);
    }
  };

  React.useEffect(() => {
    fetchChatbots();
  }, []);

  React.useEffect(() => {
    const id = selectedChatbot?.id;
    const filter = messagesFilter;
    fetchMessagesData(id, filter?.value);
  }, [selectedChatbot, messagesFilter]);

  React.useEffect(() => {
    const id = selectedChatbot?.id;
    const filter = tokenUsageFilter;
    fetchTokenData(id, filter?.value);
  }, [selectedChatbot, tokenUsageFilter]);

  React.useEffect(() => {
    const id = selectedChatbot?.id;
    const filter = feedbackFilter;
    fetchFeedbackData(id, filter?.value);
  }, [selectedChatbot, feedbackFilter]);
  return (
    <div className="mt-12">
      <div className="flex flex-col items-start">
        <div className="flex flex-col gap-3">
          <p className="font-bold text-jet dark:text-bright-gray">
            Filter by chatbot
          </p>
          <Dropdown
            size="w-[55vw] sm:w-[360px]"
            options={[
              ...chatbots.map((chatbot) => ({
                label: chatbot.name,
                value: chatbot.id,
              })),
              { label: 'None', value: '' },
            ]}
            placeholder="Select chatbot"
            onSelect={(chatbot: { label: string; value: string }) => {
              setSelectedChatbot(
                chatbots.find((item) => item.id === chatbot.value),
              );
            }}
            selectedValue={
              (selectedChatbot && {
                label: selectedChatbot.name,
                value: selectedChatbot.id,
              }) ||
              null
            }
            rounded="3xl"
            border="border"
          />
        </div>
        <div className="mt-8 w-full flex flex-col sm:flex-row gap-3">
          <div className="h-[345px] sm:w-1/2 w-full px-6 py-5 border rounded-2xl border-silver dark:border-silver/40">
            <div className="flex flex-row items-center justify-start gap-3">
              <p className="font-bold text-jet dark:text-bright-gray">
                Messages
              </p>
              <Dropdown
                size="w-[125px]"
                options={filterOptions}
                placeholder="Filter"
                onSelect={(selectedOption: {
                  label: string;
                  value: string;
                }) => {
                  setMessagesFilter(selectedOption);
                }}
                selectedValue={messagesFilter ?? null}
                rounded="3xl"
                border="border"
                contentSize="text-sm"
              />
            </div>
            <div className="mt-px relative h-[245px] w-full">
              <div
                id="legend-container-1"
                className="flex flex-row items-center justify-end"
              ></div>
              <AnalyticsChart
                data={{
                  labels: Object.keys(messagesData || {}).map((item) =>
                    formatDate(item),
                  ),
                  datasets: [
                    {
                      label: 'Messages',
                      data: Object.values(messagesData || {}),
                      backgroundColor: '#7D54D1',
                    },
                  ],
                }}
                legendID="legend-container-1"
                maxTicksLimitInX={8}
                isStacked={false}
              />
            </div>
          </div>
          <div className="h-[345px] sm:w-1/2 w-full px-6 py-5 border rounded-2xl border-silver dark:border-silver/40">
            <div className="flex flex-row items-center justify-start gap-3">
              <p className="font-bold text-jet dark:text-bright-gray">
                Token Usage
              </p>
              <Dropdown
                size="w-[125px]"
                options={filterOptions}
                placeholder="Filter"
                onSelect={(selectedOption: {
                  label: string;
                  value: string;
                }) => {
                  setTokenUsageFilter(selectedOption);
                }}
                selectedValue={tokenUsageFilter ?? null}
                rounded="3xl"
                border="border"
                contentSize="text-sm"
              />
            </div>
            <div className="mt-px relative h-[245px] w-full">
              <div
                id="legend-container-2"
                className="flex flex-row items-center justify-end"
              ></div>
              <AnalyticsChart
                data={{
                  labels: Object.keys(tokenUsageData || {}).map((item) =>
                    formatDate(item),
                  ),
                  datasets: [
                    {
                      label: 'Tokens',
                      data: Object.values(tokenUsageData || {}),
                      backgroundColor: '#7D54D1',
                    },
                  ],
                }}
                legendID="legend-container-2"
                maxTicksLimitInX={8}
                isStacked={false}
              />
            </div>
          </div>
        </div>
        <div className="mt-8 w-full">
          <div className="h-[345px] w-full px-6 py-5 border rounded-2xl border-silver dark:border-silver/40">
            <div className="flex flex-row items-center justify-start gap-3">
              <p className="font-bold text-jet dark:text-bright-gray">
                User Feedback
              </p>
              <Dropdown
                size="w-[125px]"
                options={filterOptions}
                placeholder="Filter"
                onSelect={(selectedOption: {
                  label: string;
                  value: string;
                }) => {
                  setFeedbackFilter(selectedOption);
                }}
                selectedValue={feedbackFilter ?? null}
                rounded="3xl"
                border="border"
                contentSize="text-sm"
              />
            </div>
            <div className="mt-px relative h-[245px] w-full">
              <div
                id="legend-container-3"
                className="flex flex-row items-center justify-end"
              ></div>
              <AnalyticsChart
                data={{
                  labels: Object.keys(feedbackData || {}).map((item) =>
                    formatDate(item),
                  ),
                  datasets: [
                    {
                      label: 'Positive',
                      data: Object.values(feedbackData || {}).map(
                        (item) => item.positive,
                      ),
                      backgroundColor: '#8BD154',
                    },
                    {
                      label: 'Negative',
                      data: Object.values(feedbackData || {}).map(
                        (item) => item.negative,
                      ),
                      backgroundColor: '#D15454',
                    },
                  ],
                }}
                legendID="legend-container-3"
                maxTicksLimitInX={10}
                isStacked={true}
              />
            </div>
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
  return <Bar options={options} plugins={[htmlLegendPlugin]} data={data} />;
}
