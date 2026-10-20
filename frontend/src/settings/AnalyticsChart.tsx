import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Title,
  Tooltip,
} from 'chart.js';
import { Bar } from 'react-chartjs-2';

import { hoverColor, htmlLegendPlugin } from '../utils/chartUtils';
import { formatShare } from './insights/format';

import type { ChartData, TooltipOptions } from 'chart.js';

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
);

type AnalyticsChartProps = {
  data: ChartData<'bar'>;
  legendID: string;
  maxTicksLimitInX: number;
  isStacked: boolean;
  /** Grid lines and axis borders (`--border`). */
  gridColor: string;
  /** Axis tick labels and legend text (`--muted-foreground`). */
  tickColor: string;
  /** Chart.js tooltip callbacks, for a label or footer of the chart's own. */
  tooltipCallbacks?: Partial<TooltipOptions<'bar'>['callbacks']>;
  /**
   * The data are shares (0–1) of each column: the y axis reads 0–100% in
   * steps of 20%, whatever the column holds.
   */
  share?: boolean;
};

/** The Analytics bar chart: theme colours, the HTML legend and hover tints. */
export default function AnalyticsChart({
  data,
  legendID,
  maxTicksLimitInX,
  isStacked,
  gridColor,
  tickColor,
  tooltipCallbacks,
  share = false,
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
      ...(tooltipCallbacks ? { tooltip: { callbacks: tooltipCallbacks } } : {}),
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
          ...(share
            ? {
                stepSize: 0.2,
                callback: (value: number | string) =>
                  formatShare(Number(value)),
              }
            : {}),
        },
        ...(share ? { min: 0, max: 1 } : {}),
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
