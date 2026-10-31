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
}));
vi.mock('../api/services/userService', () => ({ default: service }));

const confirm = vi.hoisted(() => ({
  props: null as null | {
    message: string;
    description?: string;
    error?: string;
    handleSubmit: () => void | Promise<unknown>;
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

  it("opens a viewer's prompt read-only from its card", async () => {
    service.getSinglePrompt.mockImplementation(() =>
      response({ content: 'Brief the rep.' }),
    );
    await render();
    await act(async () =>
      card('Deal desk')
        .querySelector<HTMLButtonElement>('button[type="button"]')!
        .click(),
    );
    const last = promptsModalProps.mock.calls.at(-1)![0];
    expect(last).toMatchObject({
      modalState: 'ACTIVE',
      type: 'EDIT',
      readOnly: true,
    });
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
});
