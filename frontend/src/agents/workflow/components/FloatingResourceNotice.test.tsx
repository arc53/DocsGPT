import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import FloatingResourceNotice from './FloatingResourceNotice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: number }) =>
      options?.count !== undefined ? `${key}:${options.count}` : key,
  }),
}));

describe('FloatingResourceNotice', () => {
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

  const render = async (stoppedCount: number) =>
    act(async () => {
      root.render(
        <FloatingResourceNotice stoppedCount={stoppedCount}>
          <p data-testid="notice">notice</p>
        </FloatingResourceNotice>,
      );
    });

  const byLabel = (label: string) =>
    container.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`);

  it('fits the canvas on a narrow screen', async () => {
    await render(1);
    const panel = container.querySelector('[data-testid="notice"]')!
      .parentElement!.parentElement!;
    expect(panel.className).not.toContain('w-full');
    expect(panel.className).toContain('max-w-[calc(100%-2rem)]');
  });

  it('closes to a chip that opens it again', async () => {
    await render(2);
    await act(async () => byLabel('agents.close')!.click());
    expect(container.querySelector('[data-testid="notice"]')).toBeNull();
    const chip = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('agents.form.resourceStates.chip:2'),
    )!;
    await act(async () => chip.click());
    expect(container.querySelector('[data-testid="notice"]')).not.toBeNull();
  });

  it('leaves no chip once nothing is stopped', async () => {
    await render(0);
    await act(async () => byLabel('agents.close')!.click());
    expect(container.innerHTML).toBe('');
  });
});
