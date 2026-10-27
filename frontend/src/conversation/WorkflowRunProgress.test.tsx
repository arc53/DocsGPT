import i18n from 'i18next';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import en from '../locale/en.json';
import { WorkflowProgress, WorkflowStep } from './conversationModels';
import WorkflowRunProgress from './WorkflowRunProgress';

const testI18n = i18n.createInstance();

beforeAll(async () => {
  await testI18n.use(initReactI18next).init({
    lng: 'en',
    fallbackLng: 'en',
    resources: { en: { translation: en } },
  });
});

const step = (n: number, status: WorkflowStep['status']): WorkflowStep => ({
  nodeId: `n${n}`,
  nodeType: 'agent',
  title: `Step title ${n}`,
  status,
  startedAt: n * 1000,
  endedAt: status === 'running' ? undefined : n * 1000 + 3000,
  detail: status === 'completed' ? `result ${n}` : undefined,
});

// Six done, the seventh working, of 14.
const running: WorkflowProgress = {
  total: 14,
  steps: [
    ...Array.from({ length: 6 }, (_, i) => step(i + 1, 'completed')),
    step(7, 'running'),
  ],
};

const finished: WorkflowProgress = {
  total: 3,
  steps: [1, 2, 3].map((n) => step(n, 'completed')),
};

describe('WorkflowRunProgress', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = (
    workflow: WorkflowProgress,
    props: { isStreaming?: boolean; hasAnswerText?: boolean } = {},
  ) =>
    act(() => {
      root.render(
        <I18nextProvider i18n={testI18n}>
          <WorkflowRunProgress workflow={workflow} {...props} />
        </I18nextProvider>,
      );
    });

  const header = () =>
    container.querySelector<HTMLButtonElement>('button[aria-expanded]')!;
  const liveTitles = () =>
    Array.from(
      container.querySelectorAll('[aria-live="polite"] span[title]'),
      (el) => el.textContent,
    );

  it('shows how far the run is and its latest four steps', () => {
    render(running, { isStreaming: true });
    expect(header().textContent).toContain('Step 7 of 14');
    expect(liveTitles()).toEqual([
      'Step title 4',
      'Step title 5',
      'Step title 6',
      'Step title 7',
    ]);
    expect(container.textContent).toContain('result 6');
    expect(
      container
        .querySelector('[data-slot="spinner"]')
        ?.getAttribute('aria-label'),
    ).toBe('Running…');
  });

  it('says only the step number when a branch leaves the count open', () => {
    render({ ...running, total: undefined }, { isStreaming: true });
    expect(header().textContent).toContain('Step 7');
    expect(header().textContent).not.toContain('of');
  });

  it('keeps only the header once the answer streams', () => {
    render(running, { isStreaming: true, hasAnswerText: true });
    expect(container.querySelector('[aria-live="polite"]')).toBeNull();
    expect(header().getAttribute('aria-expanded')).toBe('false');
  });

  it('sums the run up after it and opens to every step', () => {
    render(finished);
    expect(header().textContent).toContain('3 steps · 5s');
    act(() => header().click());
    expect(header().getAttribute('aria-expanded')).toBe('true');
    const body = document.getElementById(
      header().getAttribute('aria-controls')!,
    )!;
    expect(body.textContent).toContain('Step title 1');
    expect(body.textContent).toContain('result 3');
  });

  it('marks a failed run and shows the step’s error', () => {
    render({
      steps: [{ ...step(1, 'failed'), error: 'model timed out' }],
    });
    expect(header().textContent).toContain('failed');
    expect(container.textContent).toContain('model timed out');
  });

  // Stop ends the stream with a step still marked running.
  it('shows a step a stop cut short as unfinished, not working', () => {
    render(running);
    act(() => header().click());
    const body = document.getElementById(
      header().getAttribute('aria-controls')!,
    )!;
    expect(body.querySelector('[role="status"]')).toBeNull();
    expect(body.querySelector('.shimmer-text')).toBeNull();
    expect(body.textContent).not.toMatch(/Step title 7\d/);
  });

  it('renders nothing before the first step', () => {
    render({ steps: [] }, { isStreaming: true });
    expect(container.innerHTML).toBe('');
  });
});
