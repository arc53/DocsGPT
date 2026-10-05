import { TraceSpan } from '../types';

export type SpanRow = {
  span: TraceSpan;
  depth: number;
  hasChildren: boolean;
};

/**
 * Flatten a trace's spans into display rows: depth-first, children in start
 * order under their parent. A span whose parent is missing (dropped by the
 * span cap) is shown at the top level rather than hidden.
 */
export function buildSpanRows(spans: TraceSpan[]): SpanRow[] {
  const ids = new Set(spans.map((s) => s.id));
  const children = new Map<string | null, TraceSpan[]>();
  for (const span of spans) {
    const parent =
      span.parent_id && ids.has(span.parent_id) ? span.parent_id : null;
    const list = children.get(parent) ?? [];
    list.push(span);
    children.set(parent, list);
  }
  for (const list of children.values()) {
    list.sort((a, b) => a.offset_ms - b.offset_ms);
  }
  const rows: SpanRow[] = [];
  const visit = (parent: string | null, depth: number) => {
    for (const span of children.get(parent) ?? []) {
      const kids = children.get(span.id);
      rows.push({ span, depth, hasChildren: Boolean(kids?.length) });
      visit(span.id, depth + 1);
    }
  };
  visit(null, 0);
  return rows;
}

/** Width of the timeline: the stored duration, or the last span end if later. */
export function traceTotalMs(
  durationMs: number | undefined,
  spans: TraceSpan[],
): number {
  const lastEnd = spans.reduce(
    (max, s) => Math.max(max, (s.offset_ms || 0) + (s.duration_ms || 0)),
    0,
  );
  return Math.max(durationMs || 0, lastEnd, 1);
}

const MIN_BAR_PERCENT = 0.6;

/** A span's bar as left offset and width, in percent of the timeline. */
export function barGeometry(
  span: TraceSpan,
  totalMs: number,
): { left: number; width: number } {
  const total = totalMs > 0 ? totalMs : 1;
  const width = Math.max(
    ((span.duration_ms || 0) / total) * 100,
    MIN_BAR_PERCENT,
  );
  const left = Math.min(
    Math.max(((span.offset_ms || 0) / total) * 100, 0),
    100 - width,
  );
  return { left: round(left), width: round(width) };
}

function round(n: number): number {
  return Math.round(n * 100) / 100;
}

/** Human duration: `<1 ms`, `12 ms`, `1.23 s`, `15.4 s`, `1m 05s`. */
export function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—';
  if (ms < 1) return '<1 ms';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 10_000) return `${(ms / 1000).toFixed(2)} s`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  // Round to whole seconds before splitting, so 119.6 s reads 2m 00s, not 1m 60s.
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
}

/** Token counts abbreviated: `950`, `12.3k`, `2.5M`. */
export function formatTokens(n: number | null | undefined): string {
  const value = n ?? 0;
  if (value >= 1_000_000) return `${trimZero((value / 1_000_000).toFixed(1))}M`;
  if (value >= 1000) return `${trimZero((value / 1000).toFixed(1))}k`;
  return String(Math.round(value));
}

function trimZero(s: string): string {
  return s.endsWith('.0') ? s.slice(0, -2) : s;
}

function num(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value)
    ? value
    : undefined;
}

type Translate = (key: string, options?: Record<string, unknown>) => string;

/**
 * A short, kind-specific summary shown next to a span's name, e.g.
 * `1.2k → 80 tok` for an LLM call or `4 chunks` for a retrieval.
 */
export function spanHeadline(span: TraceSpan, t: Translate): string {
  const a = span.attributes || {};
  switch (span.kind) {
    case 'llm': {
      if (a['docsgpt.cache_hit'])
        return t('settings.logs.trace.headline.cached');
      const input = num(a['gen_ai.usage.input_tokens']);
      const output = num(a['gen_ai.usage.output_tokens']);
      if (input === undefined && output === undefined) return '';
      return t('settings.logs.trace.headline.tokens', {
        input: formatTokens(input),
        output: formatTokens(output),
      });
    }
    case 'retrieval':
    case 'rerank': {
      const chunks = num(a['docsgpt.chunk_count'] ?? a['docsgpt.kept_count']);
      return chunks === undefined
        ? ''
        : t('settings.logs.trace.headline.chunks', { count: chunks });
    }
    case 'search': {
      const hits = num(a['docsgpt.candidate_count']);
      return hits === undefined
        ? ''
        : t('settings.logs.trace.headline.hits', { count: hits });
    }
    default:
      return '';
  }
}
