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
  SelectTrigger: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
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
  }: {
    value: string;
    children: React.ReactNode;
  }) => {
    const pick = React.useContext(SelectCtx);
    return (
      <button type="button" data-item={value} onClick={() => pick(value)}>
        {children}
      </button>
    );
  },
}));

import TaskModelSection, { INSTANCE_DEFAULT } from './TaskModelSection';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const json = (body: unknown, ok = true) => ({
  ok,
  json: () => Promise.resolve(body),
});

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
  it('offers the instance default by name, then built-in and own models', async () => {
    await render({ task_model_id: null, instance_task_model_id: 'gpt-b' });
    expect(container.querySelector('h2')?.textContent).toBe(
      'settings.general.sections.models',
    );
    expect(container.textContent).toContain('settings.general.taskModel');
    expect(container.textContent).toContain(
      'settings.general.taskModelDescription',
    );
    expect(select()?.dataset.value).toBe(INSTANCE_DEFAULT);
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

  it('saves a pick, and null for the instance default', async () => {
    updatePreferences.mockResolvedValue(json({ success: true }));
    await render({ task_model_id: null, instance_task_model_id: 'gpt-b' });
    await act(async () => item('gpt-a').click());
    expect(updatePreferences).toHaveBeenLastCalledWith(
      { task_model_id: 'gpt-a' },
      'token',
    );
    expect(select()?.dataset.value).toBe('gpt-a');
    await act(async () => item(INSTANCE_DEFAULT).click());
    expect(updatePreferences).toHaveBeenLastCalledWith(
      { task_model_id: null },
      'token',
    );
    expect(select()?.dataset.value).toBe(INSTANCE_DEFAULT);
    expect(dispatch).not.toHaveBeenCalled();
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

  it('names no model when the instance default is unknown', async () => {
    await render({ task_model_id: null, instance_task_model_id: null });
    expect(item(INSTANCE_DEFAULT).textContent).toBe(
      'settings.general.taskModelInstanceDefaultUnnamed',
    );
  });

  it('stays hidden on a server without the setting', async () => {
    await render({ chat_prompt_id: 'default' });
    expect(container.innerHTML).toBe('');
  });
});
