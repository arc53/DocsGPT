import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const { interpolation: _i, ...rest } = opts ?? {};
      void _i;
      return Object.keys(rest).length ? `${key}:${JSON.stringify(rest)}` : key;
    },
  }),
}));

// The menu is a Radix dropdown; the tests only need its options.
vi.mock('../components/ui/dropdown-menu', () => ({
  ActionMenu: ({
    options,
  }: {
    options: { label: string; onClick: () => void }[];
  }) => (
    <div data-testid="menu">
      {options.map((o) => (
        <button key={o.label} type="button" onClick={o.onClick}>
          {o.label}
        </button>
      ))}
    </div>
  ),
}));

const service = vi.hoisted(() => ({
  getPrompts: vi.fn(),
  deletePrompt: vi.fn(),
  updatePrompt: vi.fn(),
  createPrompt: vi.fn(),
  getSinglePrompt: vi.fn(),
  getPreferences: vi.fn(),
  updatePreferences: vi.fn(),
  getUserTools: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: service }));

// The drawer docks beside the page on a desktop.
vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

const drafter = vi.hoisted(() => ({
  config: null as null | { enabled: boolean },
  scripts: [] as DrafterEvent[][],
  requests: [] as DrafterRequest[],
}));
vi.mock('../drafter/useDrafterConfig', () => ({
  useDrafterConfig: () => drafter.config,
}));
vi.mock('../drafter/drafterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../drafter/drafterApi')>()),
  streamDrafter: async (
    request: DrafterRequest,
    _token: string | null,
    onEvent: (event: DrafterEvent) => void,
  ) => {
    drafter.requests.push(JSON.parse(JSON.stringify(request)));
    (drafter.scripts.shift() ?? [{ type: 'end' }]).forEach(onEvent);
  },
}));

const confirm = vi.hoisted(() => ({
  props: null as null | {
    message: string;
    description?: string;
    error?: string | ((reason: unknown) => string);
    handleSubmit: () => void | Promise<unknown>;
    handleCancel?: () => void;
  },
}));
vi.mock('../modals/ConfirmationModal', () => ({
  default: (props: NonNullable<typeof confirm.props>) => {
    confirm.props = props;
    return null;
  },
}));
const promptsModalProps = vi.fn();
vi.mock('../preferences/PromptsModal', () => ({
  default: (props: { modalState: string }) => {
    promptsModalProps(props);
    return null;
  },
}));
const shareModalProps = vi.fn();
vi.mock('../teams/ShareToTeamModal', () => ({
  default: (props: unknown) => {
    shareModalProps(props);
    return null;
  },
}));

import type { DrafterEvent, DrafterRequest } from '../drafter/drafterApi';
import actionToastReducer from '../notifications/actionToastSlice';
import preferenceReducer, {
  setPrompt,
  setToken,
} from '../preferences/preferenceSlice';
import Prompts from './Prompts';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const response = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

const OWNER_ACTIONS = ['delete', 'duplicate', 'edit', 'share', 'use'];
const presets = [
  {
    id: 'default',
    name: 'default',
    type: 'public',
    used_by: { agents: [{ id: 'a1', name: 'Docs', agent_type: 'classic' }] },
  },
  { id: 'creative', name: 'creative', type: 'public', used_by: null },
  { id: 'strict', name: 'strict', type: 'public', used_by: null },
];
const own = {
  id: 'p-own',
  name: 'Vendor checks',
  type: 'private',
  preview: 'You check vendors before onboarding.',
  access: 'owner',
  allowed_actions: OWNER_ACTIONS,
  used_by: {
    agents: [{ id: 'a2', name: 'Procurement', agent_type: 'classic' }],
    others: 1,
  },
};
const idle = {
  id: 'p-idle',
  name: 'Escalation summary',
  type: 'private',
  preview: 'Summarise for tier 2.',
  access: 'owner',
  allowed_actions: OWNER_ACTIONS,
  used_by: { agents: [], others: 0 },
};
const viewer = {
  id: 'p-team',
  name: 'Deal desk',
  type: 'team',
  team_access: 'viewer',
  preview: 'Brief the rep.',
  access: 'viewer',
  allowed_actions: ['use', 'duplicate'],
  used_by: { agents: [], others: 0 },
};
const listed = [...presets, own, idle, viewer];

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.search}</div>;
}

