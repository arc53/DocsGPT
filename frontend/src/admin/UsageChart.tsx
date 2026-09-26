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

import {
  hoverColor,
  htmlLegendPlugin,
  readChartPalette,
  type ChartPalette,
} from '../utils/chartUtils';

import type { ChartData } from 'chart.js';

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
);

/**
 * Colours for the ungrouped Prompt / Generated pair.
 *
 * Same as settings/Analytics: prompt is `chart-1` (the brand), generated is
 * `chart-2`. Chart.js renders to a canvas, so these are resolved strings.
 *
 * @param palette The resolved theme palette; read from the DOM when omitted.
 * @returns The two bar colours.
 */
export function usageColors(palette: ChartPalette = readChartPalette()): {
  prompt: string;
  generated: string;
} {
  return { prompt: palette.series[0], generated: palette.series[1] };
}

/**
 * Colour for dataset `index` of a grouped chart (by model / agent / flow).
 *
 * Groups have no meaning of their own, so they take `chart-1` to `chart-5` in
 * order (DESIGN.md, chart colours). Callers fold anything past five into
 * "Other" with `foldSeries`, so the modulo never repeats a colour in practice.
 *
 * @param index The dataset's position.
 * @param palette The resolved theme palette; read from the DOM when omitted.
 * @returns The bar colour.
 */
export function seriesColor(
  index: number,
  palette: ChartPalette = readChartPalette(),
): string {
  return palette.series[index % palette.series.length];
}

function compactTick(value: number | string): string {
  const n = typeof value === 'number' ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(n);
}

function currencyTick(value: number | string): string {
  const n = typeof value === 'number' ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return `$${new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(n)}`;
}

type UsageChartProps = {
  data: ChartData<'bar'>;
  legendID: string;
  maxTicksLimitInX?: number;
  /** Format the y axis as USD rather than a token count. */
  currency?: boolean;
  /** Grid lines and axis borders (`--border`). */
  gridColor: string;
  /** Axis tick labels and legend text (`--muted-foreground`). */
  tickColor: string;
};

export default function UsageChart({
  data,
  legendID,
  maxTicksLimitInX = 8,
  currency = false,
  gridColor,
  tickColor,
}: UsageChartProps) {
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      // The HTML legend copies each item's fontColor, which is this.
      legend: { display: false, labels: { color: tickColor } },
      htmlLegend: { containerID: legendID },
    },
    scales: {
      x: {
        grid: { lineWidth: 0.2, color: gridColor },
        border: { width: 0.2, color: gridColor },
        ticks: { maxTicksLimit: maxTicksLimitInX, color: tickColor },
        stacked: true,
      },
      y: {
        grid: { lineWidth: 0.2, color: gridColor },
        border: { width: 0.2, color: gridColor },
        ticks: {
          callback: currency ? currencyTick : compactTick,
          color: tickColor,
        },
        stacked: true,
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
