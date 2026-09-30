import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../hooks/useLoadMore', () => ({ useScrollSentinel: () => vi.fn() }));
vi.mock('./traces/TraceSheet', () => ({ default: () => null }));
vi.mock('../components/CopyButton', () => ({ default: () => null }));

const getLogs = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: { getLogs: (...args: unknown[]) => getLogs(...args) },
}));

import Logs from './Logs';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const log = {
  id: 'log-1',
  action: 'stream_answer',
  level: 'info',
  timestamp: '2026-09-30 10:00:00',
  event_type: 'chat',
  question: 'Which carriers expire this month?',
  response: 'Three carriers.',
};

describe('Logs rows', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    getLogs.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ logs: [log], has_more: false }),
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root.render(<Logs />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('opens a row with a real button whose details are a Collapsible', async () => {
    const toggle = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button[aria-expanded]'),
    ).find((el) => el.textContent?.includes('[stream_answer]'))!;
    expect(toggle).toBeDefined();
    expect(container.querySelector('[role="button"]')).toBeNull();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    const body = document.getElementById(
      toggle.getAttribute('aria-controls')!,
    )!;
    expect(body.dataset.slot).toBe('collapsible');
    expect(body.dataset.state).toBe('closed');
    await act(async () => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body.dataset.state).toBe('open');
    expect(body.textContent).toContain('Three carriers.');
    await act(async () => toggle.click());
    expect(body.dataset.state).toBe('closed');
  });
});
