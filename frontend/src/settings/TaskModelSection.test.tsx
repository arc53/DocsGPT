import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const dispatch = vi.fn();
vi.mock('react-redux', () => ({
  useSelector: () => 'token',
  useDispatch: () => dispatch,
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.model ? `${key}(${opts.model})` : key,
  }),
}));

const getPreferences = vi.fn();
const updatePreferences = vi.fn();
const getModels = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    getPreferences: (...args: unknown[]) => getPreferences(...args),
    updatePreferences: (...args: unknown[]) => updatePreferences(...args),
  },
}));
vi.mock('../api/services/modelService', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../api/services/modelService')>();
  return {
    default: {
      ...actual.default,
      getModels: (...args: unknown[]) => getModels(...args),
    },
  };
});

// A plain stand-in for the Radix select: the value on the root, an item is a
// button that picks itself.
const SelectCtx = React.createContext<(value: string) => void>(() => {});
vi.mock('../components/ui/select', () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value: string;
    onValueChange: (value: string) => void;
    children: React.ReactNode;
  }) => (
    <SelectCtx.Provider value={onValueChange}>
      <div data-testid="select" data-value={value}>
        {children}
      </div>
    </SelectCtx.Provider>
  ),
  SelectTrigger: ({
    children,
    className,
    title,
  }: {
    children: React.ReactNode;
    className?: string;
    title?: string;
  }) => (
    <div data-testid="trigger" className={className} title={title}>
      {children}
    </div>
  ),
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  SelectGroup: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="group">{children}</div>
  ),
  SelectLabel: ({ children }: { children: React.ReactNode }) => (
    <span data-testid="group-label">{children}</span>
  ),
  SelectItem: ({
    value,
    children,
    suffix,
  }: {
    value: string;
    children: React.ReactNode;
    suffix?: React.ReactNode;
  }) => {
    const pick = React.useContext(SelectCtx);
    return (
      <button type="button" data-item={value} onClick={() => pick(value)}>
        {children}
        {suffix}
      </button>
    );
  },
}));

import TaskModelSection from './TaskModelSection';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const json = (body: unknown, ok = true) => ({
  ok,
  json: () => Promise.resolve(body),
});

// The select value of "Use instance default".
const INSTANCE = '__instance__';

const MODELS = [
  { id: 'gpt-a', display_name: 'GPT A', provider: 'openai', source: 'builtin' },
  { id: 'gpt-b', display_name: 'GPT B', provider: 'openai', source: 'builtin' },
  { id: 'mine', display_name: 'My Llama', provider: 'openai', source: 'user' },
];

let container: HTMLDivElement;
let root: Root;

const select = () =>
  container.querySelector<HTMLElement>('[data-testid="select"]');
const item = (value: string) =>
  container.querySelector<HTMLButtonElement>(`[data-item="${value}"]`)!;

async function render(prefs: Record<string, unknown>) {
  getPreferences.mockResolvedValue(json({ success: true, ...prefs }));
  getModels.mockResolvedValue(json({ models: MODELS }));
  await act(async () => root.render(<TaskModelSection />));
}

