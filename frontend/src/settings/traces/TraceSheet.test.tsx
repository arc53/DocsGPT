import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('./TraceWaterfall', () => ({ default: () => null }));

const getTraces = vi.fn();
vi.mock('../../api/services/userService', () => ({
  default: {
    getTraces: (...args: unknown[]) => getTraces(...args),
  },
}));

import TraceSheet from './TraceSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const flush = () => act(() => new Promise((resolve) => setTimeout(resolve)));

describe('TraceSheet', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getTraces.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('shows a destructive empty state whose Retry refetches the trace', async () => {
    getTraces
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ traces: [] }) });

    act(() =>
      root.render(
        <TraceSheet
          traceRef={{ field: 'id', value: 't-1' }}
          onClose={() => undefined}
        />,
      ),
    );
    await flush();

    const alert = document.body.querySelector('[data-slot="empty-state"]');
    expect(alert?.getAttribute('data-tone')).toBe('destructive');
    expect(alert?.textContent).toContain('settings.logs.trace.failed');
    expect(getTraces).toHaveBeenCalledTimes(1);

    const retry = Array.from(alert?.querySelectorAll('button') ?? []).find(
      (button) => button.textContent === 'retry',
    );
    expect(retry).toBeDefined();
    act(() => retry?.click());
    await flush();

    expect(getTraces).toHaveBeenCalledTimes(2);
    expect(document.body.textContent).toContain('settings.logs.trace.empty');
    expect(document.body.querySelector('[data-tone="destructive"]')).toBeNull();
  });
});
