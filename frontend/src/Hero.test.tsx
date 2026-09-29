import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (key === 'demo')
        return [1, 2, 3, 4].map((n) => ({
          header: `demo${n}`,
          query: `q${n}`,
        }));
      return opts?.names ? `${key}:${opts.names}` : key;
    },
  }),
}));

vi.mock('./api/services/modelService', () => ({
  default: {
    getModels: vi.fn(async () => ({ ok: true, json: async () => ({}) })),
    transformModels: () => [],
  },
}));
vi.mock('./hooks', () => ({ useDarkTheme: () => [false] }));

import connectorsReducer from './connectors/connectorsSlice';
import Hero from './Hero';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const connector = (key: string, name: string, publisher = 'built_in') => ({
  key,
  name,
  publisher,
  available: true,
});

describe('Hero connect card', () => {
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

  const render = async (connections: unknown[]) => {
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        preference: (
          state = {
            token: null,
            selectedModel: null,
            availableModels: [],
            modelsLoading: false,
          },
        ) => state,
      },
      preloadedState: {
        connectors: {
          enabled: true,
          loading: false,
          loaded: true,
          failed: false,
          catalog: [
            connector('google_drive', 'Google Drive'),
            connector('mcp:notion', 'Notion', 'preset'),
            connector('custom_mcp', 'MCP server', 'custom'),
          ],
          connections,
        },
      },
    } as Parameters<typeof configureStore>[0]);
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/']}>
            <Routes>
              <Route path="/" element={<Hero handleQuestion={vi.fn()} />} />
              <Route
                path="/settings/connectors"
                element={<div>CONNECTORS</div>}
              />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const card = () =>
    container.querySelector<HTMLButtonElement>(
      '[data-testid="hero-connect-card"]',
    );

  it('offers connecting the services this install has', async () => {
    await render([]);
    expect(card()?.textContent).toContain(
      'connectHero.body:Google Drive, Notion',
    );
    // It replaces the last demo card.
    expect(container.textContent).not.toContain('demo4');
    await act(async () => card()!.click());
    expect(container.textContent).toContain('CONNECTORS');
  });

  it('keeps the demo cards once something is connected', async () => {
    await render([{ id: 'c1', status: 'connected' }]);
    expect(card()).toBeNull();
    expect(container.textContent).toContain('demo4');
  });
});
