import { describe, expect, it, vi } from 'vitest';

import {
  buildUsageChart,
  cacheHitRate,
  type UsageBucket,
} from './usageChartData';

// Chart.js colors resolve against a live DOM; the shapes under test do not.
vi.mock('./UsageChart', () => ({
  seriesColor: (index: number) => `color-${index}`,
  usageColors: () => ({ prompt: 'prompt-color', generated: 'generated-color' }),
}));

const bucket = (overrides: Partial<UsageBucket>): UsageBucket => ({
  bucket: '2026-01-01',
  prompt_tokens: 100,
  generated_tokens: 20,
  cost: 1,
  cached_tokens: null,
  cache_eligible_prompt_tokens: 0,
  ...overrides,
});

describe('buildUsageChart', () => {
  it('splits prompt and generated tokens when ungrouped', () => {
    const chart = buildUsageChart([bucket({})], 'none', 'tokens');
    expect(chart.datasets.map((d) => d.label)).toEqual(['Prompt', 'Generated']);
    expect(chart.datasets[0].data).toEqual([100]);
  });

  it('plots a single series for cost', () => {
    const chart = buildUsageChart([bucket({ cost: 2.5 })], 'none', 'cost');
    expect(chart.datasets).toHaveLength(1);
    expect(chart.datasets[0].data).toEqual([2.5]);
  });

  it('gives each group its own dataset', () => {
    const chart = buildUsageChart(
      [
        bucket({ group_key: 'gpt-a' }),
        bucket({ group_key: 'gpt-b', prompt_tokens: 5, generated_tokens: 5 }),
      ],
      'model',
      'tokens',
    );
    expect(chart.datasets.map((d) => d.label)).toEqual(['gpt-a', 'gpt-b']);
    expect(chart.datasets[1].data).toEqual([10]);
  });

  it('pads a group that is missing a bucket so the axes stay aligned', () => {
    const chart = buildUsageChart(
      [
        bucket({ bucket: '2026-01-01', group_key: 'a' }),
        bucket({ bucket: '2026-01-02', group_key: 'b' }),
      ],
      'model',
      'tokens',
    );
    expect(chart.labels).toHaveLength(2);
    // 'a' has no row on the second day: a zero, not a shifted bar.
    expect(chart.datasets[0].data).toEqual([120, 0]);
    expect(chart.datasets[1].data).toEqual([0, 120]);
  });

  it('labels a group with no key rather than dropping the row', () => {
    const chart = buildUsageChart([bucket({})], 'model', 'tokens');
    expect(chart.datasets[0].label).toBe('unknown');
  });

  it('folds more than five groups into four plus Other in chart-5', () => {
    const keys = ['a', 'b', 'c', 'd', 'e', 'f', 'g'];
    const chart = buildUsageChart(
      keys.map((key, i) =>
        // 'a' is the smallest; b..e are the four largest.
        bucket({ group_key: key, prompt_tokens: i === 0 ? 1 : 100 - i * 10 }),
      ),
      'model',
      'tokens',
    );
    expect(chart.datasets.map((d) => d.label)).toEqual([
      'b',
      'c',
      'd',
      'e',
      'Other',
    ]);
    expect(chart.datasets.map((d) => d.backgroundColor)).toEqual([
      'color-0',
      'color-1',
      'color-2',
      'color-3',
      'color-4',
    ]);
    // Other sums a, f and g (prompt 1, 50, 40, plus 20 generated each).
    expect(chart.datasets[4].data).toEqual([1 + 50 + 40 + 60]);
  });

  it('handles an empty series', () => {
    const chart = buildUsageChart([], 'model', 'cost');
    expect(chart.labels).toEqual([]);
    expect(chart.datasets).toEqual([]);
  });
});

describe('cacheHitRate', () => {
  it('is unknown when no provider reported cache bins', () => {
    expect(cacheHitRate([bucket({ cached_tokens: null })])).toBeNull();
  });

  it('is unknown for an empty series', () => {
    expect(cacheHitRate([])).toBeNull();
  });

  it('divides by the prompt tokens of the reporting calls only', () => {
    // One bucket is one day, and a day mixes calls whose provider reported a
    // cache breakdown with calls whose provider did not. 50/100, not 50/200.
    const rate = cacheHitRate([
      bucket({
        prompt_tokens: 200,
        cached_tokens: 50,
        cache_eligible_prompt_tokens: 100,
      }),
    ]);
    expect(rate).toBeCloseTo(50);
  });

  it('sums across buckets', () => {
    const rate = cacheHitRate([
      bucket({
        prompt_tokens: 100,
        cached_tokens: 10,
        cache_eligible_prompt_tokens: 100,
      }),
      bucket({
        prompt_tokens: 100,
        cached_tokens: 30,
        cache_eligible_prompt_tokens: 100,
      }),
    ]);
    expect(rate).toBeCloseTo(20);
  });

  it('avoids dividing by zero eligible tokens', () => {
    expect(
      cacheHitRate([
        bucket({ prompt_tokens: 500, cache_eligible_prompt_tokens: 0 }),
      ]),
    ).toBeNull();
  });
});
