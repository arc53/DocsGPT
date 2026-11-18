import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { email?: string }) =>
      options?.email ? `${key}:${options.email}` : key,
  }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => 'user-token',
}));

vi.mock('@/hooks', () => ({
  useDarkTheme: () => [false, () => undefined],
}));

const service = vi.hoisted(() => ({ completeConnectorAuth: vi.fn() }));

vi.mock('@/api/services/userService', () => ({ default: service }));

import ConnectorCallback from './ConnectorCallback';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ConnectorCallback', () => {
  let container: HTMLDivElement;
  let root: Root;
  let opener: { postMessage: ReturnType<typeof vi.fn> } | null;
  let replaceState: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    opener = { postMessage: vi.fn() };
    Object.defineProperty(window, 'opener', {
      configurable: true,
      get: () => opener,
    });
    replaceState = vi
      .spyOn(window.history, 'replaceState')
      .mockImplementation(() => undefined);
    vi.spyOn(window, 'close').mockImplementation(() => undefined);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    service.completeConnectorAuth.mockReset();
  });

  const respond = (ok: boolean, body: unknown) =>
    service.completeConnectorAuth.mockResolvedValue({
      ok,
      json: async () => body,
    });

  const visit = async (search: string) => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={[`/connectors/callback${search}`]}>
          <ConnectorCallback />
        </MemoryRouter>,
      );
    });
  };

  it("finishes the sign-in with the browser's own login and tells the opener", async () => {
    respond(true, {
      success: true,
      provider: 'google_drive',
      connection_id: 'conn-1',
      user_email: 'a@b.c',
      return_origin: 'https://app.example.com',
    });
    await visit('?code=the-code&state=the-state');

    expect(service.completeConnectorAuth).toHaveBeenCalledTimes(1);
    expect(service.completeConnectorAuth).toHaveBeenCalledWith(
      { code: 'the-code', state: 'the-state' },
      'user-token',
    );
    // The code does not stay in the address bar.
    expect(replaceState).toHaveBeenCalled();
    expect(String(replaceState.mock.calls[0][2])).not.toContain('the-code');
    expect(opener?.postMessage).toHaveBeenCalledWith(
      {
        type: 'google_drive_auth_success',
        connection_id: 'conn-1',
        user_email: 'a@b.c',
      },
      'https://app.example.com',
    );
    expect(container.textContent).toContain(
      'modals.uploadDoc.connectors.auth.connectedAs:a@b.c',
    );
  });

  it('reports a refused sign-in as a failure, without a connection', async () => {
    respond(false, {
      success: false,
      error: 'This sign-in has expired. Please start again.',
    });
    await visit('?code=the-code&state=someone-elses-state');

    expect(opener?.postMessage).toHaveBeenCalledWith(
      { type: 'connector_auth_error' },
      window.location.origin,
    );
    expect(container.textContent).toContain(
      'modals.uploadDoc.connectors.callback.failed',
    );
  });

  it('does not post a code the provider never sent', async () => {
    await visit('?error=access_denied&state=the-state');

    expect(service.completeConnectorAuth).not.toHaveBeenCalled();
    expect(opener?.postMessage).not.toHaveBeenCalled();
    expect(container.textContent).toContain(
      'modals.uploadDoc.connectors.auth.authCancelled',
    );
  });

  it('finishes without an opener and leaves the window open', async () => {
    opener = null;
    respond(true, {
      success: true,
      provider: 'google_drive',
      connection_id: 'conn-1',
      user_email: 'a@b.c',
    });
    await visit('?code=the-code&state=the-state');

    expect(service.completeConnectorAuth).toHaveBeenCalledTimes(1);
    expect(window.close).not.toHaveBeenCalled();
    expect(container.textContent).toContain(
      'modals.uploadDoc.connectors.callback.closeWindow',
    );
  });
});
