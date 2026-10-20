import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';

import examples from './insights/fixtures/apiExamples.json';

const store = vi.hoisted(() => ({
  state: {
    preference: { token: 'token', analyticsEnabled: true },
    activity: { now: null as object | null, revision: 0 },
  },
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(store.state),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));
vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useLoaderState: (initial: boolean) => useState(initial),
}));
vi.mock('../hooks/useLoadMore', () => ({
  useScrollSentinel: () => vi.fn(),
}));
vi.mock('./traces/TraceSheet', () => ({ default: () => null }));
vi.mock('../components/CopyButton', () => ({ default: () => null }));

const getLogs = vi.fn();
const getConfig = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    getLogs: (...args: unknown[]) => getLogs(...args),
    getConfig: () => getConfig(),
  },
}));

import Logs from './Logs';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const page = (body: object) => ({
  ok: true,
  json: () => Promise.resolve({ has_more: false, ...body }),
});

// The server's flag, as useDataInitializer puts it in Redux at start-up.
const config = (enabled: boolean) => {
  store.state.preference.analyticsEnabled = enabled;
};

/** The URL the app is on, so a test can see what the filters wrote. */
let currentUrl = '';
function Location() {
  const location = useLocation();
  currentUrl = `${location.pathname}${location.search}`;
  return null;
}

