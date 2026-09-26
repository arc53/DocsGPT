import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../locale/i18n';
import type { ScheduleRun } from '../types/schedule';
import RunDetailDrawer from './RunDetailDrawer';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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

const run: ScheduleRun = {
  id: 'r1',
  schedule_id: 's1',
  user_id: 'u1',
  agent_id: 'a1',
  status: 'failed',
  scheduled_for: '2026-09-25T09:00:00Z',
  trigger_source: 'cron',
  started_at: '2026-09-25T09:00:00Z',
  finished_at: '2026-09-25T09:01:00Z',
  output: null,
  output_truncated: false,
  error: 'brave_search returned 429',
  error_type: null,
  prompt_tokens: 1120,
  generated_tokens: 84,
  created_at: '2026-09-25T09:00:00Z',
  updated_at: '2026-09-25T09:01:00Z',
};

const content = () =>
  document.querySelector<HTMLElement>('[data-slot="sheet-content"]');

describe('RunDetailDrawer', () => {
  it('opens as a right Sheet with the standard X, not a hand-rolled aside', async () => {
    await act(async () =>
      root.render(<RunDetailDrawer run={run} onClose={vi.fn()} />),
    );
    const panel = content()!;
    expect(panel).not.toBeNull();
    expect(panel.dataset.side).toBe('right');
    expect(panel.getAttribute('role')).toBe('dialog');
    expect(panel.className.split(' ')).toEqual(
      expect.arrayContaining(['bg-background', 'sm:max-w-xl']),
    );
    expect(panel.querySelector('[data-slot="sheet-title"]')!.textContent).toBe(
      'Run details',
    );
    expect(panel.querySelector('[aria-label="Close"]')).not.toBeNull();
    expect(document.querySelector('aside')).toBeNull();
  });

  it('labels come from the locale, trigger and status included', async () => {
    await act(async () =>
      root.render(<RunDetailDrawer run={run} onClose={vi.fn()} />),
    );
    const text = content()!.textContent!;
    expect(text).toContain('Scheduled for');
    expect(text).toContain('1120 prompt · 84 generated');
    expect(text).toContain('Scheduled');
    expect(text).toContain('Failed');
  });

  // L9: a code block on the sheet is a filled Card around the mono recipe.
  it('puts the error on a filled Card so it shows on the sheet', async () => {
    await act(async () =>
      root.render(<RunDetailDrawer run={run} onClose={vi.fn()} />),
    );
    const pre = content()!.querySelector('pre')!;
    const card = pre.parentElement!;
    expect(card.getAttribute('data-slot')).toBe('card');
    expect(card.getAttribute('data-variant')).toBe('filled');
    expect(card.className.split(' ')).toContain('bg-muted');
    expect(card.className.split(' ')).not.toContain('bg-background');
    expect(pre.className.split(' ')).toEqual(
      expect.arrayContaining([
        'font-mono',
        'text-xs',
        'whitespace-pre-wrap',
        'wrap-break-word',
      ]),
    );
  });

  // Decisions 63a / 63b: the title is the default SheetTitle; the Error
  // heading is a destructive xs sub-heading.
  it('uses the default sheet title and an xs destructive error heading', async () => {
    await act(async () =>
      root.render(<RunDetailDrawer run={run} onClose={vi.fn()} />),
    );
    const title = content()!.querySelector('[data-slot="sheet-title"]')!;
    expect(title.className.split(' ')).toEqual(
      expect.arrayContaining(['text-xl', 'leading-tight', 'font-semibold']),
    );
    expect(title.className).not.toContain('text-lg');
    const error = content()!.querySelector('h3')!;
    expect(error.textContent).toBe('Error');
    expect(error.className.split(' ')).toEqual(
      expect.arrayContaining(['text-destructive', 'text-sm', 'font-semibold']),
    );
  });

  it('closes from the X', async () => {
    const onClose = vi.fn();
    await act(async () =>
      root.render(<RunDetailDrawer run={run} onClose={onClose} />),
    );
    await act(async () =>
      content()!
        .querySelector<HTMLButtonElement>('[aria-label="Close"]')!
        .click(),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it('renders nothing without a run', async () => {
    await act(async () =>
      root.render(<RunDetailDrawer run={null} onClose={vi.fn()} />),
    );
    expect(content()).toBeNull();
  });
});
