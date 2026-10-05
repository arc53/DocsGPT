import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const api = vi.hoisted(() => ({ testMCPConnection: vi.fn() }));
vi.mock('../api/services/userService', () => ({ default: api }));

import notificationsReducer, {
  sseEventReceived,
} from '../notifications/notificationsSlice';
import useMcpOAuth, { type McpOAuthConfig } from './useMcpOAuth';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const CONFIG: McpOAuthConfig = {
  server_url: 'https://mcp.notion.com/mcp',
  auth_type: 'oauth',
  oauth_scopes: [],
  timeout: 30,
  redirect_uri: 'http://localhost/api/mcp_server/callback',
};

describe('useMcpOAuth', () => {
  let root: Root;
  let container: HTMLDivElement;
  let hook: ReturnType<typeof useMcpOAuth>;
  let store: ReturnType<typeof makeStore>;

  const makeStore = () =>
    configureStore({
      reducer: {
        notifications: notificationsReducer,
        preference: (state = { token: null }) => state,
      },
    });

  function Probe() {
    hook = useMcpOAuth();
    return <span data-pending={String(hook.pending)} />;
  }

  beforeEach(async () => {
    vi.useFakeTimers();
    api.testMCPConnection.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    store = makeStore();
    await act(async () => {
      root.render(
        <Provider store={store}>
          <Probe />
        </Provider>,
      );
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  const pending = () =>
    container.querySelector('span')?.getAttribute('data-pending');

  // Sentry's and Stripe's sign-in pages send Cross-Origin-Opener-Policy:
  // same-origin, which cuts the pop-up off from this tab, so `closed` reads
  // true while the user is still signing in. Only the server knows the
  // outcome; the wizard's Cancel button ends a sign-in the user abandoned.
  const startWithPopup = async () => {
    const popup = { closed: false, close: vi.fn(), location: { href: '' } };
    const open = vi.spyOn(window, 'open').mockReturnValue(popup as never);
    api.testMCPConnection.mockResolvedValue({
      json: async () => ({ requires_oauth: true, task_id: 'task-1' }),
    });
    const onDone = vi.fn();
    const onError = vi.fn();
    await act(async () => {
      await hook.start(CONFIG, { onDone, onError });
    });
    return { popup, open, onDone, onError };
  };

  const serverEvent = async (type: string, payload = {}) => {
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: `${type}-1`,
          type,
          scope: { kind: 'mcp_oauth', id: 'task-1' },
          payload,
        }),
      );
    });
  };

  it('keeps waiting for the server when the sign-in window looks closed', async () => {
    const { popup, open, onDone, onError } = await startWithPopup();
    expect(pending()).toBe('true');
    popup.closed = true;
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(onError).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
    expect(pending()).toBe('true');
    open.mockRestore();
  });

  it('finishes the sign-in the server completed after the window looked closed', async () => {
    const { popup, open, onDone, onError } = await startWithPopup();
    popup.closed = true;
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await serverEvent('mcp.oauth.completed');
    expect(onDone).toHaveBeenCalledWith({ taskId: 'task-1' });
    expect(onError).not.toHaveBeenCalled();
    expect(pending()).toBe('false');
    open.mockRestore();
  });

  it("reports the server's failure after the window looked closed", async () => {
    const { popup, open, onDone, onError } = await startWithPopup();
    popup.closed = true;
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await serverEvent('mcp.oauth.failed', { error: 'OAuth timeout' });
    expect(onError).toHaveBeenCalledWith('OAuth timeout');
    expect(onDone).not.toHaveBeenCalled();
    expect(pending()).toBe('false');
    open.mockRestore();
  });

  it('stops waiting when the user cancels', async () => {
    const { popup, open, onDone, onError } = await startWithPopup();
    popup.closed = true;
    await act(async () => {
      hook.cancel();
    });
    expect(pending()).toBe('false');
    await serverEvent('mcp.oauth.completed');
    expect(onDone).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    open.mockRestore();
  });

  it('does not report a cancel when the browser blocked the window', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    api.testMCPConnection.mockResolvedValue({
      json: async () => ({ requires_oauth: true, task_id: 'task-1' }),
    });
    const onError = vi.fn();
    await act(async () => {
      await hook.start(CONFIG, { onDone: vi.fn(), onError });
    });
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(onError).not.toHaveBeenCalled();
    expect(pending()).toBe('true');
    open.mockRestore();
  });
});
