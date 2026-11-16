import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

const service = vi.hoisted(() => ({
  getConfig: vi.fn(),
  getMe: vi.fn(),
  refreshOidcSession: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: service }));
vi.mock('../backgroundJobs/webPush', () => ({
  forgetPushSubscription: async () => undefined,
}));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

/** A session token for `sub` that is due for renewal (five minutes left). */
const token = (sub: string, iat = 1) => {
  const payload = { sub, iat, exp: Math.floor(Date.now() / 1000) + 300 };
  return `h.${btoa(JSON.stringify(payload)).replace(/=+$/, '')}.s`;
};

let container: HTMLDivElement;
let root: Root;

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
  service.getConfig.mockResolvedValue({
    json: async () => ({ auth_type: 'oidc' }),
  });
  service.getMe.mockResolvedValue({ ok: true, json: async () => ({}) });
  service.refreshOidcSession
    .mockReset()
    .mockResolvedValue({ ok: false, status: 503 });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  localStorage.clear();
  vi.restoreAllMocks();
});

const start = async (current: string, stored: string) => {
  // Renewal state is kept per module: each test starts with none.
  vi.resetModules();
  const { prefSlice } = await import('../preferences/preferenceSlice');
  const { default: useTokenAuth } = await import('./useTokenAuth');
  function Auth() {
    useTokenAuth();
    return null;
  }
  const store = configureStore({ reducer: { preference: prefSlice.reducer } });
  store.dispatch(prefSlice.actions.setToken(current));
  // Another tab renewed, or signed in as someone else, since.
  localStorage.setItem('authToken', stored);
  await act(async () => {
    root.render(
      <Provider store={store}>
        <Auth />
      </Provider>,
    );
  });
  for (let i = 0; i < 5; i += 1) await act(flush);
  return store;
};

describe('renewing a session another tab already replaced', () => {
  it("reloads when the stored session is another person's, so nothing of the last one's stays", async () => {
    const reload = vi
      .spyOn(window.location, 'reload')
      .mockImplementation(() => undefined);
    const current = token('alice');
    const store = await start(current, token('bob'));
    expect(reload).toHaveBeenCalledTimes(1);
    expect(service.refreshOidcSession).not.toHaveBeenCalled();
    // Not taken over in place: the reload starts from the stored session.
    expect(store.getState().preference.token).toBe(current);
  });

  it("takes the same person's renewed session over in place", async () => {
    const reload = vi
      .spyOn(window.location, 'reload')
      .mockImplementation(() => undefined);
    const renewed = token('alice', 2);
    const store = await start(token('alice'), renewed);
    expect(reload).not.toHaveBeenCalled();
    expect(service.refreshOidcSession).not.toHaveBeenCalled();
    expect(store.getState().preference.token).toBe(renewed);
  });
});
