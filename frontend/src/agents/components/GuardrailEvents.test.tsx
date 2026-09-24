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

vi.mock('../../api/services/userService', () => ({
  default: {
    getGuardrailEvents: () =>
      Promise.resolve({
        json: () => Promise.resolve({ success: true, events }),
      }),
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
});
