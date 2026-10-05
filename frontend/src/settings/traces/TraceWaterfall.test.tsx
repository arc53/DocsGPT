import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) =>
      typeof fallback === 'string' ? fallback : key,
  }),
}));
vi.mock('./TraceSpanDetails', () => ({ default: () => null }));

import type { Trace } from '../types';
import TraceWaterfall from './TraceWaterfall';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const trace = {
  id: 't-1',
  source: 'chat',
  status: 'ok',
  started_at: '2026-09-30T14:02:11Z',
  duration_ms: 2000,
  span_count: 2,
  dropped_spans: 0,
  summary: {},
  spans: [
    {
      id: 's-1',
      parent_id: null,
      kind: 'llm',
      name: 'gpt-5.1 · plan',
      status: 'ok',
      offset_ms: 0,
      duration_ms: 1000,
      attributes: {},
    },
    {
      id: 's-2',
      parent_id: null,
      kind: 'tool',
      name: 'read_document',
      status: 'ok',
      offset_ms: 1000,
      duration_ms: 800,
      attributes: {},
    },
  ],
} as unknown as Trace;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe('TraceWaterfall selection', () => {
  it('fills the selected row with secondary, not the hover accent', async () => {
    await act(async () => root.render(<TraceWaterfall trace={trace} />));
    const select = container.querySelector<HTMLButtonElement>(
      'button[aria-pressed]',
    )!;
    await act(async () => select.click());
    const item = container.querySelector('[role="treeitem"]')!;
    expect(item.getAttribute('aria-selected')).toBe('true');
    const row = item.firstElementChild as HTMLElement;
    expect(row.className).toContain('bg-secondary');
    expect(row.className).not.toContain('bg-accent');
  });
});
