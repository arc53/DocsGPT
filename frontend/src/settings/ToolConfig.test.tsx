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
const createTool = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    updateTool: (...args: unknown[]) => updateTool(...args),
    createTool: (...args: unknown[]) => createTool(...args),
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

  it('renders the actions search as a labelled pill SearchInput with an inset icon', async () => {
    await render(userTool);
    const label = Array.from(container.querySelectorAll('label')).find(
      (el) => el.textContent === 'settings.tools.searchActions',
    );
    const search = label?.htmlFor
      ? container.querySelector<HTMLInputElement>(
          `input[id="${label.htmlFor}"]`,
        )
      : null;
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

  it('shows a save the server refused as failed', async () => {
    updateTool.mockResolvedValue({ ok: false, status: 400 });
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
    expect(
      container.querySelector<HTMLElement>('[role="alert"]')?.textContent,
    ).toBe('settings.tools.saveFailed');
  });

  describe('a shared MCP server', () => {
    const mcpTool = (authType: string) =>
      ({
        id: 'mcp-1',
        name: 'mcp_tool',
        displayName: 'MCP',
        description: '',
        status: true,
        access: 'editor',
        allowed_actions: ['edit', 'edit_credentials', 'use', 'use_in_own'],
        config: {
          server_url: 'https://mcp.example.com/mcp',
          auth_type: authType,
        },
        configRequirements: {
          server_url: { type: 'string', label: 'Server URL', secret: false },
          auth_type: { type: 'string', label: 'Auth', secret: false },
        },
        actions: [],
      }) as unknown as UserToolType;

    const rename = async () => {
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
    };

    it('locks the connection of an OAuth server and saves without it', async () => {
      updateTool.mockResolvedValue({ ok: true });
      await render(mcpTool('oauth'));
      expect(container.querySelector('fieldset')?.disabled).toBe(true);
      await rename();
      expect(updateTool).toHaveBeenCalledTimes(1);
      expect(updateTool.mock.calls[0][0]).not.toHaveProperty('config');
      expect(updateTool.mock.calls[0][0].customName).toBe('Renamed');
    });

    it('still lets an editor change a non-OAuth server', async () => {
      updateTool.mockResolvedValue({ ok: true });
      await render(mcpTool('bearer'));
      expect(container.querySelector('fieldset')?.disabled).toBe(false);
      await rename();
      expect(updateTool.mock.calls[0][0]).toHaveProperty('config');
    });
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

  it('renders Actions as a section title with the API buttons as its actions', async () => {
    await render(apiTool);
    const heading = Array.from(container.querySelectorAll('h2')).find(
      (el) => el.textContent === 'settings.tools.actions',
    );
    expect(heading?.className).toContain('text-lg font-semibold');
    const header = heading?.closest('[data-slot="section-header"]');
    expect(header?.contains(buttonByText('settings.tools.importSpec')!)).toBe(
      true,
    );
    expect(header?.contains(buttonByText('settings.tools.addAction')!)).toBe(
      true,
    );
  });

  it('renders Actions as a section title without buttons on a non-API tool', async () => {
    await render(userTool);
    const heading = Array.from(container.querySelectorAll('h2')).find(
      (el) => el.textContent === 'settings.tools.actions',
    );
    expect(heading?.className).toContain('text-lg font-semibold');
    expect(buttonByText('settings.tools.importSpec')).toBeUndefined();
  });

  it('renders the API action form as 42px pills with remove icons', async () => {
    await render(apiTool);
    const deleteAction = container.querySelector<HTMLElement>(
      'button[aria-label="convTile.delete"]',
    );
    expect(deleteAction?.hasAttribute('title')).toBe(false);
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
      expect(trigger.dataset.size).toBe('field');
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

  it('renders the body type hint as a FormField hint and the action sections as xs sub-headings', async () => {
    await render(apiTool);
    await act(async () => {
      (
        container.querySelector('[class*="cursor-pointer"]') as HTMLElement
      ).click();
    });
    const hint = Array.from(container.querySelectorAll('p')).find(
      (el) => el.textContent === 'settings.tools.bodyTypeHint.json',
    );
    expect(hint?.className).toBe('text-muted-foreground text-xs');
    expect(hint?.id).toBeTruthy();
    expect(
      container.querySelector(`[aria-describedby~="${hint?.id}"]`),
    ).not.toBeNull();
    const headers = Array.from(container.querySelectorAll('h3')).find(
      (el) => el.textContent === 'settings.tools.headers',
    );
    expect(headers?.className).toContain('text-sm font-semibold');
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

  it('opens an action header from the keyboard', async () => {
    await render(apiTool);
    const header = container.querySelector<HTMLElement>(
      '[role="button"][aria-expanded]',
    );
    expect(header?.tabIndex).toBe(0);
    expect(header?.getAttribute('aria-expanded')).toBe('false');
    await act(async () => {
      header?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    expect(header?.getAttribute('aria-expanded')).toBe('true');
    expect(
      container.querySelector('input[value="https://example.com"]'),
    ).not.toBeNull();
  });

  it('renders the parameter table from the ui/table parts', async () => {
    await render(userTool);
    await act(async () => {
      (
        container.querySelector('[class*="cursor-pointer"]') as HTMLElement
      ).click();
    });
    expect(container.querySelector('.table-default')).toBeNull();
    const table = container.querySelector('table');
    expect(table?.dataset.slot).toBe('table');
    expect(table?.closest('[data-slot="table-container"]')).not.toBeNull();
    const heads = Array.from(table?.querySelectorAll('th') ?? []);
    expect(heads.length).toBe(5);
    heads.forEach((th) => expect(th.dataset.slot).toBe('table-header'));
    table?.querySelectorAll('td').forEach((td) => {
      expect(td.dataset.slot).toBe('table-cell');
    });
  });

  it('renders the API property tables from the ui/table parts with 40px delete columns', async () => {
    await render(apiTool);
    await act(async () => {
      (
        container.querySelector('[class*="cursor-pointer"]') as HTMLElement
      ).click();
    });
    expect(container.querySelector('.table-default')).toBeNull();
    const tables = Array.from(container.querySelectorAll('table'));
    expect(tables).toHaveLength(3);
    tables.forEach((table) => {
      expect(table.dataset.slot).toBe('table');
      expect(table.closest('[data-slot="table-container"]')).not.toBeNull();
      table.querySelectorAll('th').forEach((th) => {
        expect(th.dataset.slot).toBe('table-header');
        expect(th.className).not.toContain('!');
      });
    });
    const deleteCell = container
      .querySelector('table button[data-variant="ghost-destructive"]')
      ?.closest('td');
    expect(deleteCell?.dataset.slot).toBe('table-cell');
    expect(deleteCell?.style.getPropertyValue('--cell-width')).toBe('40px');
    expect(deleteCell?.className).toContain('text-center');
    expect(deleteCell?.className).not.toMatch(/p-0|!/);
  });

  it('renders the add-property Cancel as a ghost pill', async () => {
    await render(apiTool);
    await act(async () => {
      (
        container.querySelector('[class*="cursor-pointer"]') as HTMLElement
      ).click();
    });
    await act(async () => {
      buttonByText('settings.tools.addNew')?.click();
    });
    const cancel = buttonByText('settings.tools.cancel');
    expect(cancel?.dataset.variant).toBe('ghost');
    expect(cancel?.dataset.size).toBe('sm');
    expect(cancel?.dataset.shape).toBe('pill');
  });

  it('creates a draft OpenAPI tool on its first save, not before', async () => {
    createTool.mockResolvedValue({ ok: true });
    updateTool.mockClear();
    await render({ ...apiTool, id: '' } as APIToolType);
    expect(createTool).not.toHaveBeenCalled();
    await act(async () => buttonByText('settings.tools.save')!.click());
    expect(updateTool).not.toHaveBeenCalled();
    expect(createTool.mock.calls[0][0]).toMatchObject({ name: 'api_tool' });
  });

  describe('access', () => {
    const viewer = { access: 'viewer', allowed_actions: ['use'] };
    const editorNoCreds = {
      access: 'editor',
      allowed_actions: ['edit', 'use', 'use_in_own'],
    };
    const configTool = {
      ...userTool,
      configRequirements: {
        token: { type: 'string', label: 'Token', secret: true, required: true },
      },
      config: { has_encrypted_credentials: true },
    } as unknown as UserToolType;
    // A disabled fieldset disables its controls in the browser; jsdom doesn't
    // apply that to `:disabled`, so check for the fieldset as well.
    const disabled = (el: Element) =>
      el.matches(':disabled') || el.closest('fieldset[disabled]') !== null;
    const nameInput = () =>
      container.querySelector<HTMLInputElement>(
        'input[placeholder="settings.tools.customNamePlaceholder"]',
      )!;
    const expandFirstAction = async () => {
      await act(async () => {
        (
          container.querySelector('[class*="cursor-pointer"]') as HTMLElement
        ).click();
      });
    };

    it('opens read-only without edit or edit_credentials: no Save, every field disabled', async () => {
      await render({ ...configTool, ...viewer } as UserToolType);
      expect(buttonByText('settings.tools.save')).toBeUndefined();
      const note = container.querySelector('[data-slot="alert"]');
      expect(note?.getAttribute('role')).toBe('note');
      expect(note?.textContent).toBe('common.viewOnlyNotice');
      expect(nameInput().disabled).toBe(true);
      const secret = container.querySelector<HTMLInputElement>(
        'input[type="password"]',
      );
      expect(secret && disabled(secret)).toBe(true);
      expect(secret?.value).toBe('');
      expect(secret?.placeholder).not.toContain('•');
      expect(container.textContent).toContain('common.savedSecretHint');
      container
        .querySelectorAll<HTMLButtonElement>('[role="switch"]')
        .forEach((sw) => expect(disabled(sw)).toBe(true));
      await expandFirstAction();
      container
        .querySelectorAll<HTMLInputElement>('table input')
        .forEach((input) => expect(disabled(input)).toBe(true));
    });

    it('keeps the actions search usable when read-only', async () => {
      await render({ ...userTool, ...viewer } as UserToolType);
      const label = Array.from(container.querySelectorAll('label')).find(
        (el) => el.textContent === 'settings.tools.searchActions',
      )!;
      expect(
        container.querySelector<HTMLInputElement>(
          `input[id="${label.htmlFor}"]`,
        )?.disabled,
      ).toBe(false);
    });

    it('hides the API tool Import and Add action buttons when read-only', async () => {
      await render({ ...apiTool, ...viewer } as APIToolType);
      expect(buttonByText('settings.tools.importSpec')).toBeUndefined();
      expect(buttonByText('settings.tools.addAction')).toBeUndefined();
    });

    it('lets an editor without edit_credentials rename but not touch credentials', async () => {
      await render({ ...configTool, ...editorNoCreds } as UserToolType);
      expect(nameInput().disabled).toBe(false);
      // Not a view-only form: the editor can still save a rename.
      expect(container.textContent).not.toContain('common.viewOnlyNotice');
      const authInputs = Array.from(
        container.querySelectorAll<HTMLInputElement>('input'),
      ).filter((i) => i !== nameInput() && !i.closest('table'));
      const credential = authInputs.find((i) => i.type === 'password');
      expect(credential && disabled(credential)).toBe(true);
    });

    it('says why the credentials are locked for an editor without edit_credentials', async () => {
      await render({ ...configTool, ...editorNoCreds } as UserToolType);
      const note = container.querySelector('[data-slot="alert"]');
      expect(note?.getAttribute('role')).toBe('note');
      expect(note?.textContent).toBe('common.credentialsLockedNotice');
    });

    it('shows no credentials note to a role that may change them', async () => {
      await render({
        ...configTool,
        access: 'editor',
        allowed_actions: ['edit', 'edit_credentials', 'use'],
      } as UserToolType);
      expect(container.textContent).not.toContain(
        'common.credentialsLockedNotice',
      );
    });

    // The connection's secret is the owner's alone: the server refuses any
    // credential change from anyone else, so the form must not offer one.
    it("locks a connected tool's credentials for an editor allowed to change credentials", async () => {
      updateTool.mockResolvedValue({ ok: true });
      await render({
        ...configTool,
        connection_id: 'owner-conn',
        access: 'editor',
        allowed_actions: ['edit', 'edit_credentials', 'use'],
      } as UserToolType);
      const note = container.querySelector('[data-slot="alert"]');
      expect(note?.textContent).toBe('common.credentialsLockedNotice');
      const credential = container.querySelector<HTMLInputElement>(
        'input[type="password"]',
      );
      expect(credential && disabled(credential)).toBe(true);
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          'value',
        )?.set;
        setter?.call(nameInput(), 'Renamed');
        nameInput().dispatchEvent(new Event('input', { bubbles: true }));
      });
      await act(async () => {
        buttonByText('settings.tools.save')?.click();
      });
      expect(updateTool).toHaveBeenCalledTimes(1);
      expect(updateTool.mock.calls[0][0]).not.toHaveProperty('config');
    });

    it("keeps a connected tool's credentials open to its owner", async () => {
      await render({
        ...configTool,
        connection_id: 'my-conn',
        access: 'owner',
      } as UserToolType);
      expect(container.textContent).not.toContain(
        'common.credentialsLockedNotice',
      );
    });

    it("disables an API tool's URL and header values without edit_credentials", async () => {
      await render({ ...apiTool, ...editorNoCreds } as APIToolType);
      await expandFirstAction();
      const url = Array.from(
        container.querySelectorAll<HTMLInputElement>('input'),
      ).find((i) => i.value === 'https://example.com');
      expect(url?.disabled).toBe(true);
      const headerValue = container.querySelector<HTMLInputElement>(
        'input[placeholder="settings.tools.headerValuePlaceholder"]',
      );
      expect(headerValue?.disabled).toBe(true);
    });
  });

  it('masks a saved API header value with a replace-to-change placeholder', async () => {
    const saved = JSON.parse(JSON.stringify(apiTool)) as APIToolType;
    saved.config.actions.list.headers.properties.Accept.has_value = true;
    await render(saved);
    await act(async () => {
      (
        container.querySelector('[class*="cursor-pointer"]') as HTMLElement
      ).click();
    });
    const masked = container.querySelector<HTMLInputElement>(
      'input[placeholder="settings.tools.savedSecretPlaceholder"]',
    );
    expect(masked).not.toBeNull();
    expect(masked?.type).toBe('password');
    expect(masked?.value).toBe('');
  });

  it('shows a non-2xx save response as a destructive Alert', async () => {
    updateTool.mockResolvedValue({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ success: false, message: 'Forbidden' }),
    });
    const goBack = vi.fn();
    await act(async () => {
      root.render(
        <ToolConfig
          tool={{ ...userTool, customName: '' }}
          setTool={() => {}}
          handleGoBack={goBack}
        />,
      );
    });
    const name = container.querySelector<HTMLInputElement>(
      'input[placeholder="settings.tools.customNamePlaceholder"]',
    );
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )?.set?.call(name, 'Renamed');
      name?.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      buttonByText('settings.tools.save')?.click();
    });
    expect(
      container.querySelector<HTMLElement>('[role="alert"]')?.textContent,
    ).toBe('settings.tools.saveFailed');
    expect(goBack).not.toHaveBeenCalled();
  });
});
