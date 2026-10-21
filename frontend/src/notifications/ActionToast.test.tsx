import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { Toast, ToastViewport } from '../components/ui/toast';
import ActionToast, { ACTION_TOAST_DISMISS_MS } from './ActionToast';
import actionToastReducer, { showActionToast } from './actionToastSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeStore = () =>
  configureStore({ reducer: { actionToast: actionToastReducer } });

describe('ActionToast', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    store = makeStore();
    await act(async () => {
      root.render(
        <Provider store={store}>
          <ActionToast />
        </Provider>,
      );
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  const show = async (variant: 'success' | 'destructive', message: string) =>
    act(async () => {
      store.dispatch(showActionToast({ variant, message }));
    });

  it('renders nothing when there is no toast', () => {
    expect(container.querySelector('[data-slot="toast"]')).toBeNull();
  });

  it('renders the message as a card with the variant header', async () => {
    await show('success', 'lena deactivated');
    const card = container.querySelector('[data-slot="toast"]');
    expect(card?.textContent).toContain('lena deactivated');
    // Cards carry no role; the shared ToastViewport is the live region.
    expect(card?.getAttribute('role')).toBeNull();
    expect(
      container
        .querySelector('[data-slot="toast-header"]')
        ?.getAttribute('data-variant'),
    ).toBe('success');
  });

  it('uses the destructive header for a failure', async () => {
    await show('destructive', 'Action failed for lena');
    expect(
      container
        .querySelector('[data-slot="toast-header"]')
        ?.getAttribute('data-variant'),
    ).toBe('destructive');
  });

  it('closes on the dismiss button', async () => {
    await show('success', 'done');
    const btn = container.querySelector(
      'button[aria-label="notifications.dismiss"]',
    ) as HTMLButtonElement;
    await act(async () => btn.click());
    expect(container.querySelector('[data-slot="toast"]')).toBeNull();
  });

  it('auto-dismisses after 4.5s, restarting for a new message', async () => {
    vi.useFakeTimers();
    expect(ACTION_TOAST_DISMISS_MS).toBe(4500);
    await show('success', 'first');
    await act(async () => vi.advanceTimersByTime(3000));
    await show('success', 'second');
    await act(async () => vi.advanceTimersByTime(3000));
    expect(container.textContent).toContain('second');
    await act(async () => vi.advanceTimersByTime(1600));
    expect(container.querySelector('[data-slot="toast"]')).toBeNull();
  });

  it('shows a new result on a phone even after a newer card folded the last one', async () => {
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) =>
        ({
          matches: true,
          media: query,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
        }) as unknown as MediaQueryList,
    );
    const renderStack = (approval: boolean) =>
      act(async () => {
        root.render(
          <Provider store={store}>
            <ToastViewport>
              <ActionToast />
              {approval && <Toast key="approval">approval</Toast>}
            </ToastViewport>
          </Provider>,
        );
      });
    const shown = () =>
      Array.from(container.querySelectorAll<HTMLElement>('[data-slot="toast"]'))
        .filter((card) => !card.hidden)
        .map((card) => card.textContent);
    await renderStack(false);
    await show('success', 'saved');
    await renderStack(true);
    expect(shown()).toEqual(['approval']);

    await show('destructive', 'delete failed');
    expect(shown()).toEqual(['delete failed']);
  });

  it('waits while the stack folds it', async () => {
    vi.useFakeTimers();
    await show('success', 'done');
    const card = container.querySelector<HTMLElement>('[data-slot="toast"]')!;
    await act(async () => {
      card.hidden = true;
    });
    await act(async () => vi.advanceTimersByTime(ACTION_TOAST_DISMISS_MS + 10));
    expect(container.querySelector('[data-slot="toast"]')).not.toBeNull();
    await act(async () => {
      card.hidden = false;
    });
    await act(async () => vi.advanceTimersByTime(ACTION_TOAST_DISMISS_MS + 10));
    expect(container.querySelector('[data-slot="toast"]')).toBeNull();
  });
});
