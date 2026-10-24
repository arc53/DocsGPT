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
import { formatCount } from '../utils/dateTimeUtils';

import type {
  ChartData,
  ScriptableScaleContext,
  TooltipOptions,
} from 'chart.js';

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
  /** The HTML legend's container; without one the caller names the series itself. */
  legendID?: string;
  maxTicksLimitInX: number;
  isStacked: boolean;
  /** Grid lines and axis borders (`--border`). */
  gridColor: string;
  /** Axis tick labels and legend text (`--muted-foreground`). */
  tickColor: string;
  /** Chart.js tooltip callbacks, for a label or footer of the chart's own. */
  tooltipCallbacks?: Partial<TooltipOptions<'bar'>['callbacks']>;
  /**
   * One tooltip per column listing each of its series that has a value, and
   * level x labels (short ones, such as "13–19 Oct", that never need turning).
   */
  columnTooltip?: boolean;
  /**
   * Series drawn below zero (negative values) read as counts too: the y axis
   * shows absolute values and the zero line is drawn in the tick colour.
   */
  diverging?: boolean;
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
  columnTooltip = false,
  diverging = false,
}: AnalyticsChartProps) {
  const tooltip = {
    ...(tooltipCallbacks ? { callbacks: tooltipCallbacks } : {}),
    ...(columnTooltip
      ? { filter: (item: { raw: unknown }) => Number(item.raw) !== 0 }
      : {}),
  };
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    ...(columnTooltip
      ? { interaction: { mode: 'index' as const, intersect: false } }
      : {}),
    plugins: {
      legend: {
        display: false,
        // The HTML legend copies each item's fontColor, which is this.
        labels: { color: tickColor },
      },
      htmlLegend: {
        containerID: legendID,
      },
      tooltip,
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
          ...(columnTooltip ? { maxRotation: 0 } : {}),
        },
        stacked: isStacked,
      },
      y: {
        grid: {
          lineWidth: 0.2,
          color: diverging
            ? (context: ScriptableScaleContext) =>
                context.tick?.value === 0 ? tickColor : gridColor
            : gridColor,
        },
        border: {
          width: 0.2,
          color: gridColor,
        },
        ticks: {
          color: tickColor,
          // Insight counts are sums of probabilities: whole steps only.
          ...(columnTooltip || diverging ? { precision: 0 } : {}),
          ...(diverging
            ? {
                callback: (value: number | string) =>
                  formatCount(Math.abs(Number(value))),
              }
            : {}),
        },
        stacked: isStacked,
      },
    },
  };
  return (
    <Bar
      options={options}
      plugins={legendID ? [htmlLegendPlugin] : []}
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