beforeEach(() => {
  dispatch.mockClear();
  getPreferences.mockReset();
  updatePreferences.mockReset();
  getModels.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe('Task model row', () => {
  it('lists the instance default, then built-in then own models, the instance default picked when none is stored', async () => {
    await render({ task_model_id: null, instance_task_model_id: 'gpt-b' });
    expect(container.querySelector('h2')?.textContent).toBe(
      'settings.general.sections.models',
    );
    expect(container.textContent).toContain('settings.general.taskModel');
    expect(container.textContent).toContain(
      'settings.general.taskModelDescription',
    );
    expect(select()?.dataset.value).toBe(INSTANCE);
    const items = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-item]'),
    ).map((b) => b.textContent);
    expect(items).toEqual([
      'settings.general.taskModelInstanceDefault(GPT B)',
      'GPT A',
      'GPT B',
      'My Llama',
    ]);
    const labels = Array.from(
      container.querySelectorAll('[data-testid="group-label"]'),
    ).map((l) => l.textContent);
    expect(labels).toEqual([
      'settings.customModels.modelsGroup.builtin',
      'settings.customModels.modelsGroup.user',
    ]);
  });

  it('shows the stored pick', async () => {
    await render({ task_model_id: 'mine', instance_task_model_id: 'gpt-b' });
    expect(select()?.dataset.value).toBe('mine');
  });

  it('saves every pick, the instance default as null', async () => {
    updatePreferences.mockResolvedValue(json({ success: true }));
    await render({ task_model_id: null, instance_task_model_id: 'gpt-b' });
    await act(async () => item('gpt-a').click());
    expect(updatePreferences).toHaveBeenLastCalledWith(
      { task_model_id: 'gpt-a' },
      'token',
    );
    expect(select()?.dataset.value).toBe('gpt-a');
    // The instance's own model, picked by name, is a pick of its own.
    await act(async () => item('gpt-b').click());
    expect(updatePreferences).toHaveBeenLastCalledWith(
      { task_model_id: 'gpt-b' },
      'token',
    );
    expect(select()?.dataset.value).toBe('gpt-b');
    await act(async () => item(INSTANCE).click());
    expect(updatePreferences).toHaveBeenLastCalledWith(
      { task_model_id: null },
      'token',
    );
    expect(select()?.dataset.value).toBe(INSTANCE);
    expect(dispatch).not.toHaveBeenCalled();
  });

  it('saves one pick at a time, then only the latest one made meanwhile', async () => {
    let finish: (ok: boolean) => void = () => undefined;
    updatePreferences.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = (ok) => resolve(json({ success: ok }, ok));
        }),
    );
    await render({ task_model_id: null, instance_task_model_id: 'gpt-b' });
    await act(async () => item('gpt-a').click());
    await act(async () => item('gpt-b').click());
    await act(async () => item('mine').click());
    expect(updatePreferences).toHaveBeenCalledTimes(1);
    expect(select()?.dataset.value).toBe('mine');
    await act(async () => finish(true));
    expect(updatePreferences).toHaveBeenCalledTimes(2);
    expect(updatePreferences).toHaveBeenLastCalledWith(
      { task_model_id: 'mine' },
      'token',
    );
    await act(async () => finish(true));
    expect(updatePreferences).toHaveBeenCalledTimes(2);
    expect(select()?.dataset.value).toBe('mine');
    expect(dispatch).not.toHaveBeenCalled();
  });

  it('goes on to a newer pick when an earlier save fails, and rolls back to the last saved one when that fails too', async () => {
    const finishes: ((ok: boolean) => void)[] = [];
    updatePreferences.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishes.push((ok) => resolve(json({ success: ok }, ok)));
        }),
    );
    await render({ task_model_id: 'gpt-a', instance_task_model_id: 'gpt-b' });
    await act(async () => item('gpt-b').click());
    await act(async () => item('mine').click());
    await act(async () => finishes[0](false));
    expect(updatePreferences).toHaveBeenLastCalledWith(
      { task_model_id: 'mine' },
      'token',
    );
    expect(select()?.dataset.value).toBe('mine');
    expect(dispatch).not.toHaveBeenCalled();
    await act(async () => finishes[1](false));
    expect(select()?.dataset.value).toBe('gpt-a');
    expect(dispatch).toHaveBeenCalledTimes(1);
  });

  it('sends a queued pick only when it differs from what the server holds', async () => {
    const finishes: ((ok: boolean) => void)[] = [];
    updatePreferences.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishes.push((ok) => resolve(json({ success: ok }, ok)));
        }),
    );
    await render({ task_model_id: 'gpt-a', instance_task_model_id: 'gpt-b' });
    // Back to the saved pick while a save fails: nothing more to send.
    await act(async () => item('mine').click());
    await act(async () => item('gpt-a').click());
    await act(async () => finishes[0](false));
    expect(updatePreferences).toHaveBeenCalledTimes(1);
    expect(select()?.dataset.value).toBe('gpt-a');
    expect(dispatch).not.toHaveBeenCalled();
    // Back to it while a save succeeds: the server now holds the other one.
    await act(async () => item('mine').click());
    await act(async () => item('gpt-a').click());
    await act(async () => finishes[1](true));
    expect(updatePreferences).toHaveBeenCalledTimes(3);
    expect(updatePreferences).toHaveBeenLastCalledWith(
      { task_model_id: 'gpt-a' },
      'token',
    );
  });

  it('puts the pick back and toasts when the save fails', async () => {
    updatePreferences.mockResolvedValue(json({ success: false }, false));
    await render({ task_model_id: 'gpt-a', instance_task_model_id: 'gpt-b' });
    await act(async () => item('mine').click());
    expect(select()?.dataset.value).toBe('gpt-a');
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: {
          variant: 'destructive',
          message: 'settings.general.taskModelSaveFailed',
        },
      }),
    );
  });

  it('offers the instance default unnamed when no model would run', async () => {
    await render({ task_model_id: null, instance_task_model_id: null });
    expect(select()?.dataset.value).toBe(INSTANCE);
    expect(item(INSTANCE).textContent).toBe(
      'settings.general.taskModelInstanceDefaultUnnamed',
    );
  });

  it('says when the stored pick can no longer run, and Use instance default clears it', async () => {
    updatePreferences.mockResolvedValue(json({ success: true }));
    await render({
      task_model_id: null,
      task_model_unavailable: true,
      instance_task_model_id: 'gpt-b',
    });
    // No option is picked: the stored model is in none of them.
    expect(select()?.dataset.value).toBe('');
    expect(container.textContent).toContain(
      'settings.general.taskModelUnavailable',
    );
    await act(async () => item(INSTANCE).click());
    expect(updatePreferences).toHaveBeenLastCalledWith(
      { task_model_id: null },
      'token',
    );
    expect(select()?.dataset.value).toBe(INSTANCE);
    expect(container.textContent).not.toContain(
      'settings.general.taskModelUnavailable',
    );
  });

  it('keeps the unavailable note when clearing it fails', async () => {
    updatePreferences.mockResolvedValue(json({ success: false }, false));
    await render({
      task_model_id: null,
      task_model_unavailable: true,
      instance_task_model_id: 'gpt-b',
    });
    await act(async () => item(INSTANCE).click());
    expect(select()?.dataset.value).toBe('');
    expect(container.textContent).toContain(
      'settings.general.taskModelUnavailable',
    );
    expect(dispatch).toHaveBeenCalledTimes(1);
  });

  it('shows no unavailable note for a pick that runs', async () => {
    await render({
      task_model_id: 'gpt-a',
      task_model_unavailable: false,
      instance_task_model_id: 'gpt-b',
    });
    expect(container.textContent).not.toContain(
      'settings.general.taskModelUnavailable',
    );
  });

  it('grows the trigger to its value up to a cap, each name truncating, the picked one as its title', async () => {
    await render({ task_model_id: 'mine', instance_task_model_id: 'gpt-b' });
    const trigger = container.querySelector<HTMLElement>(
      '[data-testid="trigger"]',
    )!;
    expect(trigger.className.split(' ')).toEqual(
      expect.arrayContaining(['sm:w-auto', 'sm:min-w-56', 'sm:max-w-80']),
    );
    expect(trigger.className).not.toContain('sm:w-56');
    expect(trigger.title).toBe('My Llama');
    expect(item('mine').querySelector('span.truncate')?.textContent).toBe(
      'My Llama',
    );
    expect(item(INSTANCE).querySelector('span.truncate')?.textContent).toBe(
      'settings.general.taskModelInstanceDefault(GPT B)',
    );
  });

  const REFUSED = { code: 'model_auth', at: '2026-11-10T09:00:00Z' };

  it("says when the picked model's key was refused, and marks it in the list", async () => {
    updatePreferences.mockResolvedValue(json({ success: true }));
    await render({
      task_model_id: 'gpt-a',
      instance_task_model_id: 'gpt-b',
      task_model_error: { model_id: 'gpt-a', ...REFUSED },
    });
    expect(container.textContent).toContain(
      'settings.general.taskModelFailed(GPT A)',
    );
    expect(item('gpt-a').textContent).toBe(
      'GPT Asettings.general.taskModelFailedItem',
    );
    expect(item('gpt-b').textContent).toBe('GPT B');
    // Another pick runs: the note goes, the mark stays (the model can
    // still be picked once an admin fixes the key).
    await act(async () => item('gpt-b').click());
    expect(container.textContent).not.toContain(
      'settings.general.taskModelFailed(',
    );
    expect(item('gpt-a').textContent).toContain(
      'settings.general.taskModelFailedItem',
    );
  });

  it('says so when the instance default it follows was refused', async () => {
    await render({
      task_model_id: null,
      instance_task_model_id: 'gpt-b',
      task_model_error: { model_id: 'gpt-b', ...REFUSED },
    });
    expect(container.textContent).toContain(
      'settings.general.taskModelFailed(GPT B)',
    );
  });

  it('shows no refusal without one', async () => {
    await render({
      task_model_id: 'gpt-a',
      instance_task_model_id: 'gpt-b',
      task_model_error: null,
    });
    expect(container.textContent).not.toContain(
      'settings.general.taskModelFailed',
    );
  });

  it('stays hidden on a server without the setting', async () => {
    await render({ chat_prompt_id: 'default' });
    expect(container.innerHTML).toBe('');
  });

  it('shows a skeleton row while it loads', async () => {
    getPreferences.mockReturnValue(new Promise(() => undefined));
    getModels.mockReturnValue(new Promise(() => undefined));
    await act(async () => root.render(<TaskModelSection />));
    expect(container.querySelector('h2')?.textContent).toBe(
      'settings.general.sections.models',
    );
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(container.querySelector('[data-slot="skeleton"]')).not.toBeNull();
    expect(select()).toBeNull();
  });

  it('shows a load error with Retry when the fetch fails, and Retry loads it', async () => {
    getPreferences.mockResolvedValue(json({}, false));
    getModels.mockResolvedValue(json({ models: MODELS }));
    await act(async () => root.render(<TaskModelSection />));
    const error = container.querySelector(
      '[data-slot="empty-state"][data-tone="destructive"]',
    );
    expect(error?.textContent).toContain('settings.general.taskModelLoadError');
    expect(select()).toBeNull();

    getPreferences.mockResolvedValue(
      json({ task_model_id: 'mine', instance_task_model_id: 'gpt-b' }),
    );
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(select()?.dataset.value).toBe('mine');
  });

  it('shows the load error when a request throws', async () => {
    getPreferences.mockRejectedValue(new Error('offline'));
    getModels.mockResolvedValue(json({ models: MODELS }));
    await act(async () => root.render(<TaskModelSection />));
    expect(
      container.querySelector(
        '[data-slot="empty-state"][data-tone="destructive"]',
      ),
    ).not.toBeNull();
  });
});
