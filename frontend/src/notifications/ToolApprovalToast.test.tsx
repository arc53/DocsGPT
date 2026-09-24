import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import en from '../locale/en.json';

// Resolve keys against the English bundle so assertions read as the UI does.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) =>
      key
        .split('.')
        .reduce<unknown>(
          (node, part) => (node as Record<string, unknown>)?.[part],
          en,
        ) ?? key,
  }),
}));

import notificationsReducer, { sseEventReceived } from './notificationsSlice';
import ToolApprovalToast from './ToolApprovalToast';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeStore = () =>
  configureStore({
    reducer: {
      notifications: notificationsReducer,
      preference: () => ({
        conversations: { data: [{ id: 'c1', name: 'Halvorsen review' }] },
      }),
    },
  });

function Location() {
  return <span data-testid="location">{useLocation().pathname}</span>;
}

describe('ToolApprovalToast', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    localStorage.clear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    store = makeStore();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const renderAt = async (path: string) => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route
                path="*"
                element={
                  <>
                    <ToolApprovalToast />
                    <Location />
                  </>
                }
              />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const pause = (id: string, conversationId: string) =>
    store.dispatch(
      sseEventReceived({
        id,
        type: 'tool.approval.required',
        scope: { kind: 'conversation', id: conversationId },
      }),
    );

  const toasts = () => container.querySelectorAll('[data-slot="toast"]');

  it('renders a warning card with no rail of its own', async () => {
    pause('e1', 'c1');
    await renderAt('/');
    expect(toasts()).toHaveLength(1);
    // App.tsx owns the shared ToastViewport and its live region.
    expect(container.querySelector('[data-slot="toast-viewport"]')).toBeNull();
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(container.querySelector('.fixed')).toBeNull();
    expect(
      container
        .querySelector('[data-slot="toast-header"]')
        ?.getAttribute('data-variant'),
    ).toBe('warning');
    expect(
      container.querySelector('[data-slot="toast-title"]')?.textContent,
    ).toBe('Tool approval needed');
    const item = container.querySelector('[data-slot="toast-item"]');
    expect(item?.textContent).toContain('Halvorsen review');
    expect(item?.querySelector('[data-status="warning"]')).not.toBeNull();
  });

  it('dedups per conversation and hides the one in view', async () => {
    pause('e1', 'c1');
    pause('e2', 'c1');
    pause('e3', 'c2');
    await renderAt('/c/c2');
    expect(toasts()).toHaveLength(1);
    expect(container.textContent).toContain('Halvorsen review');
  });

  it('dismisses on close', async () => {
    pause('e1', 'c1');
    await renderAt('/');
    const close = container.querySelector(
      'button[aria-label="Dismiss"]',
    ) as HTMLButtonElement;
    await act(async () => close.click());
    expect(toasts()).toHaveLength(0);
  });

  it('navigates to the conversation on Review', async () => {
    pause('e1', 'c1');
    await renderAt('/');
    const review = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'Review',
    ) as HTMLButtonElement;
    await act(async () => review.click());
    expect(
      container.querySelector('[data-testid="location"]')?.textContent,
    ).toBe('/c/c1');
    expect(toasts()).toHaveLength(0);
  });
});
