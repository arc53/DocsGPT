import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import ChartPanel from './ChartPanel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ChartPanel', () => {
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

  const chart = vi.fn((legendId: string) => (
    <div data-testid="chart" data-legend={legendId} />
  ));

  it('titles the panel as a section of the page and hands the chart its legend', () => {
    act(() => root.render(<ChartPanel title="Messages" chart={chart} />));
    // The panels sit straight under the page's h1.
    expect(container.querySelector('h2')!.textContent).toBe('Messages');
    expect(container.querySelector('h3')).toBeNull();
    const legendId = container
      .querySelector('[data-testid="chart"]')!
      .getAttribute('data-legend')!;
    expect(container.querySelector(`[id="${legendId}"]`)).not.toBeNull();
  });

  it('keeps its title while loading, with a skeleton in place of the chart', () => {
    act(() =>
      root.render(<ChartPanel title="Messages" chart={chart} loading />),
    );
    expect(container.querySelector('h2')!.textContent).toBe('Messages');
    expect(container.querySelector('[data-testid="chart"]')).toBeNull();
    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0);
  });

  it('puts its controls in the title row', () => {
    act(() =>
      root.render(
        <ChartPanel
          title="Token usage"
          chart={chart}
          actions={<button type="button">Group by</button>}
        />,
      ),
    );
    const heading = container.querySelector('h2')!;
    const row = heading.closest('[data-slot="section-header"]')!.parentElement!;
    expect(row.querySelector('button')!.textContent).toBe('Group by');
  });

  it('says the chart failed to load, with Retry, instead of drawing it', () => {
    const onRetry = vi.fn();
    act(() =>
      root.render(
        <ChartPanel
          title="Messages"
          chart={chart}
          error="Could not load this chart."
          onRetry={onRetry}
        />,
      ),
    );
    const alert = container.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('Could not load this chart.');
    expect(container.querySelector('[data-testid="chart"]')).toBeNull();
    act(() => alert.querySelector('button')!.click());
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
