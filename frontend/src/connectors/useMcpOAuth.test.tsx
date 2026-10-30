import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const api = vi.hoisted(() => ({
  testMCPConnection: vi.fn(),
  cancelMCPOAuth: vi.fn(),
}));
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
    api.cancelMCPOAuth.mockReset().mockResolvedValue({});
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

  const serverEvent = async (type: string, payload = {}, taskId = 'task-1') => {
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: `${type}-${taskId}`,
          type,
          scope: { kind: 'mcp_oauth', id: taskId },
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
    // A window that only looks closed (COOP) never cancels the sign-in.
    expect(api.cancelMCPOAuth).not.toHaveBeenCalled();
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
  it('stops the sign-in on the server when the user cancels, so a retry starts fresh', async () => {
    const { popup, open, onDone } = await startWithPopup();
    await serverEvent('mcp.oauth.awaiting_redirect', {
      authorization_url: 'https://provider.example/authorize?try=1',
    });
    await act(async () => {
      hook.cancel();
    });
    expect(api.cancelMCPOAuth).toHaveBeenCalledWith('task-1', null);
    expect(pending()).toBe('false');

    api.testMCPConnection.mockResolvedValue({
      json: async () => ({ requires_oauth: true, task_id: 'task-2' }),
    });
    const retry = { onDone: vi.fn(), onError: vi.fn() };
    await act(async () => {
      await hook.start(CONFIG, retry);
    });
    // The cancelled attempt is not stopped twice, and its late events are ignored.
    expect(api.cancelMCPOAuth).toHaveBeenCalledTimes(1);
    await serverEvent('mcp.oauth.failed', { error: 'OAuth cancelled' });
    expect(retry.onError).not.toHaveBeenCalled();

    await serverEvent(
      'mcp.oauth.awaiting_redirect',
      { authorization_url: 'https://provider.example/authorize?try=2' },
      'task-2',
    );
    expect(popup.location.href).toBe(
      'https://provider.example/authorize?try=2',
    );
    await serverEvent('mcp.oauth.completed', {}, 'task-2');
    expect(retry.onDone).toHaveBeenCalledWith({ taskId: 'task-2' });
    expect(onDone).not.toHaveBeenCalled();
    open.mockRestore();
  });

  it('signs in through a COOP provider without cancelling on the server', async () => {
    const { popup, open, onDone, onError } = await startWithPopup();
    await serverEvent('mcp.oauth.awaiting_redirect', {
      authorization_url: 'https://dashboard.stripe.com/oauth',
    });
    // The provider's Cross-Origin-Opener-Policy cuts the window off: it reads closed.
    popup.closed = true;
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(api.cancelMCPOAuth).not.toHaveBeenCalled();
    expect(pending()).toBe('true');
    await serverEvent('mcp.oauth.completed');
    expect(onDone).toHaveBeenCalledWith({ taskId: 'task-1' });
    expect(onError).not.toHaveBeenCalled();
    expect(api.cancelMCPOAuth).not.toHaveBeenCalled();
    open.mockRestore();
  });

  it('stops the sign-in the server queued after the user already cancelled', async () => {
    const open = vi
      .spyOn(window, 'open')
      .mockReturnValue({ closed: false, close: vi.fn() } as never);
    let answer: (value: unknown) => void = () => undefined;
    api.testMCPConnection.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    const onDone = vi.fn();
    let started: Promise<void> = Promise.resolve();
    await act(async () => {
      started = hook.start(CONFIG, { onDone, onError: vi.fn() });
    });
    await act(async () => {
      hook.cancel();
    });
    // Nothing to stop yet: the server has not named the sign-in.
    expect(api.cancelMCPOAuth).not.toHaveBeenCalled();
    await act(async () => {
      answer({
        json: async () => ({ requires_oauth: true, task_id: 'task-1' }),
      });
      await started;
    });
    expect(api.cancelMCPOAuth).toHaveBeenCalledWith('task-1', null);
    expect(pending()).toBe('false');
    expect(onDone).not.toHaveBeenCalled();
    open.mockRestore();
  });

  it('stops the previous sign-in when the user starts again', async () => {
    const { open } = await startWithPopup();
    api.testMCPConnection.mockResolvedValue({
      json: async () => ({ requires_oauth: true, task_id: 'task-2' }),
    });
    await act(async () => {
      await hook.start(CONFIG, { onDone: vi.fn(), onError: vi.fn() });
    });
    expect(api.cancelMCPOAuth).toHaveBeenCalledTimes(1);
    expect(api.cancelMCPOAuth).toHaveBeenCalledWith('task-1', null);
    open.mockRestore();
  });

  it('does not call the server when there is no sign-in to cancel', async () => {
    await act(async () => {
      hook.cancel();
    });
    expect(api.cancelMCPOAuth).not.toHaveBeenCalled();
  });
});
