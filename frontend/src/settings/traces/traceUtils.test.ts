import { describe, expect, it } from 'vitest';

import { TraceSpan } from '../types';
import {
  barGeometry,
  buildSpanRows,
  formatDurationMs,
  formatTokens,
  spanHeadline,
  traceTotalMs,
} from './traceUtils';

const span = (overrides: Partial<TraceSpan>): TraceSpan => ({
  id: 's',
  parent_id: null,
  kind: 'llm',
  name: 'chat m',
  status: 'ok',
  offset_ms: 0,
  duration_ms: 10,
  attributes: {},
  ...overrides,
});

describe('buildSpanRows', () => {
  it('orders depth-first by start offset with depths', () => {
    const rows = buildSpanRows([
      span({ id: 'llm2', parent_id: 'agent', offset_ms: 50 }),
      span({ id: 'agent', kind: 'agent', offset_ms: 5, duration_ms: 100 }),
      span({ id: 'retrieval', kind: 'retrieval', offset_ms: 0 }),
      span({ id: 'tool', kind: 'tool', parent_id: 'agent', offset_ms: 20 }),
      span({ id: 'inner', parent_id: 'tool', offset_ms: 21 }),
    ]);
    expect(rows.map((r) => [r.span.id, r.depth])).toEqual([
      ['retrieval', 0],
      ['agent', 0],
      ['tool', 1],
      ['inner', 2],
      ['llm2', 1],
    ]);
  });

  it('treats spans whose parent is missing as roots', () => {
    const rows = buildSpanRows([span({ id: 'a', parent_id: 'gone' })]);
    expect(rows).toHaveLength(1);
    expect(rows[0].depth).toBe(0);
  });

  it('marks rows that have children', () => {
    const rows = buildSpanRows([
      span({ id: 'p', kind: 'agent' }),
      span({ id: 'c', parent_id: 'p' }),
    ]);
    expect(rows[0].hasChildren).toBe(true);
    expect(rows[1].hasChildren).toBe(false);
  });
});

describe('traceTotalMs', () => {
  it('uses the larger of the stored duration and the last span end', () => {
    expect(traceTotalMs(100, [span({ offset_ms: 90, duration_ms: 30 })])).toBe(
      120,
    );
    expect(traceTotalMs(500, [span({ offset_ms: 0, duration_ms: 30 })])).toBe(
      500,
    );
  });

  it('never returns zero', () => {
    expect(traceTotalMs(0, [])).toBeGreaterThan(0);
  });
});

describe('barGeometry', () => {
  it('positions a span as percentages of the total', () => {
    expect(barGeometry(span({ offset_ms: 25, duration_ms: 50 }), 100)).toEqual({
      left: 25,
      width: 50,
    });
  });

  it('keeps tiny spans visible and inside the track', () => {
    const tiny = barGeometry(span({ offset_ms: 100, duration_ms: 0 }), 100);
    expect(tiny.width).toBeGreaterThan(0);
    expect(tiny.left + tiny.width).toBeLessThanOrEqual(100);
  });
});

describe('formatDurationMs', () => {
  it.each([
    [0.4, '<1 ms'],
    [12.4, '12 ms'],
    [999, '999 ms'],
    [1234, '1.23 s'],
    [15432, '15.4 s'],
    [65000, '1m 05s'],
    [119_600, '2m 00s'],
  ])('%s -> %s', (ms, expected) => {
    expect(formatDurationMs(ms)).toBe(expected);
  });

  it('shows a dash for missing values', () => {
    expect(formatDurationMs(undefined)).toBe('—');
  });
});

describe('formatTokens', () => {
  it('abbreviates large counts', () => {
    expect(formatTokens(950)).toBe('950');
    expect(formatTokens(12345)).toBe('12.3k');
    expect(formatTokens(2_500_000)).toBe('2.5M');
  });
});

const HEADLINES: Record<string, string> = {
  'settings.logs.trace.headline.tokens': '{{input}} → {{output}} tok',
  'settings.logs.trace.headline.chunks': '{{count}} chunks',
  'settings.logs.trace.headline.hits': '{{count}} hits',
  'settings.logs.trace.headline.cached': 'cached',
};

const t = (key: string, options: Record<string, unknown> = {}) =>
  (HEADLINES[key] ?? key).replace(/\{\{(\w+)\}\}/g, (_m, name) =>
    String(options[name]),
  );

describe('spanHeadline', () => {
  it('summarises an llm span by tokens', () => {
    expect(
      spanHeadline(
        span({
          attributes: {
            'gen_ai.usage.input_tokens': 1200,
            'gen_ai.usage.output_tokens': 80,
          },
        }),
        t,
      ),
    ).toBe('1.2k → 80 tok');
  });

  it('summarises a retrieval span by chunk count', () => {
    expect(
      spanHeadline(
        span({ kind: 'retrieval', attributes: { 'docsgpt.chunk_count': 4 } }),
        t,
      ),
    ).toBe('4 chunks');
  });

  it('is empty when nothing is known', () => {
    expect(spanHeadline(span({ kind: 'step' }), t)).toBe('');
  });

  it('labels a cached llm call', () => {
    expect(
      spanHeadline(span({ attributes: { 'docsgpt.cache_hit': true } }), t),
    ).toBe('cached');
  });
});
