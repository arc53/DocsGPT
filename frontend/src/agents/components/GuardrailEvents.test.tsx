import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

// A stable `t`: the component lists it as an effect dependency.
vi.mock('react-i18next', () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

const events = [
  { id: '1', action: 'block', outcome: 'triggered' },
  { id: '2', action: 'redact', outcome: 'triggered' },
  { id: '3', action: 'flag', outcome: 'triggered' },
  { id: '4', action: 'flag', outcome: 'not_evaluated' },
].map((e) => ({
  ...e,
  check_name: `check-${e.id}`,
  stage: 'input',
  category: null,
  detail: '',
  created_at: '2026-09-01T00:00:00Z',
}));

// Flipped by the Retry test to make the next events fetch fail.
const fetchState = vi.hoisted(() => ({
  failNext: false,
  calls: [] as unknown[][],
}));

vi.mock('../../api/services/userService', () => ({
  default: {
    getGuardrailEvents: (...args: unknown[]) => {
      fetchState.calls.push(args);
      if (fetchState.failNext) {
        fetchState.failNext = false;
        return Promise.reject(new Error('network'));
      }
      return Promise.resolve({
        json: () => Promise.resolve({ success: true, events }),
      });
    },
    getGuardrailSummary: () =>
      Promise.resolve({
        json: () =>
          Promise.resolve({
            success: true,
            breakdown: [],
            totals: { blocked: 1, redacted: 1, flagged: 1, not_evaluated: 1 },
          }),
      }),
  },
}));

import GuardrailEvents from './GuardrailEvents';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeStore = () =>
  configureStore({ reducer: { preference: () => ({ token: null }) } });

describe('GuardrailEvents tones', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(
        <Provider store={makeStore()}>
          <GuardrailEvents agentId="a1" />
        </Provider>,
      );
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  // A3: the section lines up with Analytics and the log table on Logs.
  it('is not indented against the sections around it', () => {
    const root = document.querySelector<HTMLElement>(
      '[data-testid="guardrail-events"]',
    )!;
    expect(root.className).not.toMatch(/(^|\s)px-/);
  });

  it('colours outcome badges by meaning', () => {
    const variants = Array.from(
      container.querySelectorAll(
        '[data-testid="guardrail-events-rows"] [data-slot="badge"]',
      ),
    ).map((b) => b.getAttribute('data-variant'));
    expect(variants).toEqual(['destructive', 'info', 'warning', 'neutral']);
  });

  it('colours the stat tiles to match', () => {
    const tone = (id: string) =>
      container.querySelector(`[data-testid="${id}"] p:last-child`)?.className;
    expect(tone('guardrail-stat-blocked')).toContain('text-destructive');
    expect(tone('guardrail-stat-redacted')).toContain('text-info');
    expect(tone('guardrail-stat-flagged')).toContain('text-warning');
    expect(tone('guardrail-stat-not-evaluated')).toContain(
      'text-muted-foreground',
    );
  });

  it('renders the stat tiles as StatCards', () => {
    for (const id of [
      'guardrail-stat-blocked',
      'guardrail-stat-redacted',
      'guardrail-stat-flagged',
      'guardrail-stat-not-evaluated',
    ]) {
      const tile = container.querySelector(`[data-testid="${id}"]`);
      expect(tile?.getAttribute('data-slot')).toBe('card');
      expect(tile?.getAttribute('data-variant')).toBe('subtle');
    }
    expect(
      container
        .querySelector('[data-testid="guardrail-stat-not-evaluated"]')
        ?.getAttribute('title'),
    ).toBe('agents.guardrailEvents.notEvaluatedHint');
  });

  it('puts the window Select in the section header actions', () => {
    const header = container.querySelector('[data-slot="section-header"]');
    expect(
      header?.querySelector('[data-testid="guardrail-events-window"]'),
    ).not.toBeNull();
  });

  it('renders ui/table named by the Guardrail decisions sub-heading', () => {
    const table = container.querySelector('table[data-slot="table"]');
    expect(table).not.toBeNull();
    const labelId = table!.getAttribute('aria-labelledby');
    expect(labelId).toBeTruthy();
    // SectionHeader puts the id on its root; with no actions or description
    // the root holds only the h3, so the name is the heading's text.
    const label = document.getElementById(labelId!);
    expect(label?.querySelector('h3')?.textContent).toBe(
      'agents.guardrailEvents.tableHeader',
    );
    expect(label?.textContent).toBe('agents.guardrailEvents.tableHeader');
    expect(table!.querySelector('[data-slot="table-head"]')).not.toBeNull();
    expect(
      table!.querySelector(
        '[data-slot="table-body"][data-testid="guardrail-events-rows"]',
      ),
    ).not.toBeNull();
  });
});

describe('GuardrailEvents load error', () => {
  it('shows a destructive empty state whose Retry re-runs the fetch', async () => {
    fetchState.failNext = true;
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <Provider store={makeStore()}>
          <GuardrailEvents agentId="a1" />
        </Provider>,
      );
    });

    const errorState = container.querySelector(
      '[data-slot="empty-state"][data-tone="destructive"]',
    );
    expect(errorState?.textContent).toContain(
      'agents.guardrailEvents.loadError',
    );
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    );
    expect(retry).toBeDefined();

    await act(async () => retry!.click());

    expect(
      container.querySelector(
        '[data-slot="empty-state"][data-tone="destructive"]',
      ),
    ).toBeNull();
    expect(
      container.querySelector('[data-testid="guardrail-events-rows"]'),
    ).not.toBeNull();

    await act(async () => root.unmount());
    container.remove();
  });
});

describe('GuardrailEvents paging', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    fetchState.calls.length = 0;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(
        <Provider store={makeStore()}>
          <GuardrailEvents agentId="a1" />
        </Provider>,
      );
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  // The server applies the window and filters, so every page is filtered.
  it('asks the server for the first 50 decisions in the window', () => {
    const [agentId, , limit, offset, filters] = fetchState.calls[0];
    expect(agentId).toBe('a1');
    expect(limit).toBe(50);
    expect(offset).toBe(0);
    expect(filters).toEqual({ days: 30, check: undefined, outcome: undefined });
  });

  it('drops the "most recent N" note: older decisions load as you scroll', () => {
    expect(container.textContent).not.toContain(
      'agents.guardrailEvents.truncated',
    );
  });

  it("caps the table in the frame's inner overlay scroller", () => {
    const scroller = container.querySelector('table')!.parentElement!;
    expect(scroller.className).toContain('max-h-[45svh]');
    expect(scroller.className).toContain('scrollbar-overlay');
    // A short list has no status strip.
    expect(
      container.querySelector('[data-slot="load-more-status"]'),
    ).toBeNull();
  });
});
