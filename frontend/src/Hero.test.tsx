import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    i18n: { language: 'en' },
    t: (key: string, opts?: Record<string, unknown>) => {
      const values = ['name', 'first', 'second', 'names']
        .map((k) => opts?.[k])
        .filter(Boolean);
      return values.length ? `${key}:${values.join('|')}` : key;
    },
  }),
}));

vi.mock('./api/services/modelService', () => ({
  default: {
    getModels: vi.fn(async () => ({ ok: true, json: async () => ({}) })),
    transformModels: () => [],
  },
}));
vi.mock('./hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./hooks')>()),
  useDarkTheme: () => [false],
}));

import connectorsReducer from './connectors/connectorsSlice';
import chatToolsReducer from './conversation/chatToolsSlice';
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
  icon: key,
  publisher,
  capabilities,
  category,
  available: true,
});

const CATALOG = [
  connector('brave', 'Brave Search', ['read'], 'search'),
  connector('telegram', 'Telegram', ['write'], 'messaging'),
  connector('google_drive', 'Google Drive', ['sync'], 'files'),
  connector('mcp:notion', 'Notion', ['read', 'write'], 'knowledge', 'preset'),
  connector('mcp:linear', 'Linear', ['read', 'write'], 'projects', 'preset'),
  connector('custom_mcp', 'MCP server', ['read'], 'custom', 'custom'),
];

type HeroState = {
  sourceDocs?: unknown[] | null;
  selectedDocs?: unknown[];
  conversations?: unknown[] | null;
  agents?: unknown[] | null;
  connections?: unknown[];
  tools?: unknown[];
  toolsLoaded?: boolean;
  availableModels?: unknown[];
};

const makeStore = ({
  sourceDocs = [],
  selectedDocs = [],
  conversations = [],
  agents = [],
  connections = [],
  tools = [],
  toolsLoaded = true,
  availableModels = [],
}: HeroState = {}) =>
  configureStore({
    reducer: {
      connectors: connectorsReducer,
      chatTools: chatToolsReducer,
      preference: (
        state = {
          token: null,
          selectedModel: null,
          availableModels,
          modelsLoading: false,
          sourceDocs,
          selectedDocs,
          conversations: { data: conversations, loading: false },
          agents,
        },
      ) => state,
    },
    preloadedState: {
      connectors: {
        enabled: true,
        loading: false,
        loaded: true,
        failed: false,
        catalog: CATALOG,
        connections,
      },
      chatTools: { tools, loaded: toolsLoaded },
    },
  } as Parameters<typeof configureStore>[0]);

