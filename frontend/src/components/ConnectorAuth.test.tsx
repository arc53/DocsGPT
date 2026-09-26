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

vi.mock('../api/services/userService', () => ({ default: {} }));

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

  it('renders the auth button as a default brand button', () => {
    render({});
    const button = container.querySelector('button');
    expect(button?.textContent).toContain('Connect');
    expect(button?.className).toContain('bg-primary');
    expect(button?.className).not.toContain('bg-blue-500');
  });
});
