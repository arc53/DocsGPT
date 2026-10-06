import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const push = vi.hoisted(() => ({
  enablePush: vi.fn(),
  savePushChoice: vi.fn(),
}));
vi.mock('./webPush', () => push);
vi.mock('../api/services/backgroundService', () => ({ default: {} }));

import actionToastReducer from '../notifications/actionToastSlice';
import backgroundReducer, {
  fetchPushConfig,
  requestPushPrompt,
  selectPushPromptOpen,
} from './backgroundSlice';
import PushPermissionToast from './PushPermissionToast';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('PushPermissionToast', () => {
  let container: HTMLDivElement;
  let root: Root;

  const makeStore = (enabled = true) => {
    const store = configureStore({
      reducer: {
        background: backgroundReducer,
        actionToast: actionToastReducer,
        preference: (state: { token: string | null } = { token: 'tok' }) =>
          state,
      },
    });
    store.dispatch({
      type: fetchPushConfig.fulfilled.type,
      payload: { enabled, public_key: enabled ? 'PUBKEY' : null },
    });
    return store;
  };

  beforeEach(() => {
    push.enablePush.mockReset();
    push.savePushChoice.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (store: ReturnType<typeof makeStore>) => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <PushPermissionToast />
        </Provider>,
      );
    });
  };
  // The prompt renders into document.body, outside the bottom toast stack.
  const prompt = () =>
    document.querySelector('[data-testid="push-permission-prompt"]');
  const button = (text: string) =>
    Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent === text,
    ) as HTMLButtonElement;

  it('stays hidden until something asks for it (never on load)', async () => {
    const store = makeStore();
    await render(store);
    expect(prompt()).toBeNull();
    await act(async () => {
      store.dispatch(requestPushPrompt());
    });
    expect(prompt()).not.toBeNull();
    expect(prompt()?.textContent).toContain('backgroundJobs.push.promptTitle');
    expect(push.enablePush).not.toHaveBeenCalled();
  });

  it('sits at the top right, out of the bottom stack over the composer', async () => {
    const store = makeStore();
    store.dispatch(requestPushPrompt());
    const viewport = document.createElement('div');
    viewport.setAttribute('data-slot', 'toast-viewport');
    container.appendChild(viewport);
    await render(store);
    const anchor = document.querySelector(
      '[data-testid="push-permission-anchor"]',
    );
    expect(anchor?.parentElement).toBe(document.body);
    expect(anchor?.className).toContain('top-20');
    expect(anchor?.className).not.toContain('bottom-');
    expect(prompt()?.closest('[data-slot="toast-viewport"]')).toBeNull();
  });

  it('stays hidden when the server has no push', async () => {
    const store = makeStore(false);
    store.dispatch(requestPushPrompt());
    await render(store);
    expect(prompt()).toBeNull();
  });

  it('Not now remembers the answer and closes', async () => {
    const store = makeStore();
    store.dispatch(requestPushPrompt());
    await render(store);
    await act(async () => button('backgroundJobs.push.notNow').click());
    expect(push.savePushChoice).toHaveBeenCalledWith('dismissed');
    expect(push.enablePush).not.toHaveBeenCalled();
    expect(selectPushPromptOpen(store.getState())).toBe(false);
  });

  it('Enable asks the browser, subscribes and remembers', async () => {
    push.enablePush.mockResolvedValue('granted');
    const store = makeStore();
    store.dispatch(requestPushPrompt());
    await render(store);
    await act(async () => button('backgroundJobs.push.enable').click());
    expect(push.enablePush).toHaveBeenCalledWith('PUBKEY', 'tok');
    expect(push.savePushChoice).toHaveBeenCalledWith('enabled');
    expect(selectPushPromptOpen(store.getState())).toBe(false);
  });

  it('a blocked permission says where to change it', async () => {
    push.enablePush.mockResolvedValue('denied');
    const store = makeStore();
    store.dispatch(requestPushPrompt());
    await render(store);
    await act(async () => button('backgroundJobs.push.enable').click());
    expect(push.savePushChoice).toHaveBeenCalledWith('dismissed');
    expect(JSON.stringify(store.getState().actionToast)).toContain(
      'backgroundJobs.push.blocked',
    );
  });

  it('a failed subscribe is reported', async () => {
    push.enablePush.mockRejectedValue(new Error('no'));
    const store = makeStore();
    store.dispatch(requestPushPrompt());
    await render(store);
    await act(async () => button('backgroundJobs.push.enable').click());
    expect(JSON.stringify(store.getState().actionToast)).toContain(
      'backgroundJobs.push.failed',
    );
    expect(selectPushPromptOpen(store.getState())).toBe(false);
  });
});
