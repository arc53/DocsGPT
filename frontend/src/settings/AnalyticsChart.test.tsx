import { renderToStaticMarkup } from 'react-dom/server';

// The options Chart.js would get; a canvas is not needed to read them.
const bar = vi.hoisted(() => ({
  options: null as null | {
    scales: {
      y: {
        min?: number;
        max?: number;
        ticks: { stepSize?: number; callback?: (value: number) => string };
      };
    };
  },
}));
vi.mock('react-chartjs-2', () => ({
  Bar: (props: { options: NonNullable<typeof bar.options> }) => {
    bar.options = props.options;
    return null;
  },
}));

import AnalyticsChart from './AnalyticsChart';

const render = (share?: boolean) =>
  renderToStaticMarkup(
    <AnalyticsChart
      data={{ labels: ['a'], datasets: [{ label: 'x', data: [0.4] }] }}
      legendID="legend"
      maxTicksLimitInX={8}
      isStacked
      gridColor="#000"
      tickColor="#111"
      share={share}
    />,
  );

describe('AnalyticsChart', () => {
  it('reads shares on a 0–100% y axis in steps of 20%', () => {
    render(true);
    const { y } = bar.options!.scales;
    expect(y.min).toBe(0);
    expect(y.max).toBe(1);
    expect(y.ticks.stepSize).toBe(0.2);
    expect(y.ticks.callback!(0.4)).toBe('40%');
    expect(y.ticks.callback!(1)).toBe('100%');
  });

  it('leaves a count axis to Chart.js', () => {
    render();
    const { y } = bar.options!.scales;
    expect(y.max).toBeUndefined();
    expect(y.ticks.callback).toBeUndefined();
  });
});