describe('Prompts page', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  const makeStore = () =>
    configureStore({
      reducer: {
        preference: preferenceReducer,
        actionToast: actionToastReducer,
      },
    });

  beforeEach(() => {
    Object.values(service).forEach((fn) => fn.mockReset());
    service.getPrompts.mockImplementation(() => response(listed));
    service.updatePreferences.mockImplementation(() =>
      response({ success: true }),
    );
    service.getUserTools.mockImplementation(() => response({ success: false }));
    drafter.config = null;
    drafter.scripts = [];
    drafter.requests = [];
    promptsModalProps.mockReset();
    shareModalProps.mockReset();
    confirm.props = null;
    store = makeStore();
    store.dispatch(setToken('tok'));
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = (entry = '/settings/prompts') =>
    act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={[entry]}>
            <Routes>
              <Route
                path="/settings/prompts"
                element={
                  <>
                    <Prompts />
                    <Where />
                  </>
                }
              />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });

  const cards = () =>
    Array.from(container.querySelectorAll<HTMLElement>('[data-slot="card"]'));
  const card = (name: string) =>
    cards().find(
      (c) => c.querySelector('[data-slot="card-title"]')?.textContent === name,
    )!;
  const titles = () =>
    cards().map(
      (c) => c.querySelector('[data-slot="card-title"]')?.textContent,
    );
  const radioOf = (name: string) =>
    card(name).querySelector<HTMLButtonElement>('[role="radio"]')!;
  const menuLabels = (name: string) =>
    Array.from(card(name).querySelectorAll('[data-testid="menu"] button')).map(
      (b) => b.textContent,
    );
  const clickMenu = (name: string, label: string) =>
    act(async () =>
      Array.from(
        card(name).querySelectorAll<HTMLButtonElement>(
          '[data-testid="menu"] button',
        ),
      )
        .find((b) => b.textContent === label)!
        .click(),
    );
  const chatPromptId = () => store.getState().preference.prompt.id;

  it('lists Included, Yours and Shared with team as filled cards', async () => {
    await render();
    const headings = Array.from(container.querySelectorAll('h2')).map(
      (h) => h.textContent,
    );
    // Each heading carries its count.
    expect(headings).toEqual([
      'settings.prompts.sections.included3',
      'settings.prompts.sections.yours2',
      'settings.prompts.sections.shared1',
    ]);
    expect(titles()).toEqual([
      'default',
      'creative',
      'strict',
      'Vendor checks',
      'Escalation summary',
      'Deal desk',
    ]);
    for (const c of cards())
      expect(c.getAttribute('data-variant')).toBe('filled');
    // A preset says what it does; a prompt of yours shows its start.
    expect(card('strict').textContent).toContain(
      'settings.prompts.presets.strict',
    );
    expect(card('Vendor checks').textContent).toContain(
      'You check vendors before onboarding.',
    );
    // The role is a fact in the meta line, not a pill.
    expect(
      card('Deal desk').querySelector(
        '[data-slot="card-footer"] [data-testid="role-meta"]',
      ),
    ).not.toBeNull();
  });

  it('says which agents use a prompt and marks the chat prompt', async () => {
    store.dispatch(setPrompt({ id: 'p-own', name: 'x', type: 'private' }));
    await render();
    expect(card('Vendor checks').textContent).toContain(
      'settings.usage.agentsShort:{"count":2,"formatted":"2"}',
    );
    // The radio says it is the chat prompt; no badge repeats it.
    expect(card('Vendor checks').textContent).not.toContain(
      'settings.usage.inChats',
    );
    expect(
      card('Vendor checks').querySelector('[data-slot="badge"]'),
    ).toBeNull();
    expect(radioOf('Vendor checks').getAttribute('aria-checked')).toBe('true');
    expect(radioOf('default').getAttribute('aria-checked')).toBe('false');
  });

  it('keeps the radio state for its look under the tooltip', async () => {
    store.dispatch(setPrompt({ id: 'p-own', name: 'x', type: 'private' }));
    await render();
    expect(radioOf('Vendor checks').dataset.state).toBe('checked');
    expect(radioOf('default').dataset.state).toBe('unchecked');
  });

  it('has one radio group across the sections, each radio named', async () => {
    await render();
    const group = container.querySelector(
      '[aria-label="settings.prompts.chatPromptLabel"]',
    )!;
    expect(group.getAttribute('role')).toBe('radiogroup');
    expect(group.querySelectorAll('[role="radio"]')).toHaveLength(6);
    for (const c of cards())
      expect(c.querySelectorAll('[role="radio"]')).toHaveLength(1);
    expect(radioOf('strict').getAttribute('aria-label')).toBe(
      'settings.prompts.useInChats:{"name":"strict"}',
    );
  });

  it('saves the picked radio as the chat prompt on the server', async () => {
    await render();
    await act(async () => radioOf('Escalation summary').click());
    expect(service.updatePreferences).toHaveBeenCalledWith(
      { chat_prompt_id: 'p-idle' },
      'tok',
    );
    expect(chatPromptId()).toBe('p-idle');
    expect(radioOf('Escalation summary').getAttribute('aria-checked')).toBe(
      'true',
    );
  });

  // Arrow keys check each card they pass; only where the user stops saves.
  it('saves once after arrow keys stop, not per card', async () => {
    await render();
    vi.useFakeTimers();
    try {
      for (const key of ['ArrowDown', 'ArrowDown']) {
        const focused = document.activeElement?.matches('[role="radio"]')
          ? (document.activeElement as HTMLElement)
          : radioOf('default');
        await act(async () => {
          focused.focus();
          focused.dispatchEvent(
            new KeyboardEvent('keydown', { key, bubbles: true }),
          );
          await vi.advanceTimersByTimeAsync(0);
        });
      }
      expect(chatPromptId()).toBe('strict');
      expect(service.updatePreferences).not.toHaveBeenCalled();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(service.updatePreferences).toHaveBeenCalledTimes(1);
      expect(service.updatePreferences).toHaveBeenCalledWith(
        { chat_prompt_id: 'strict' },
        'tok',
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('switches the radio back and shows an error when the save fails', async () => {
    service.updatePreferences.mockImplementation(() =>
      response({}, false, 500),
    );
    await render();
    await act(async () => radioOf('creative').click());
    expect(chatPromptId()).toBe('default');
    expect(radioOf('default').getAttribute('aria-checked')).toBe('true');
    expect(store.getState().actionToast.current).toMatchObject({
      variant: 'destructive',
      message: 'settings.prompts.chatPromptFailed',
    });
  });

  it('gives a preset View and Duplicate, your own Edit, Duplicate, Share and Delete', async () => {
    await render();
    expect(menuLabels('default')).toEqual([
      'settings.prompts.view',
      'settings.prompts.duplicate',
    ]);
    expect(menuLabels('Vendor checks')).toEqual([
      'settings.prompts.edit',
      'settings.prompts.duplicate',
      'settings.prompts.shareWithTeam',
      'settings.prompts.delete',
    ]);
    expect(menuLabels('Deal desk')).toEqual([
      'settings.prompts.view',
      'settings.prompts.duplicate',
    ]);
  });

  it('opens the share dialog for your own prompt', async () => {
    await render();
    await clickMenu('Vendor checks', 'settings.prompts.shareWithTeam');
    expect(shareModalProps.mock.calls.at(-1)![0]).toMatchObject({
      resourceType: 'prompt',
      resourceId: 'p-own',
      resourceName: 'Vendor checks',
    });
  });

  it('filters by use, the chat prompt counting as in use', async () => {
    store.dispatch(setPrompt({ id: 'p-idle', name: 'x', type: 'private' }));
    await render('/settings/prompts?usage=inUse');
    expect(titles()).toEqual([
      'default',
      'Vendor checks',
      'Escalation summary',
    ]);
  });

  it('lists the prompts nothing uses under Unused', async () => {
    store.dispatch(setPrompt({ id: 'p-idle', name: 'x', type: 'private' }));
    await render('/settings/prompts?usage=unused');
    expect(titles()).toEqual(['creative', 'strict', 'Deal desk']);
  });

  const search = (term: string) =>
    act(async () => {
      const input = container.querySelector<HTMLInputElement>(
        '#prompt-search-input',
      )!;
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!.call(input, term);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

  // Picking a prompt makes it in use; under Unused its card stays until
  // the search or filter changes, as a Tools tile does.
  it('keeps a card picked under Unused until the search changes', async () => {
    await render('/settings/prompts?usage=unused');
    expect(titles()).toEqual([
      'creative',
      'strict',
      'Escalation summary',
      'Deal desk',
    ]);
    await act(async () => radioOf('creative').click());
    expect(chatPromptId()).toBe('creative');
    expect(titles()).toEqual([
      'creative',
      'strict',
      'Escalation summary',
      'Deal desk',
    ]);
    await search('e');
    expect(titles()).toEqual(['Escalation summary', 'Deal desk']);
    // Back on the first search, the held usage is gone for good.
    await search('');
    expect(titles()).toEqual(['strict', 'Escalation summary', 'Deal desk']);
  });

  // Each arrow key moves the check; the focused radio's card must stay.
  it('keeps the focused card while arrow keys move the pick under Unused', async () => {
    await render('/settings/prompts?usage=unused');
    vi.useFakeTimers();
    try {
      const from = radioOf('creative');
      await act(async () => {
        from.focus();
        from.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }),
        );
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(chatPromptId()).toBe('strict');
      expect(titles()).toEqual([
        'creative',
        'strict',
        'Escalation summary',
        'Deal desk',
      ]);
      expect(document.activeElement).toBe(radioOf('strict'));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps the card the pick left under In use', async () => {
    store.dispatch(setPrompt({ id: 'p-idle', name: 'x', type: 'private' }));
    await render('/settings/prompts?usage=inUse');
    await act(async () => radioOf('default').click());
    expect(chatPromptId()).toBe('default');
    expect(titles()).toEqual([
      'default',
      'Vendor checks',
      'Escalation summary',
    ]);
  });

  it('filters by kind with a track that keeps it in the address', async () => {
    await render();
    const items = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[aria-label="settings.prompts.kindFilterLabel"] [data-slot="toggle-group-item"]',
      ),
    );
    expect(items.map((b) => b.firstChild?.textContent)).toEqual([
      'settings.prompts.filters.all',
      'settings.prompts.sections.included',
      'settings.prompts.sections.yours',
      'settings.prompts.kinds.shared',
    ]);
    await act(async () => items[2].click());
    expect(container.querySelector('[data-testid="where"]')!.textContent).toBe(
      '?kind=yours',
    );
    expect(titles()).toEqual(['Vendor checks', 'Escalation summary']);
  });

  // DESIGN "No item leads to an empty list": the counts follow the search.
  it('counts each kind within the search, offering none it would empty', async () => {
    await render();
    // creative, strict, Vendor checks and Escalation summary; no shared one.
    await search('c');
    const items = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[aria-label="settings.prompts.kindFilterLabel"] [data-slot="toggle-group-item"]',
      ),
    );
    expect(
      items.map(
        (b) =>
          `${b.firstChild?.textContent} ${b.querySelector('[data-slot="count"]')?.textContent}`,
      ),
    ).toEqual([
      'settings.prompts.filters.all 4',
      'settings.prompts.sections.included 2',
      'settings.prompts.sections.yours 2',
    ]);
  });

  it('puts usage in a pill Select that reads Any use', async () => {
    await render();
    const trigger = container.querySelector<HTMLElement>(
      '[data-slot="select-trigger"][aria-label="settings.usage.filterLabel"]',
    )!;
    expect(trigger.getAttribute('data-shape')).toBe('pill');
    expect(trigger.textContent).toBe('settings.usage.filters.all');
  });

  it('says when a search matches nothing', async () => {
    await render();
    const input = container.querySelector<HTMLInputElement>(
      '#prompt-search-input',
    )!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!.call(input, 'zzz');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(cards()).toHaveLength(0);
    expect(container.textContent).toContain('settings.prompts.noPromptsFound');
  });

  it('shows a failed load as an error with Retry', async () => {
    service.getPrompts.mockImplementation(() => response({}, false, 500));
    await render();
    const alert = container.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('settings.prompts.loadError');
    service.getPrompts.mockImplementation(() => response(listed));
    await act(async () =>
      Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
        .find((b) => b.textContent === 'retry')!
        .click(),
    );
    expect(titles()).toContain('Vendor checks');
  });

  it('names the usage in the delete confirm', async () => {
    store.dispatch(setPrompt({ id: 'p-own', name: 'x', type: 'private' }));
    await render();
    await clickMenu('Vendor checks', 'settings.prompts.delete');
    expect(confirm.props!.message).toBe(
      'modals.prompts.deleteConfirmation:{"name":"Vendor checks"}',
    );
    expect(confirm.props!.description).toBe(
      'settings.prompts.deleteUsedByInChats:{"count":2,"formatted":"2"}',
    );
  });

  it('says only that it cannot be undone for an unused prompt', async () => {
    await render();
    await clickMenu('Escalation summary', 'settings.prompts.delete');
    expect(confirm.props!.description).toBe('common.cantUndo');
  });

  // The server reads a deleted chat prompt back as default, so a later
  // failed pick switches back to default, not to the deleted prompt.
  it('switches back to default after the saved chat prompt was deleted', async () => {
    service.deletePrompt.mockImplementation(() => response({ success: true }));
    await render();
    await act(async () => radioOf('Escalation summary').click());
    expect(chatPromptId()).toBe('p-idle');
    await clickMenu('Escalation summary', 'settings.prompts.delete');
    await act(async () => {
      await confirm.props!.handleSubmit();
    });
    service.updatePreferences.mockImplementation(() =>
      response({}, false, 500),
    );
    await act(async () => radioOf('creative').click());
    expect(chatPromptId()).toBe('default');
    expect(radioOf('default').getAttribute('aria-checked')).toBe('true');
  });

  // An arrow key in a card's ⋯ menu is no radio move: a click after it
  // saves at once.
  it('saves a click at once after an arrow key outside the radios', async () => {
    await render();
    vi.useFakeTimers();
    try {
      const menuButton = card('Vendor checks').querySelector<HTMLElement>(
        '[data-testid="menu"] button',
      )!;
      await act(async () => {
        menuButton.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }),
        );
      });
      await act(async () => {
        radioOf('creative').click();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(service.updatePreferences).toHaveBeenCalledWith(
        { chat_prompt_id: 'creative' },
        'tok',
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('falls back to default when the chat prompt is deleted', async () => {
    store.dispatch(setPrompt({ id: 'p-idle', name: 'x', type: 'private' }));
    service.deletePrompt.mockImplementation(() => response({ success: true }));
    await render();
    await clickMenu('Escalation summary', 'settings.prompts.delete');
    expect(confirm.props!.description).toBe('settings.prompts.deleteInChats');
    await act(async () => {
      await confirm.props!.handleSubmit();
    });
    expect(service.deletePrompt).toHaveBeenCalledWith({ id: 'p-idle' }, 'tok');
    expect(titles()).not.toContain('Escalation summary');
    expect(chatPromptId()).toBe('default');
    expect(radioOf('default').getAttribute('aria-checked')).toBe('true');
  });

  it('keeps the card and rejects when the delete fails', async () => {
    service.deletePrompt.mockImplementation(() => response({}, false, 403));
    await render();
    await clickMenu('Escalation summary', 'settings.prompts.delete');
    let result: void | Promise<unknown> = undefined;
    await act(async () => {
      result = confirm.props!.handleSubmit();
      (result as Promise<unknown>).catch(() => undefined);
    });
    await expect(result).rejects.toThrow();
    expect(confirm.props!.error).toBe('settings.prompts.deleteFailed');
    expect(titles()).toContain('Escalation summary');
  });

  // ---- An open prompt: the detail view in place of the list ----

  const view = () =>
    container.querySelector<HTMLElement>('[data-slot="prompt-view"]');
  const buttons = (root: ParentNode = container) =>
    Array.from(root.querySelectorAll<HTMLButtonElement>('button'));
  const button = (text: string, root: ParentNode = container) =>
    buttons(root).find((b) => b.textContent === text);
  const click = (target: HTMLElement) =>
    act(async () => {
      target.click();
    });
  const openCard = (name: string) =>
    click(
      card(name).querySelector<HTMLButtonElement>('button[type="button"]')!,
    );
  const nameInput = () =>
    view()!.querySelector<HTMLInputElement>('input[type="text"]')!;
  const textArea = () => view()!.querySelector<HTMLTextAreaElement>('textarea');
  const type = (field: HTMLInputElement | HTMLTextAreaElement, value: string) =>
    act(async () => {
      const proto =
        field instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(field, value);
      field.dispatchEvent(new Event('input', { bubbles: true }));
    });
  const crumbs = () =>
    Array.from(view()!.querySelectorAll('[data-slot="breadcrumb"] li'))
      .map((li) => li.textContent)
      // The separators are items too.
      .filter(Boolean);
  const viewMenu = () =>
    Array.from(view()!.querySelectorAll('[data-testid="menu"] button')).map(
      (b) => b.textContent,
    );
  const save = () => button('modals.prompts.save', view()!)!;
  const panel = () =>
    container.querySelector<HTMLElement>('[data-slot="side-panel"]');

  const withText = (content: string, updatedAt = 'v1') =>
    service.getSinglePrompt.mockImplementation(() =>
      response({ content, updated_at: updatedAt }),
    );

  it('opens a prompt as a view in place of the list, not in the modal', async () => {
    withText('You check vendors.');
    await render();
    await openCard('Vendor checks');
    expect(service.getSinglePrompt).toHaveBeenCalledWith('p-own', 'tok');
    expect(cards()).toHaveLength(0);
    expect(crumbs()).toEqual(['settings.prompts.label', 'Vendor checks']);
    expect(nameInput().value).toBe('Vendor checks');
    expect(textArea()!.value).toBe('You check vendors.');
    // The byline names the agents using it; the ⋯ is the card's less Edit.
    expect(view()!.textContent).toContain(
      'settings.usage.agentsShort:{"count":2,"formatted":"2"}',
    );
    expect(viewMenu()).toEqual([
      'settings.prompts.duplicate',
      'settings.prompts.shareWithTeam',
      'settings.prompts.delete',
    ]);
    expect(promptsModalProps).not.toHaveBeenCalled();
  });

  it("opens a viewer's prompt read-only with no Save", async () => {
    withText('Brief the rep.');
    await render();
    await openCard('Deal desk');
    expect(nameInput().disabled).toBe(true);
    expect(textArea()!.readOnly).toBe(true);
    expect(save()).toBeUndefined();
    expect(view()!.textContent).toContain('common.viewOnlyNotice');
    expect(viewMenu()).toEqual(['settings.prompts.duplicate']);
  });

  it('says a built-in prompt is read-only in its byline', async () => {
    withText('You are DocsGPT.');
    await render();
    await openCard('default');
    expect(view()!.textContent).toContain('modals.prompts.viewDescription');
    expect(view()!.textContent).not.toContain('common.viewOnlyNotice');
    expect(save()).toBeUndefined();
  });

  it('shows a failed load as an error with Retry', async () => {
    service.getSinglePrompt.mockImplementation(() => response({}, false, 500));
    await render();
    await openCard('Vendor checks');
    expect(view()!.textContent).toContain('settings.prompts.loadPromptError');
    expect(textArea()).toBeNull();
    withText('You check vendors.');
    await click(button('retry', view()!)!);
    expect(textArea()!.value).toBe('You check vendors.');
  });

  it('saves an edit at its version and goes back to the list', async () => {
    withText('You check vendors.');
    service.updatePrompt.mockImplementation(() => response({ success: true }));
    await render();
    await openCard('Vendor checks');
    await type(textArea()!, 'You check vendors twice.');
    await click(save());
    expect(service.updatePrompt).toHaveBeenCalledWith(
      {
        id: 'p-own',
        name: 'Vendor checks',
        content: 'You check vendors twice.',
        expected_updated_at: 'v1',
      },
      'tok',
    );
    expect(view()).toBeNull();
    expect(titles()).toContain('Vendor checks');
    expect(service.getPrompts).toHaveBeenCalledTimes(2);
  });

  it('stays on the prompt and says so when someone else changed it', async () => {
    withText('You check vendors.');
    service.updatePrompt.mockImplementation(() => response({}, false, 409));
    await render();
    await openCard('Vendor checks');
    await type(textArea()!, 'Changed.');
    await click(save());
    expect(view()).not.toBeNull();
    expect(store.getState().actionToast.current).toMatchObject({
      variant: 'destructive',
      message: 'settings.prompts.editConflict',
    });
  });

  it('adds a prompt from an empty view, refusing a name already taken', async () => {
    service.createPrompt.mockImplementation(() => response({ id: 'p-new' }));
    await render();
    await click(button('settings.prompts.addPrompt')!);
    expect(crumbs()).toEqual([
      'settings.prompts.label',
      'modals.prompts.addPrompt',
    ]);
    expect(save().disabled).toBe(true);
    await type(nameInput(), 'Vendor checks');
    await type(textArea()!, 'Hello.');
    expect(save().disabled).toBe(true);
    expect(view()!.textContent).toContain('modals.prompts.nameExists');
    await type(nameInput(), 'Greeter');
    expect(save().disabled).toBe(false);
    await click(save());
    expect(service.createPrompt).toHaveBeenCalledWith(
      { name: 'Greeter', content: 'Hello.' },
      'tok',
    );
    expect(view()).toBeNull();
  });

  it('opens a copy named after the prompt from Duplicate', async () => {
    withText('You check vendors.');
    await render();
    await clickMenu('Vendor checks', 'settings.prompts.duplicate');
    expect(crumbs()).toEqual([
      'settings.prompts.label',
      'modals.prompts.duplicatePrompt',
    ]);
    expect(nameInput().value).toBe('Vendor checks copy');
    expect(textArea()!.value).toBe('You check vendors.');
    expect(view()!.textContent).toContain(
      'modals.prompts.duplicateDescription:{"name":"Vendor checks"}',
    );
  });

  it('asks before the crumb leaves unsaved changes', async () => {
    withText('You check vendors.');
    await render();
    await openCard('Vendor checks');
    // Nothing changed: the crumb goes straight back.
    await click(button('settings.prompts.label', view()!)!);
    expect(view()).toBeNull();
    expect(confirm.props).toBeNull();

    await openCard('Vendor checks');
    await type(textArea()!, 'Changed.');
    await click(button('settings.prompts.label', view()!)!);
    expect(view()).not.toBeNull();
    expect(confirm.props!.message).toBe('settings.prompts.unsavedChanges');
    await act(async () => confirm.props!.handleCancel!());
    expect(view()).toBeNull();
  });

  it('saves and leaves from the unsaved-changes confirm', async () => {
    withText('You check vendors.');
    service.updatePrompt.mockImplementation(() => response({}, false, 409));
    await render();
    await openCard('Vendor checks');
    await type(textArea()!, 'Changed.');
    await click(button('settings.prompts.label', view()!)!);
    let result: void | Promise<unknown> = undefined;
    await act(async () => {
      result = confirm.props!.handleSubmit();
      (result as Promise<unknown>).catch(() => undefined);
    });
    // A refused save stays in the confirm, not a toast as well.
    await expect(result).rejects.toThrow('conflict');
    const error = confirm.props!.error as (reason: unknown) => string;
    expect(error(new Error('conflict'))).toBe('settings.prompts.editConflict');
    expect(store.getState().actionToast.current).toBeNull();
    expect(view()).not.toBeNull();
  });

  // ---- The drafter's drawer ----

  const IMPROVE = {
    mode: 'improve',
    message: 'Tightened the vendor rule.',
    edits: [
      {
        id: 'e1',
        find: 'You check vendors.',
        replace: 'You check every vendor.',
        reason: 'Clearer.',
      },
    ],
    result: 'You check every vendor.',
    template_mode: { before: false, after: false },
    warnings: ['Mind the tone.'],
    checks: ['boundaries_removed'],
  };
  const proposal = (payload: object): DrafterEvent[] => [
    { type: 'status', step: 'drafting' },
    { type: 'proposal', proposal: payload },
    { type: 'end' },
  ];

  it('leaves the drafter out while it is off', async () => {
    withText('You check vendors.');
    await render();
    await openCard('Vendor checks');
    expect(button('drafter.improve', view()!)).toBeUndefined();
    expect(panel()).toBeNull();
  });

  it('opens the drawer beside the view from Improve', async () => {
    drafter.config = { enabled: true };
    withText('You check vendors.');
    await render();
    await openCard('Vendor checks');
    const improve = button('drafter.improve', view()!)!;
    expect(improve.getAttribute('aria-expanded')).toBe('false');
    expect(panel()).toBeNull();
    await click(improve);
    expect(improve.getAttribute('aria-expanded')).toBe('true');
    // Docked: the panel is the view's sibling, not inside its scroller.
    expect(panel()!.contains(view())).toBe(false);
    expect(panel()!.textContent).toContain(
      'drafter.prompt.introImproveUsedBy:{"count":2,"formatted":"2"}',
    );
    expect(
      Array.from(panel()!.querySelectorAll('[data-suggestion]')).map((b) =>
        b.getAttribute('data-suggestion'),
      ),
    ).toEqual(['lookOver', 'noPrices', 'language']);
  });

  it('offers Write on an empty new prompt', async () => {
    drafter.config = { enabled: true };
    await render();
    await click(button('settings.prompts.addPrompt')!);
    await click(button('drafter.prompt.write', view()!)!);
    expect(panel()!.textContent).toContain('drafter.prompt.introWrite');
  });

  it('reviews an improvement inline and finishes it from the drawer', async () => {
    drafter.config = { enabled: true };
    drafter.scripts = [proposal(IMPROVE)];
    withText('You check vendors.');
    await render();
    await openCard('Vendor checks');
    await click(button('drafter.improve', view()!)!);
    await click(
      panel()!.querySelector<HTMLButtonElement>(
        '[data-suggestion="lookOver"]',
      )!,
    );
    expect(drafter.requests[0]).toMatchObject({
      recipe: 'prompt',
      messages: [
        { role: 'user', content: 'drafter.prompt.suggestions.lookOver' },
      ],
      context: {
        mode: 'improve',
        prompt: { id: 'p-own', name: 'Vendor checks' },
        agent: null,
      },
    });
    // The changes are in the editor with their Accept and Reject; the
    // message and what to check are the drawer's turn.
    expect(view()!.querySelector('[data-slot="prompt-review"]')).not.toBeNull();
    expect(
      view()!.querySelector('[data-slot="prompt-draft-warnings"]'),
    ).toBeNull();
    expect(panel()!.textContent).toContain('Tightened the vendor rule.');
    const warnings = panel()!.querySelector(
      '[data-slot="prompt-draft-warnings"]',
    )!;
    expect(warnings.textContent).toContain(
      'drafter.prompt.checks.boundaries_removed',
    );
    expect(warnings.textContent).toContain('Mind the tone.');
    expect(save().disabled).toBe(true);
    expect(
      buttons(panel()!)
        .map((b) => b.textContent)
        .filter((text) => text?.startsWith('drafter.prompt.')),
    ).toEqual([
      'drafter.prompt.acceptAll',
      'drafter.prompt.reviewOneByOne',
      'drafter.prompt.discard',
    ]);
    await click(button('drafter.prompt.acceptAll', panel()!)!);
    expect(textArea()!.value).toBe('You check every vendor.');
    expect(button('drafter.prompt.acceptAll', panel()!)).toBeUndefined();
    expect(save().disabled).toBe(false);
  });

  it('ends an open review with the choices so far when a new request goes', async () => {
    drafter.config = { enabled: true };
    drafter.scripts = [proposal(IMPROVE), [{ type: 'end' }]];
    withText('You check vendors.');
    await render();
    await openCard('Vendor checks');
    await click(button('drafter.improve', view()!)!);
    await click(
      panel()!.querySelector<HTMLButtonElement>(
        '[data-suggestion="noPrices"]',
      )!,
    );
    const composer = panel()!.querySelector<HTMLTextAreaElement>('textarea')!;
    await type(composer, 'Also be brief.');
    await act(async () => {
      composer.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    expect(drafter.requests[1].context).toMatchObject({
      prompt: { content: 'You check vendors.' },
    });
    expect(view()!.querySelector('[data-slot="prompt-review"]')).toBeNull();
    expect(textArea()!.value).toBe('You check vendors.');
  });

  it('improves a built-in prompt as a copy, with the drawer open on it', async () => {
    drafter.config = { enabled: true };
    withText('You are DocsGPT.');
    await render();
    await openCard('default');
    await click(button('drafter.improve', view()!)!);
    expect(crumbs()).toEqual([
      'settings.prompts.label',
      'modals.prompts.duplicatePrompt',
    ]);
    expect(nameInput().value).toBe('default copy');
    expect(nameInput().disabled).toBe(false);
    expect(textArea()!.value).toBe('You are DocsGPT.');
    expect(panel()!.textContent).toContain('drafter.prompt.introImprove');
    expect(service.createPrompt).not.toHaveBeenCalled();
  });
});
