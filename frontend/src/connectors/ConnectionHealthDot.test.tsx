import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import ConnectionHealthDot from './ConnectionHealthDot';
import connectorsReducer from './connectorsSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ConnectionHealthDot', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (statuses: string[]) => {
    const store = configureStore({
      reducer: { connectors: connectorsReducer },
      preloadedState: {
        connectors: {
          enabled: true,
          loading: false,
          loaded: true,
          failed: false,
          catalog: [],
          connections: statuses.map((status, i) => ({ id: `c${i}`, status })),
        },
      },
    } as Parameters<typeof configureStore>[0]);
    await act(async () => {
      root.render(
        <Provider store={store}>
          <ConnectionHealthDot />
        </Provider>,
      );
    });
  };

  it('shows while a connection needs signing in again', async () => {
    await render(['connected', 'reconnect_needed']);
    const dot = container.querySelector(
      '[data-testid="connection-health-dot"]',
    );
    expect(dot?.getAttribute('aria-label')).toBe(
      'settings.connectors.health.navDot',
    );
  });

  it('stays away when every connection works', async () => {
    await render(['connected', 'disconnected']);
    expect(container.innerHTML).toBe('');
  });
});
