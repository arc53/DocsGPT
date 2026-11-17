import { configureStore } from '@reduxjs/toolkit';
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // Interpolated names show as `key(name)` / `key[names]` so tests can
    // read who is named.
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && typeof opts.names === 'string'
        ? `${key}[${opts.names}]`
        : opts && typeof opts.name === 'string'
          ? `${key}(${opts.name}${typeof opts.team === 'string' ? `→${opts.team}` : ''})`
          : key,
  }),
}));

// The list shows as soon as it loads, without the skeleton's linger.
vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useLoaderState: (initial: boolean) => useState(initial),
}));

const service = vi.hoisted(() => ({
  listCustomModels: vi.fn(),
  deleteCustomModel: vi.fn(),
  updateCustomModel: vi.fn(),
  getCustomModelUsage: vi.fn(),
  copyToTeam: vi.fn(),
}));
vi.mock('../api/services/customModelsService', () => ({ default: service }));
vi.mock('../api/services/modelService', () => ({
  default: { getModels: vi.fn(), transformModels: vi.fn(() => []) },
}));
// The add/edit dialog is tested on its own; here only what it opens with.
const modalProps = vi.hoisted(() => ({
  current: null as Record<string, unknown> | null,
}));
vi.mock('../modals/CustomModelModal', () => ({
  default: (props: Record<string, unknown>) => {
    modalProps.current = props;
    return null;
  },
}));
// Render each ⋯ menu's options inline so tests can read and click them.
vi.mock('../components/ui/dropdown-menu', () => ({
  ActionMenu: ({
    options,
  }: {
    options: Array<{ label: string; onClick: () => void }>;
  }) => (
    <div data-testid="model-menu">
      {options.map((o) => (
        <button key={o.label} type="button" onClick={o.onClick}>
          {o.label}
        </button>
      ))}
    </div>
  ),
}));

import actionToastReducer from '../notifications/actionToastSlice';
import type { CustomModel } from '../models/types';
import { setRequestWorkspace } from '../workspace/requestWorkspace';
import workspaceReducer, {
  PERSONAL_ROW,
  switchWorkspace,
  type WorkspaceRole,
  type WorkspaceRow,
} from '../workspace/workspaceSlice';
import CustomModels from './CustomModels';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

/** A token whose `sub` is `user`, as the app reads the reader's id. */
const tokenFor = (user: string) =>
  `h.${btoa(JSON.stringify({ sub: user })).replace(/=+$/, '')}.s`;

const team = (id: string, name: string, role: WorkspaceRole): WorkspaceRow => ({
  id,
  kind: 'team',
  name,
  role,
});

const makeStore = (current: string, teams: WorkspaceRow[]) =>
  configureStore({
    reducer: {
      actionToast: actionToastReducer,
      preference: (state = { token: tokenFor('ana') }) => state,
      workspace: workspaceReducer,
    },
    preloadedState: {
      workspace: {
        current,
        workspaces: [PERSONAL_ROW, ...teams],
        loaded: true,
        loading: false,
        epoch: 0,
        lastReason: null,
        latestRequestId: null,
      },
    },
  });

const teamModel = (
  manage: boolean,
  overrides: Partial<CustomModel> = {},
): CustomModel => ({
  id: 'tm1',
  upstream_model_id: 'llama-3',
  display_name: 'Team Llama',
  capabilities: {
    supports_tools: true,
    supports_structured_output: true,
    attachments: [],
    context_window: 128000,
  },
  enabled: true,
  source: 'team',
  owner: 'team',
  team_id: 't1',
  created_by: { user_id: 'lena', label: 'Lena' },
  allowed_actions: manage ? ['view', 'use', 'manage'] : ['view', 'use'],
  ...(manage && { base_url: 'https://llm.example.com/v1' }),
  ...overrides,
});

const MINE: CustomModel = {
  id: 'pm1',
  upstream_model_id: 'mistral-large',
  display_name: 'My Mistral',
  base_url: 'https://api.mistral.ai/v1',
  capabilities: {
    supports_tools: true,
    supports_structured_output: true,
    attachments: [],
    context_window: 128000,
  },
  enabled: true,
  source: 'user',
  owner: 'personal',
  team_id: null,
  created_by: null,
  allowed_actions: ['view', 'use', 'manage'],
};

