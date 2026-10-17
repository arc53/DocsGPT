import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('../hooks', () => ({
  useDarkTheme: () => [false, () => undefined],
}));

const service = vi.hoisted(() => ({ getConnectorAuthUrl: vi.fn() }));

vi.mock('../api/services/userService', () => ({ default: service }));

import ConnectorAuth from './ConnectorAuth';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ConnectorAuth', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = (props: Partial<Parameters<typeof ConnectorAuth>[0]>) =>
    act(() =>
      root.render(
        <ConnectorAuth
          provider="google_drive"
          onSuccess={() => undefined}
          onError={() => undefined}
          label="Connect"
          {...props}
        />,
      ),
    );

  it('shows the error as a destructive alert with an icon', () => {
    render({ errorMessage: 'Session expired' });
    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.className).toContain('text-destructive');
    expect(alert?.querySelector('svg')).not.toBeNull();
    expect(alert?.textContent).toContain('Session expired');
  });

  it('renders the connected banner as a polite success alert', () => {
    const onDisconnect = vi.fn();
    render({ isConnected: true, userEmail: 'a@b.c', onDisconnect });
    const banner = container.querySelector('[role="status"]');
    expect(banner).not.toBeNull();
    expect(banner?.className).toContain('text-success');
    expect(banner?.className).toContain('bg-success/10');
    expect(banner?.querySelector('svg')).not.toBeNull();
    const button = banner?.querySelector('button');
    expect(button?.className).toContain('text-primary');
    expect(button?.className).not.toContain('text-black');
    expect(button?.textContent).toBe(
      'modals.uploadDoc.connectors.auth.disconnect',
    );
    act(() => button?.click());
    expect(onDisconnect).toHaveBeenCalledTimes(1);
  });

  // Opens the pop-up and returns a function that posts a message from it.
  const startSignIn = async (
    props: Partial<Parameters<typeof ConnectorAuth>[0]>,
  ) => {
    const popup = { closed: false, close: vi.fn(), location: { href: '' } };
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
    service.getConnectorAuthUrl.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        authorization_url: 'https://provider.example.com/auth',
        callback_origin: 'https://app.example.com',
      }),
    });
    render(props);
    await act(async () => {
      container.querySelector('button')?.click();
    });
    expect(popup.location.href).toBe('https://provider.example.com/auth');
    return (data: unknown, origin = 'https://app.example.com') => {
      const event = new MessageEvent('message', { data, origin });
      Object.defineProperty(event, 'source', { value: popup });
      act(() => {
        window.dispatchEvent(event);
      });
    };
  };

  afterEach(() => {
    vi.restoreAllMocks();
    service.getConnectorAuthUrl.mockReset();
  });

  it('reports the connection the callback page finished', async () => {
    const onSuccess = vi.fn();
    const post = await startSignIn({ onSuccess });
    post({
      type: 'google_drive_auth_success',
      connection_id: 'conn-1',
      user_email: 'a@b.c',
    });
    expect(onSuccess).toHaveBeenCalledWith({
      connection_id: 'conn-1',
      user_email: 'a@b.c',
    });
  });

  it('ignores a result from another origin', async () => {
    const onSuccess = vi.fn();
    const post = await startSignIn({ onSuccess });
    post(
      { type: 'google_drive_auth_success', connection_id: 'conn-1' },
      'https://attacker.example.com',
    );
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('reports a generic failure from the callback page', async () => {
    const onError = vi.fn();
    const post = await startSignIn({ onError });
    post({ type: 'connector_auth_error' });
    expect(onError).toHaveBeenCalledWith(
      'modals.uploadDoc.connectors.auth.authFailed',
    );
  });

  it('renders the auth button as a default brand button', () => {
    render({});
    const button = container.querySelector('button');
    expect(button?.textContent).toContain('Connect');
    expect(button?.className).toContain('bg-primary');
    expect(button?.className).not.toContain('bg-blue-500');
  });
});
