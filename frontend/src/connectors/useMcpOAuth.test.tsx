import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const api = vi.hoisted(() => ({ testMCPConnection: vi.fn() }));
vi.mock('../api/services/userService', () => ({ default: api }));

import notificationsReducer from '../notifications/notificationsSlice';
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
    const store = configureStore({
      reducer: {
        notifications: notificationsReducer,
        preference: (state = { token: null }) => state,
      },
    });
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

  it('stops waiting and says so when the sign-in window is closed', async () => {
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
    expect(pending()).toBe('true');
    // Still open: nothing happens.
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    expect(onError).not.toHaveBeenCalled();
    popup.closed = true;
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    expect(onError).toHaveBeenCalledWith(
      'modals.uploadDoc.connectors.auth.authCancelled',
    );
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
    expect(pending()).toBe('false');
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
