import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import FloatingResourceNotice from './FloatingResourceNotice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { formatted?: string }) =>
      options?.formatted !== undefined ? `${key}:${options.formatted}` : key,
    i18n: { language: 'en' },
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

  const render = async (stoppedCount: number, hidden = false) =>
    act(async () => {
      root.render(
        <FloatingResourceNotice stoppedCount={stoppedCount} hidden={hidden}>
          {(close) => (
            <div data-testid="notice" data-slot="alert">
              <button type="button" aria-label="close" onClick={close} />
            </div>
          )}
        </FloatingResourceNotice>,
      );
    });

  const notice = () => container.querySelector('[data-testid="notice"]');
  const chip = () =>
    Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('agents.form.resourceStates.chip'),
    );

  // The floating-Alert recipe: the Alert sits right on the opaque card,
  // with no padded box around it.
  it('floats the notice directly on an opaque card that fits the canvas', async () => {
    await render(1);
    const card = notice()!.parentElement!;
    expect(card.className).toContain('bg-card');
    expect(card.className).toContain('rounded-xl');
    expect(card.className).toContain('shadow-md');
    expect(card.className).toContain('max-w-[calc(100%-2rem)]');
    expect(card.className).not.toContain('p-3');
    expect(card.className).not.toContain('overflow-y-auto');
  });

  it('closes to a chip that counts what is stopped and opens it again', async () => {
    await render(1234);
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[aria-label="close"]')!
        .click(),
    );
    expect(notice()).toBeNull();
    expect(chip()?.textContent).toContain(
      'agents.form.resourceStates.chip:1,234',
    );
    await act(async () => chip()!.click());
    expect(notice()).not.toBeNull();
  });

  // Only stopped items float: who added what lives in the pickers.
  it('shows nothing while nothing is stopped', async () => {
    await render(0);
    expect(container.innerHTML).toBe('');
  });

  // The publish errors float in the same spot; they win while they show.
  it('steps aside while the publish errors show, then comes back', async () => {
    await render(2, true);
    expect(container.innerHTML).toBe('');
    await render(2, false);
    expect(notice()).not.toBeNull();
  });
});