describe('Hero suggestions', () => {
  let container: HTMLDivElement;
  let root: Root;
  const handleQuestion =
    vi.fn<(args: { question: string; isRetry?: boolean }) => void>();

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    handleQuestion.mockReset();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (state: HeroState = {}) => {
    await act(async () => {
      root.render(
        <Provider store={makeStore(state)}>
          <MemoryRouter initialEntries={['/']}>
            <Routes>
              <Route
                path="/"
                element={<Hero handleQuestion={handleQuestion} />}
              />
              <Route
                path="/settings/connectors"
                element={<div>CONNECTORS</div>}
              />
              <Route path="/c/:id" element={<div>CHAT</div>} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const rows = () =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-suggestion]'),
    );
  const rowKeys = () => rows().map((row) => row.dataset.suggestion);
  const rowFor = (key: string) =>
    container.querySelector<HTMLButtonElement>(`[data-suggestion="${key}"]`)!;

  it('offers setup steps on a fresh install, naming services with data', async () => {
    await render();
    expect(rowKeys()).toEqual(['add-knowledge', 'connect', 'create-agent']);
    // Not a web search or a messaging bot.
    // British English, like the rest of the app: no comma before "and".
    expect(rowFor('connect').textContent).toBe(
      'hero.suggestions.connect:Google Drive, Notion and hero.suggestions.more',
    );
    await act(async () => rowFor('connect').click());
    expect(container.textContent).toContain('CONNECTORS');
  });

  it('shows nothing until every list it reads has loaded', async () => {
    await render({ conversations: null });
    expect(rows()).toHaveLength(0);
    await act(async () => root.unmount());
    root = createRoot(container);
    await render({ toolsLoaded: false });
    expect(rows()).toHaveLength(0);
  });

  it('holds room for the most rows, so the logo stays put as they change', async () => {
    await render({ conversations: null });
    const slot = container.querySelector(
      '[data-testid="hero-suggestions-slot"]',
    );
    // Four md rows (40px each) at the bottom of the slot.
    expect(slot?.className.split(' ')).toEqual(
      expect.arrayContaining(['min-h-40', 'justify-end']),
    );
  });

  it('sends a question about the selected sources and opens a recent chat', async () => {
    const contracts = { id: 's1', name: 'Carrier Contracts 2026' };
    await render({
      sourceDocs: [contracts],
      selectedDocs: [contracts],
      conversations: [
        {
          id: 'c-1',
          name: 'Halvorsen QBR prep',
          agent_id: null,
          date: new Date().toISOString(),
        },
      ],
      agents: [{ id: 'a1' }],
      connections: [
        { id: 'conn-1', connector_key: 'brave', status: 'connected' },
      ],
    });
    expect(rowKeys()).toEqual(['summarize-s1', 'continue-c-1']);
    // The text wraps rather than cuts, so no row carries a title tooltip.
    expect(rowFor('summarize-s1').querySelector('[title]')).toBeNull();
    expect(rowFor('summarize-s1').getAttribute('title')).toBeNull();
    // Both end icons wait for hover or focus (shown on touch): an arrow up
    // sends, an arrow right opens.
    const trailing = (key: string) =>
      rowFor(key).querySelector('svg:last-of-type') as SVGElement;
    expect(trailing('summarize-s1').getAttribute('class')).toContain(
      'lucide-arrow-up',
    );
    expect(trailing('continue-c-1').getAttribute('class')).toContain(
      'lucide-arrow-right',
    );
    for (const key of ['summarize-s1', 'continue-c-1']) {
      expect(trailing(key).getAttribute('class')).toContain('opacity-0');
      expect(trailing(key).getAttribute('class')).toContain(
        'pointer-coarse:opacity-100',
      );
    }
    await act(async () => rowFor('summarize-s1').click());
    expect(handleQuestion).toHaveBeenCalledWith({
      question: 'hero.suggestions.summarize:Carrier Contracts 2026',
    });
    await act(async () => rowFor('continue-c-1').click());
    expect(container.textContent).toContain('CHAT');
  });

  it('asks about a service only while its tool is on in chat', async () => {
    const connections = [
      { id: 'conn-n', connector_key: 'mcp:notion', status: 'connected' },
    ];
    const notionTool = { id: 't1', connection_id: 'conn-n', status: true };
    await render({
      sourceDocs: [{ id: 's1', name: 'Handbook' }],
      agents: [{ id: 'a1' }],
      connections,
      tools: [notionTool],
    });
    expect(rowKeys()).toEqual(['service-mcp:notion']);
    expect(rowFor('service-mcp:notion').textContent).toBe(
      'hero.suggestions.service.knowledge:Notion',
    );
    await act(async () => root.unmount());
    root = createRoot(container);
    await render({
      sourceDocs: [{ id: 's1', name: 'Handbook' }],
      agents: [{ id: 'a1' }],
      connections,
      tools: [{ ...notionTool, status: false }],
    });
    expect(rows()).toHaveLength(0);
  });

  it('keeps the browser translator off the model picker', async () => {
    await render();
    // A translator that rewraps the picker's text breaks React's next
    // commit; model names are product names anyway.
    const trigger = container.querySelector('[data-slot="select-trigger"]');
    expect(trigger?.getAttribute('translate')).toBe('no');
  });
});

describe('Hero model picker', () => {
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

  const model = (id: string, source: 'builtin' | 'user' = 'builtin') => ({
    id,
    display_name: id,
    provider: 'openai',
    source,
  });

  const render = async (availableModels: unknown[]) => {
    const store = makeStore({ availableModels });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter>
            <Hero handleQuestion={vi.fn()} />
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const trigger = () =>
    container.querySelector<HTMLElement>('[data-slot="select-trigger"]')!;

  const open = async () => {
    await act(async () => {
      trigger().dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
  };

  const labels = () =>
    Array.from(document.querySelectorAll('[data-slot="select-label"]')).map(
      (el) => el.textContent,
    );

  it('is the stock pill select, like the outlined pills around it', async () => {
    await render([model('gpt-5.5')]);
    expect(trigger().dataset.shape).toBe('pill');
    expect(trigger().className).not.toContain('bg-muted');
    expect(trigger().className).not.toContain('rounded-4xl');
  });

  it('lists built-in models without headings when the user has none', async () => {
    await render([model('gpt-5.5'), model('glm-5.3')]);
    await open();
    expect(document.querySelectorAll('[data-slot="select-item"]')).toHaveLength(
      2,
    );
    expect(labels()).toEqual([]);
  });

  it('caps the menu so a long model list scrolls', async () => {
    await render([model('gpt-5.5')]);
    await open();
    const viewport = document.querySelector(
      '[data-slot="select-content"] [data-radix-select-viewport]',
    );
    expect(viewport?.className.split(' ')).toContain('max-h-75');
  });

  it('heads built-in and own models once the user has added one', async () => {
    await render([model('mine', 'user'), model('gpt-5.5')]);
    await open();
    expect(labels()).toEqual([
      'settings.customModels.modelsGroup.builtin',
      'settings.customModels.modelsGroup.user',
    ]);
    const items = Array.from(
      document.querySelectorAll('[data-slot="select-item"]'),
    ).map((el) => el.textContent);
    expect(items).toEqual(['gpt-5.5', 'mine']);
  });
});
