import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    i18n: { language: 'en' },
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

const connector = (
  key: string,
  name: string,
  capabilities: string[],
  category: string,
  publisher = 'built_in',
) => ({
  key,
  name,
  publisher,
  capabilities,
  category,
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
            connector('brave', 'Brave Search', ['read'], 'search'),
            connector('telegram', 'Telegram', ['write'], 'messaging'),
            connector('google_drive', 'Google Drive', ['sync'], 'files'),
            connector(
              'mcp:notion',
              'Notion',
              ['read', 'write'],
              'knowledge',
              'preset',
            ),
            connector(
              'mcp:linear',
              'Linear',
              ['read', 'write'],
              'projects',
              'preset',
            ),
            connector('custom_mcp', 'MCP server', ['read'], 'custom', 'custom'),
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

  it('names services whose data you can chat with, as a list', async () => {
    await render([]);
    // Not a web search or a messaging bot: the card is "Connect your data".
    const expected = new Intl.ListFormat('en', { type: 'conjunction' }).format([
      'Google Drive',
      'Notion',
      'connectHero.more',
    ]);
    expect(card()?.textContent).toContain(`connectHero.body:${expected}`);
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

  it('keeps the browser translator off the model picker', async () => {
    await render([]);
    // A translator that rewraps the picker's text breaks React's next
    // commit; model names are product names anyway.
    const trigger = container.querySelector('[data-slot="select-trigger"]');
    expect(trigger?.getAttribute('translate')).toBe('no');
  });
});