describe('Custom models page in a team', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    Object.values(service).forEach((fn) => fn.mockReset());
    service.listCustomModels.mockResolvedValue([]);
    modalProps.current = null;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    setRequestWorkspace('personal', 0);
  });

  const render = async (current: string, teams: WorkspaceRow[]) => {
    store = makeStore(current, teams);
    setRequestWorkspace(current, 0);
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/settings/custom-models']}>
            <CustomModels />
          </MemoryRouter>
        </Provider>,
      );
    });
  };
  const inTeam = (role: WorkspaceRole) =>
    render('t1', [team('t1', 'Operations', role)]);

  const text = () => document.body.textContent ?? '';
  const button = (label: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent?.trim() === label);
  // A button of the open dialog, which renders outside the page.
  const dialogButton = (label: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => !container.contains(b) && b.textContent?.trim() === label);
  const menuLabels = () =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-testid="model-menu"] button',
      ),
    ).map((b) => b.textContent);

  it.each(['viewer', 'editor'] as const)(
    "a %s reads the team's models without the base URL, and changes nothing",
    async (role) => {
      service.listCustomModels.mockResolvedValue([teamModel(false)]);
      await inTeam(role);
      expect(service.listCustomModels).toHaveBeenCalledWith(
        expect.any(String),
        { owner: 'team', workspace: 't1' },
      );
      expect(text()).toContain('settings.customModels.team.notice');
      expect(text()).not.toContain('settings.customModels.personalOnly');
      expect(text()).toContain('Team Llama');
      expect(text()).toContain('llama-3');
      expect(text()).toContain('settings.customModels.team.addedBy(Lena)');
      expect(text()).not.toContain('llm.example.com');
      expect(button('settings.customModels.addModel')).toBeUndefined();
      expect(container.querySelector('[data-testid="model-menu"]')).toBe(null);
    },
  );

  it('a member sees who can add one when the team has none', async () => {
    await inTeam('viewer');
    expect(text()).toContain('settings.customModels.team.emptyMember');
    expect(text()).not.toContain('settings.customModels.team.emptyAdmin');
  });

  it.each(['admin', 'owner'] as const)(
    'an %s adds models for the team and manages them',
    async (role) => {
      service.listCustomModels.mockResolvedValue([teamModel(true)]);
      await inTeam(role);
      expect(text()).toContain('llm.example.com');
      expect(menuLabels()).toEqual([
        'settings.customModels.actions.edit',
        'settings.customModels.team.actions.disable',
        'settings.customModels.actions.delete',
      ]);
      await act(async () => button('settings.customModels.addModel')!.click());
      expect(modalProps.current).toMatchObject({
        modalState: 'ACTIVE',
        model: null,
        owner: 'team',
      });
    },
  );

  it('an Admin is asked to add the first one', async () => {
    await inTeam('admin');
    expect(text()).toContain('settings.customModels.team.emptyAdmin');
  });

  it('an Admin disables a model from its menu', async () => {
    service.listCustomModels.mockResolvedValue([teamModel(true)]);
    service.updateCustomModel.mockResolvedValue(
      teamModel(true, { enabled: false }),
    );
    await inTeam('admin');
    await act(async () =>
      button('settings.customModels.team.actions.disable')!.click(),
    );
    expect(service.updateCustomModel).toHaveBeenCalledWith(
      'tm1',
      { enabled: false },
      expect.any(String),
    );
    expect(text()).toContain('settings.customModels.disabledBadge');
    expect(menuLabels()).toContain('settings.customModels.team.actions.enable');
  });

  it('the delete confirm names the agents and workflows that fall back, read before deleting', async () => {
    service.listCustomModels.mockResolvedValue([teamModel(true)]);
    service.getCustomModelUsage.mockResolvedValue({
      agents: [{ id: 'a1', name: 'Support bot' }],
      workflows: [{ id: 'w1', name: 'Triage' }],
    });
    service.deleteCustomModel.mockResolvedValue({ success: true });
    await inTeam('admin');
    await act(async () =>
      button('settings.customModels.actions.delete')!.click(),
    );
    expect(service.getCustomModelUsage).toHaveBeenCalledWith(
      'tm1',
      expect.any(String),
    );
    expect(service.deleteCustomModel).not.toHaveBeenCalled();
    expect(text()).toContain(
      'settings.customModels.team.delete.usedBy[Support bot, Triage]',
    );
    await act(async () =>
      dialogButton('settings.customModels.actions.delete')!.click(),
    );
    expect(service.deleteCustomModel).toHaveBeenCalledWith(
      'tm1',
      expect.any(String),
    );
  });

  it('a model nothing uses is deleted with the plain warning', async () => {
    service.listCustomModels.mockResolvedValue([teamModel(true)]);
    service.getCustomModelUsage.mockResolvedValue({
      agents: [],
      workflows: [],
    });
    await inTeam('admin');
    await act(async () =>
      button('settings.customModels.actions.delete')!.click(),
    );
    expect(text()).toContain('common.cantUndo');
    expect(text()).not.toContain('settings.customModels.team.delete.usedBy');
  });

  it('switching to another team lists that team’s models', async () => {
    await render('t1', [
      team('t1', 'Operations', 'viewer'),
      team('t2', 'Dev', 'admin'),
    ]);
    await act(async () => {
      store.dispatch(switchWorkspace('t2'));
    });
    expect(service.listCustomModels).toHaveBeenLastCalledWith(
      expect.any(String),
      { owner: 'team', workspace: 't2' },
    );
  });

  it('Personal lists the reader’s own models with no team notice, as before', async () => {
    service.listCustomModels.mockResolvedValue([MINE]);
    await render('personal', [team('t1', 'Operations', 'editor')]);
    expect(service.listCustomModels).toHaveBeenCalledWith(expect.any(String));
    expect(text()).not.toContain('settings.customModels.team.notice');
    expect(text()).toContain('settings.customModels.subtitle');
    expect(text()).toContain('api.mistral.ai');
    expect(button('settings.customModels.addModel')).toBeDefined();
    // Only an Admin of some team may copy a model into it.
    expect(menuLabels()).not.toContain(
      'settings.customModels.team.copy.action',
    );
  });

  it('Copy to a team shows for an Admin of a team and copies the model there', async () => {
    service.listCustomModels.mockResolvedValue([MINE]);
    service.copyToTeam.mockResolvedValue(teamModel(true, { id: 'tm9' }));
    await render('personal', [
      team('t1', 'Operations', 'editor'),
      team('t2', 'Dev', 'admin'),
    ]);
    await act(async () =>
      button('settings.customModels.team.copy.action')!.click(),
    );
    // One team to copy into: the dialog names it instead of asking.
    expect(text()).toContain(
      'settings.customModels.team.copy.bodyTo(My Mistral→Dev)',
    );
    await act(async () =>
      button('settings.customModels.team.copy.confirm')!.click(),
    );
    expect(service.copyToTeam).toHaveBeenCalledWith(
      'pm1',
      't2',
      expect.any(String),
    );
    expect(store.getState().actionToast.current).toMatchObject({
      variant: 'success',
      message: 'settings.customModels.team.copy.done(My Mistral→Dev)',
    });
  });

  it('a refused copy says why in the dialog', async () => {
    service.listCustomModels.mockResolvedValue([MINE]);
    service.copyToTeam.mockRejectedValue(
      Object.assign(new Error('model_already_in_team'), {
        status: 409,
        payload: {
          success: false,
          error: 'model_already_in_team',
          model_id: 'tm1',
        },
      }),
    );
    await render('personal', [team('t2', 'Dev', 'owner')]);
    await act(async () =>
      button('settings.customModels.team.copy.action')!.click(),
    );
    await act(async () =>
      button('settings.customModels.team.copy.confirm')!.click(),
    );
    expect(text()).toContain('settings.customModels.team.errors.alreadyInTeam');
    expect(store.getState().actionToast.current).toBe(null);
  });
});