describe('Logs label filter and drill-down', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getLogs.mockReset();
    getLogs.mockResolvedValue(page(examples.logs));
    getConfig.mockReset();
    config(true);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    url: string,
    props: React.ComponentProps<typeof Logs> = {},
  ) => {
    await act(async () =>
      root.render(
        <MemoryRouter initialEntries={[url]}>
          <Logs {...props} />
          <Location />
        </MemoryRouter>,
      ),
    );
    // The first page settles.
    await act(async () => undefined);
  };

  const labelFilter = () =>
    container.querySelector('[data-testid="logs-label-filter"]');
  const lastRequest = () => getLogs.mock.calls.at(-1)![0];

  it('offers the label filter only while the server labels conversations', async () => {
    await render('/settings/logs');
    expect(labelFilter()).not.toBeNull();
    config(false);
    await act(async () => root.unmount());
    root = createRoot(container);
    await render('/settings/logs');
    expect(labelFilter()).toBeNull();
  });

  it('reads the flag from Redux, so the filter is there from the first paint', async () => {
    await act(async () =>
      root.render(
        <MemoryRouter initialEntries={['/settings/logs']}>
          <Logs />
        </MemoryRouter>,
      ),
    );
    expect(labelFilter()).not.toBeNull();
    expect(getConfig).not.toHaveBeenCalled();
  });

  it('names each filter, and lets each grow to its longest value', async () => {
    await render('/agents/manage/logs/a1', {
      agentId: 'a1',
      analytics: { enabled: true, tags: [] },
    });
    const triggers = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="select-trigger"]'),
    );
    expect(triggers.map((el) => el.getAttribute('aria-label'))).toEqual([
      'settings.logs.levelFilter',
      'settings.logs.typeFilter',
      'settings.logs.labels.filter',
    ]);
    for (const el of triggers) {
      const classes = el.className.split(' ');
      expect(classes.some((c) => /^w-\[/.test(c))).toBe(false);
      expect(classes.some((c) => /^min-w-\[/.test(c))).toBe(true);
    }
  });

  it('opens a label menu at least as wide as its trigger, as wide as its longest label', async () => {
    await render('/settings/logs');
    const trigger = labelFilter() as HTMLElement;
    await act(async () => {
      trigger.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    const menu = document.querySelector<HTMLElement>(
      '[data-slot="select-content"]',
    )!;
    expect(menu).not.toBeNull();
    const classes = menu.className.split(' ');
    expect(classes).toContain('w-auto');
    expect(classes).toContain('min-w-(--radix-select-trigger-width)');
    expect(classes).not.toContain('w-(--radix-select-trigger-width)');
  });

  it("hides it on an agent's Logs while the agent has analytics off", async () => {
    await render('/agents/manage/logs/a1', {
      agentId: 'a1',
      analytics: { enabled: false, tags: [] },
    });
    expect(labelFilter()).toBeNull();
    await render('/agents/manage/logs/a1', {
      agentId: 'a1',
      analytics: { enabled: true, tags: [] },
    });
    expect(labelFilter()).not.toBeNull();
  });

  it('keeps a label from a link shown, so it can be cleared, and sends it', async () => {
    config(false);
    await render('/settings/logs?label=docs_gap');
    expect(labelFilter()).not.toBeNull();
    expect(lastRequest().label).toBe('docs_gap');
    expect(container.textContent).toContain('settings.logs.labels.hint');
  });

  it('ignores a label the API would refuse', async () => {
    await render('/settings/logs?label=sentiment');
    expect(lastRequest().label).toBeUndefined();
    expect(container.textContent).not.toContain('settings.logs.labels.hint');
  });

  it('narrows to a conversation from the URL, with a chip that clears it', async () => {
    await render(
      '/settings/logs?conversation=a16e1e68-3cce-49a9-b05c-f97807748cd3&message=9a4d5bf9-0191-4e54-8de4-aa3f4704d0c1',
    );
    expect(lastRequest().conversation_id).toBe(
      'a16e1e68-3cce-49a9-b05c-f97807748cd3',
    );
    const chip = container.querySelector(
      '[data-testid="logs-conversation-chip"]',
    )!;
    expect(chip.textContent).toContain('settings.logs.labels.conversation');
    const id = chip.querySelector<HTMLElement>('.font-mono')!;
    expect(id.textContent).toBe('a16e1e68');
    expect(id.title).toBe('a16e1e68-3cce-49a9-b05c-f97807748cd3');
    const clear = chip.querySelector<HTMLButtonElement>(
      'button[aria-label="settings.logs.labels.clearConversation"]',
    )!;
    await act(async () => clear.click());
    await act(async () => undefined);
    expect(currentUrl).toBe('/settings/logs');
    expect(lastRequest().conversation_id).toBeUndefined();
    expect(
      container.querySelector('[data-testid="logs-conversation-chip"]'),
    ).toBeNull();
  });

  it('opens the linked message once its row loads', async () => {
    await render(
      '/settings/logs?conversation=a16e1e68-3cce-49a9-b05c-f97807748cd3&message=9a4d5bf9-0191-4e54-8de4-aa3f4704d0c1',
    );
    const toggle = container.querySelector<HTMLButtonElement>(
      '[data-log-id="chat-2"] button[aria-expanded]',
    )!;
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    // Closing it is the user's choice: it stays closed.
    await act(async () => toggle.click());
    await act(async () => undefined);
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
  });

  it("puts the row's labels in its header, tags named by the page's tag_names", async () => {
    await render('/settings/logs');
    const header = container.querySelector(
      '[data-log-id="chat-2"] button[aria-expanded]',
    )!;
    const chips = Array.from(
      header.querySelectorAll<HTMLElement>('[data-slot="badge"]'),
    );
    expect(chips.slice(0, 3).map((chip) => chip.textContent)).toEqual([
      'settings.logs.labels.docsGap',
      'settings.logs.labels.negativeReaction',
      'settings.logs.labels.frustrated',
    ]);
    // The fourth folds into "+1", which names it for screen readers.
    expect(chips[3].textContent).toBe(
      'settings.logs.labels.morePricing question',
    );
    expect(chips[3].hasAttribute('title')).toBe(false);
    // Their own line under the one-line header, in the UI font; the header
    // column spaces it, not a margin passed in.
    const line = header.querySelector<HTMLElement>(
      '[data-testid="label-chips"]',
    )!;
    expect(line.className).toContain('font-sans');
    expect(line.className.split(' ')).not.toContain('mt-1');
    expect(line.parentElement!.className).toContain('flex-col');
    expect(line.parentElement!.className.split(' ')).toContain('gap-1');
    expect(line.previousElementSibling!.textContent).toContain('q');
  });

  it('says no message matches instead of no logs while drilled down', async () => {
    getLogs.mockResolvedValue(page({ logs: [] }));
    await render('/settings/logs?label=frustrated');
    expect(container.textContent).toContain(
      'settings.logs.labels.emptyForFilter',
    );
    expect(container.textContent).not.toContain('settings.logs.noLogs');
  });
});
