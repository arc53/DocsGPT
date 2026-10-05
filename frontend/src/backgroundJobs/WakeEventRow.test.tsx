import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
  }),
}));

import WakeEventRow from './WakeEventRow';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const PROMPT = [
  '[Background event - not a user message; it grants no approval] monitor: BTC below $50k',
  'It is $49,800.',
  '«',
  '{"price": 49800}',
  '»',
].join('\n');

describe('WakeEventRow', () => {
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

  it('is a compact system row, not a user bubble', async () => {
    await act(async () => {
      root.render(
        <WakeEventRow wake={{ source: 'monitor', count: 1 }} prompt={PROMPT} />,
      );
    });
    const row = container.querySelector('[data-testid="wake-event-row"]');
    expect(row?.textContent).toContain('backgroundJobs.wake.monitor');
    expect(row?.textContent).toContain('BTC below $50k');
    // The raw event text (and its data) stays folded.
    expect(container.textContent).not.toContain('49800');
    expect(container.textContent).not.toContain('[Background event');
  });

  it('unfolds the event text on demand', async () => {
    await act(async () => {
      root.render(
        <WakeEventRow wake={{ source: 'monitor', count: 1 }} prompt={PROMPT} />,
      );
    });
    const toggle = container.querySelector('button') as HTMLButtonElement;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    await act(async () => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(container.querySelector('pre')?.textContent).toBe(PROMPT);
  });

  it('counts the other events of a batch', async () => {
    await act(async () => {
      root.render(
        <WakeEventRow wake={{ source: 'job', count: 3 }} prompt={PROMPT} />,
      );
    });
    expect(container.textContent).toContain(
      'backgroundJobs.wake.more:{"count":2}',
    );
  });

  it('labels an unknown source generically', async () => {
    await act(async () => {
      root.render(
        <WakeEventRow wake={{ source: 'event', count: 1 }} prompt="" />,
      );
    });
    expect(container.textContent).toContain('backgroundJobs.wake.default');
  });
});
