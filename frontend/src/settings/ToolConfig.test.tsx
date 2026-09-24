import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === 'string' ? fallback : key,
  }),
}));

vi.mock('../hooks', () => ({ useDarkTheme: () => [false, () => {}] }));
vi.mock('../navigation/DetailBreadcrumb', () => ({ default: () => null }));
vi.mock('../modals/ConfirmationModal', () => ({ default: () => null }));
vi.mock('../modals/AddActionModal', () => ({ default: () => null }));
vi.mock('../modals/ImportSpecModal', () => ({ default: () => null }));

const updateTool = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    updateTool: (...args: unknown[]) => updateTool(...args),
    deleteTool: () => Promise.resolve(),
  },
}));

import type { APIToolType, UserToolType } from './types';
import ToolConfig from './ToolConfig';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const userTool = {
  id: 'tool-1',
  name: 'brave_search',
  displayName: 'Brave',
  description: '',
  status: true,
  config: {},
  actions: [
    {
      name: 'search',
      description: 'Search the web',
      active: true,
      parameters: {
        type: 'object',
        properties: {
          q: {
            type: 'string',
            description: '',
            value: '',
            filled_by_llm: true,
          },
        },
      },
    },
  ],
} as unknown as UserToolType;

const apiTool = {
  id: 'tool-2',
  name: 'api_tool',
  displayName: 'API',
  description: '',
  status: true,
  config: {
    actions: {
      list: {
        name: 'list',
        method: 'POST',
        url: 'https://example.com',
        description: 'List things',
        active: true,
        body: { type: 'object', properties: {} },
        headers: {
          type: 'object',
          properties: {
            Accept: {
              type: 'string',
              description: '',
              value: '',
              filled_by_llm: false,
            },
          },
        },
        query_params: { type: 'object', properties: {} },
        body_content_type: 'application/json',
        body_encoding_rules: {},
      },
    },
  },
} as unknown as APIToolType;

describe('ToolConfig', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    updateTool.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (tool: UserToolType | APIToolType) => {
    await act(async () => {
      root.render(
        <ToolConfig tool={tool} setTool={() => {}} handleGoBack={() => {}} />,
      );
    });
  };

  const buttonByText = (text: string) =>
    Array.from(container.querySelectorAll<HTMLElement>('button')).find(
      (el) => el.textContent === text,
    );

  it('renders the header Save as a small pill with no class overrides', async () => {
    await render(userTool);
    const save = buttonByText('settings.tools.save');
    expect(save?.dataset.size).toBe('sm');
    expect(save?.dataset.shape).toBe('pill');
    expect(save?.className).not.toMatch(/text-white|text-xs/);
  });

  it('renders the actions search as a pill Input with an inset icon', async () => {
    await render(userTool);
    const search = container.querySelector<HTMLInputElement>(
      'input[placeholder="settings.tools.searchActions"]',
    );
    expect(search?.dataset.shape).toBe('pill');
    expect(search?.className).toContain('pl-10');
    expect(search?.parentElement?.querySelector('svg')).not.toBeNull();
  });

  it('renders the parameter table fields at the small Input size', async () => {
    await render(userTool);
    await act(async () => {
      (
        container.querySelector('[class*="cursor-pointer"]') as HTMLElement
      ).click();
    });
    const tableInputs = Array.from(
      container.querySelectorAll<HTMLInputElement>('table input[data-slot]'),
    );
    expect(tableInputs.length).toBeGreaterThan(0);
    tableInputs.forEach((input) => {
      expect(input.dataset.size).toBe('sm');
      expect(input.className).not.toMatch(/rounded-lg|h-auto/);
    });
  });

  it('shows a failed save as a destructive Alert', async () => {
    updateTool.mockRejectedValue(new Error('nope'));
    await render({ ...userTool, customName: '' });
    const name = container.querySelector<HTMLInputElement>(
      'input[placeholder="settings.tools.customNamePlaceholder"]',
    );
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )?.set;
      setter?.call(name, 'Renamed');
      name?.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      buttonByText('settings.tools.save')?.click();
    });
    const alert = container.querySelector<HTMLElement>('[role="alert"]');
    expect(alert?.textContent).toBe('settings.tools.saveFailed');
    expect(alert?.className).toContain('text-destructive');
  });

  it('renders the API tool header actions as outline-primary pills', async () => {
    await render(apiTool);
    for (const label of [
      'settings.tools.importSpec',
      'settings.tools.addAction',
    ]) {
      const button = buttonByText(label);
      expect(button?.dataset.variant).toBe('outline-primary');
      expect(button?.dataset.shape).toBe('pill');
    }
  });

  it('renders the API action form as 42px pills with remove icons', async () => {
    await render(apiTool);
    const deleteAction = container.querySelector<HTMLElement>(
      'button[title="convTile.delete"]',
    );
    expect(deleteAction?.dataset.variant).toBe('ghost-destructive');
    expect(deleteAction?.dataset.size).toBe('icon-xs');

    await act(async () => {
      (
        container.querySelector('[class*="cursor-pointer"]') as HTMLElement
      ).click();
    });
    const urlField = container.querySelector<HTMLInputElement>(
      'input[value="https://example.com"]',
    );
    expect(urlField?.dataset.shape).toBe('pill');
    expect(urlField?.dataset.size).toBe('default');
    const triggers = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="select-trigger"]'),
    );
    expect(triggers).toHaveLength(2);
    triggers.forEach((trigger) => {
      expect(trigger.dataset.size).toBe('lg');
      expect(trigger.className).not.toContain('rounded-3xl');
    });
    const addNew = buttonByText('settings.tools.addNew');
    expect(addNew?.dataset.variant).toBe('outline-primary');
    expect(addNew?.dataset.shape).toBe('pill');
    const removeRow = container.querySelector<HTMLElement>(
      'table button[data-variant="ghost-destructive"]',
    );
    expect(removeRow?.dataset.size).toBe('icon-xs');
  });

  it('renders the property type as a small Select, not a native select', async () => {
    const list = (apiTool.config as { actions: Record<string, object> }).actions
      .list;
    await render({
      ...apiTool,
      config: {
        actions: {
          list: {
            ...list,
            query_params: {
              type: 'object',
              properties: {
                limit: {
                  type: 'integer',
                  description: '',
                  value: '',
                  filled_by_llm: true,
                },
              },
            },
          },
        },
      },
    } as unknown as APIToolType);
    await act(async () => {
      (
        container.querySelector('[class*="cursor-pointer"]') as HTMLElement
      ).click();
    });
    expect(container.querySelector('select:not([aria-hidden])')).toBeNull();
    const typeTrigger = container.querySelector<HTMLElement>(
      'table [data-slot="select-trigger"]',
    );
    expect(typeTrigger?.dataset.size).toBe('sm');
    expect(typeTrigger?.getAttribute('aria-label')).toBe('settings.tools.type');
    expect(typeTrigger?.textContent).toContain('integer');
  });
});
