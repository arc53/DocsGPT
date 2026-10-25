import { renderToStaticMarkup } from 'react-dom/server';

// The options Chart.js would get; a canvas is not needed to read them.
const bar = vi.hoisted(() => ({
  options: null as null | {
    interaction?: { mode: string; intersect: boolean };
    plugins: { tooltip: { filter?: (item: { raw: unknown }) => boolean } };
    scales: {
      x: { ticks: { maxRotation?: number } };
      y: {
        grid: { color: unknown };
        ticks: { precision?: number; callback?: (value: number) => string };
      };
    };
  },
  plugins: [] as unknown[],
}));
vi.mock('react-chartjs-2', () => ({
  Bar: (props: {
    options: NonNullable<typeof bar.options>;
    plugins: unknown[];
  }) => {
    bar.options = props.options;
    bar.plugins = props.plugins;
    return null;
  },
}));

import AnalyticsChart from './AnalyticsChart';

const render = (
  props: Partial<{
    columnTooltip: boolean;
    diverging: boolean;
    legendID: string;
  }> = {},
) =>
  renderToStaticMarkup(
    <AnalyticsChart
      data={{ labels: ['a'], datasets: [{ label: 'x', data: [3] }] }}
      maxTicksLimitInX={8}
      isStacked
      gridColor="#000"
      tickColor="#111"
      {...props}
    />,
  );

describe('AnalyticsChart', () => {
  it('leaves the tooltip, the axes and the legend to Chart.js by default', () => {
    render({ legendID: 'legend' });
    const { x, y } = bar.options!.scales;
    expect(bar.options!.interaction).toBeUndefined();
    expect(bar.options!.plugins.tooltip.filter).toBeUndefined();
    expect(x.ticks.maxRotation).toBeUndefined();
    expect(y.ticks.precision).toBeUndefined();
    expect(y.ticks.callback).toBeUndefined();
    expect(bar.plugins).toHaveLength(1);
  });

  it('draws no HTML legend without a container', () => {
    render();
    expect(bar.plugins).toHaveLength(0);
  });

  it('lists a whole column in one tooltip, skipping empty series, with level labels', () => {
    render({ columnTooltip: true });
    expect(bar.options!.interaction).toEqual({
      mode: 'index',
      intersect: false,
    });
    const { filter } = bar.options!.plugins.tooltip;
    expect(filter!({ raw: 0 })).toBe(false);
    expect(filter!({ raw: -0.4 })).toBe(true);
    expect(bar.options!.scales.x.ticks.maxRotation).toBe(0);
    expect(bar.options!.scales.y.ticks.precision).toBe(0);
  });

  it('reads a diverging axis as counts either side of a marked zero line', () => {
    render({ diverging: true });
    const { y } = bar.options!.scales;
    expect(y.ticks.callback!(-3)).toBe('3');
    expect(y.ticks.callback!(2)).toBe('2');
    const color = y.grid.color as (context: {
      tick?: { value: number };
    }) => string;
    expect(color({ tick: { value: 0 } })).toBe('#111');
    expect(color({ tick: { value: 2 } })).toBe('#000');
  });
});
