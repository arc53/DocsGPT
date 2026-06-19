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

import { htmlLegendPlugin } from '../utils/chartUtils';

import type { ChartData } from 'chart.js';

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
);

// Chart.js renders to a canvas and can't read CSS variables, so resolve the
// theme color to a concrete string at render time (mirrors settings/Analytics).
function readCssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.body).getPropertyValue(name).trim();
  return value || fallback;
}

export function usageColors(): { prompt: string; generated: string } {
  return {
    // Violet + pink is the established DocsGPT 2-series pairing (Analytics uses
    // --primary + SERIES_COLORS[0]); far more colorblind-separable than blue.
    prompt: readCssVar('--primary', '#7D54D1'),
    generated: '#FF6384',
  };
}

function compactTick(value: number | string): string {
  const n = typeof value === 'number' ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(n);
}

type UsageChartProps = {
  data: ChartData<'bar'>;
  legendID: string;
  maxTicksLimitInX?: number;
};

export default function UsageChart({
  data,
  legendID,
  maxTicksLimitInX = 8,
}: UsageChartProps) {
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      htmlLegend: { containerID: legendID },
    },
    scales: {
      x: {
        grid: { lineWidth: 0.2, color: '#C4C4C4' },
        border: { width: 0.2, color: '#C4C4C4' },
        ticks: { maxTicksLimit: maxTicksLimitInX },
        stacked: true,
      },
      y: {
        grid: { lineWidth: 0.2, color: '#C4C4C4' },
        border: { width: 0.2, color: '#C4C4C4' },
        ticks: { callback: compactTick },
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
          hoverBackgroundColor: `${dataset.backgroundColor}CC`,
        })),
      }}
    />
  );
}
