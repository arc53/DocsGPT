import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const service = vi.hoisted(() => ({
  createCustomModel: vi.fn(),
  updateCustomModel: vi.fn(),
  testCustomModel: vi.fn(),
  testCustomModelPayload: vi.fn(),
}));
vi.mock('../api/services/customModelsService', () => ({ default: service }));

import type { CustomModel } from '../models/types';
import CustomModelModal, {
  buildInitialFormState,
  CapabilityChip,
} from './CustomModelModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('CapabilityChip', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = (active: boolean, onClick = vi.fn()) => {
    act(() => {
      root.render(
        <CapabilityChip label="Tools" active={active} onClick={onClick} />,
      );
    });
    return container.querySelector<HTMLButtonElement>('button')!;
  };

  it('is a pressed toggle chip, secondary with a check when on', () => {
    const chip = render(true);
    // A toggle button named by its capability ("Tools, pressed"), not a
    // switch: the chip row reads as a set of on/off choices.
    expect(chip.dataset.slot).toBe('toggle-chip');
    expect(chip.hasAttribute('role')).toBe(false);
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    expect(chip.dataset.variant).toBe('secondary');
    expect(chip.dataset.size).toBe('sm');
    expect(chip.dataset.shape).toBe('pill');
    expect(chip.querySelector('svg')).not.toBeNull();
    expect(chip.className).not.toMatch(/success/);
  });

  it('uses the ghost-muted variant without a check when off', () => {
    const onClick = vi.fn();
    const chip = render(false, onClick);
    expect(chip.dataset.variant).toBe('ghost-muted');
    expect(chip.getAttribute('aria-pressed')).toBe('false');
    expect(chip.querySelector('svg')).toBeNull();
    expect(chip.textContent).toBe('Tools');
    act(() => chip.click());
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe('buildInitialFormState', () => {
  const savedModel = (capabilities: Partial<CustomModel['capabilities']>) =>
    ({
      id: 'm1',
      upstream_model_id: 'mistral-large',
      display_name: 'Mistral',
      base_url: 'https://api.mistral.ai/v1',
      capabilities,
      enabled: true,
      source: 'user',
    }) as CustomModel;

  it('turns tools and structured output on for a new model', () => {
    const state = buildInitialFormState(null);
    expect(state.supports_tools).toBe(true);
    expect(state.supports_structured_output).toBe(true);
  });

  it('shows a capability the saved model lacks as off, as the backend applies it', () => {
    // The model registry reads a missing flag as false, so the dialog
    // must not show it as on.
    const state = buildInitialFormState(savedModel({ context_window: 32000 }));
    expect(state.supports_tools).toBe(false);
    expect(state.supports_structured_output).toBe(false);
  });

  it('keeps the stored value of each capability', () => {
    const state = buildInitialFormState(
      savedModel({ supports_tools: true, supports_structured_output: true }),
    );
    expect(state.supports_tools).toBe(true);
    expect(state.supports_structured_output).toBe(true);
  });
});

describe('CustomModelModal capability chips', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const chipPressed = (key: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '[data-slot="toggle-chip"]',
      ),
    )
      .find(
        (chip) =>
          chip.textContent ===
          `settings.customModels.capabilities.chips.${key}`,
      )
      ?.getAttribute('aria-pressed');

  const renderModal = (model: CustomModel | null) => {
    act(() => {
      root.render(
        <CustomModelModal
          modalState="ACTIVE"
          setModalState={vi.fn()}
          model={model}
          onSaved={vi.fn()}
        />,
      );
    });
  };

  it('shows tools and structured output on when creating a model', () => {
    renderModal(null);
    expect(chipPressed('tools')).toBe('true');
    expect(chipPressed('structuredOutput')).toBe('true');
  });

  it('shows both off when editing a model saved without them', () => {
    renderModal({
      id: 'm1',
      upstream_model_id: 'mistral-large',
      display_name: 'Mistral',
      base_url: 'https://api.mistral.ai/v1',
      capabilities: { context_window: 32000 },
      enabled: true,
      source: 'user',
    } as CustomModel);
    expect(chipPressed('tools')).toBe('false');
    expect(chipPressed('structuredOutput')).toBe('false');
  });
});

describe('CustomModelModal for a team', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    Object.values(service).forEach((fn) => fn.mockReset());
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const TEAM_MODEL = {
    id: 'm1',
    upstream_model_id: 'llama-3',
    display_name: 'Team Llama',
    base_url: 'https://llm.example.com/v1',
    capabilities: { context_window: 32000 },
    enabled: true,
    source: 'team',
    owner: 'team',
    team_id: 't1',
    allowed_actions: ['view', 'use', 'manage'],
  } as CustomModel;

  const renderModal = (
    model: CustomModel | null,
    owner?: 'team',
    onSaved = vi.fn(),
  ) => {
    act(() => {
      root.render(
        <CustomModelModal
          modalState="ACTIVE"
          setModalState={vi.fn()}
          model={model}
          onSaved={onSaved}
          owner={owner}
        />,
      );
    });
    return onSaved;
  };

  // The fields in the order the form draws them.
  const inputs = () =>
    Array.from(document.body.querySelectorAll<HTMLInputElement>('input'));
  const type = (input: HTMLInputElement, value: string) =>
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  const button = (label: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent?.trim() === label)!;
  const fillNew = () => {
    const [name, upstream, baseUrl, apiKey] = inputs();
    type(name, 'Team Llama');
    type(upstream, 'llama-3');
    type(baseUrl, 'https://llm.example.com/v1');
    type(apiKey, 'sk-team');
  };

  it("adds the model for the team: the create and the payload test say owner 'team'", async () => {
    service.testCustomModelPayload.mockResolvedValue({ ok: true });
    service.createCustomModel.mockResolvedValue({ ...TEAM_MODEL });
    const onSaved = renderModal(null, 'team');
    fillNew();
    await act(async () =>
      button('settings.customModels.testConnection').click(),
    );
    expect(service.testCustomModelPayload).toHaveBeenCalledWith(
      expect.objectContaining({ owner: 'team', api_key: 'sk-team' }),
      'token',
    );
    await act(async () => button('settings.customModels.save').click());
    expect(service.createCustomModel).toHaveBeenCalledWith(
      expect.objectContaining({ owner: 'team', display_name: 'Team Llama' }),
      'token',
    );
    expect(onSaved).toHaveBeenCalled();
  });

  it('adds a personal model without an owner', async () => {
    service.createCustomModel.mockResolvedValue({ id: 'm2' });
    renderModal(null);
    fillNew();
    await act(async () => button('settings.customModels.save').click());
    expect(service.createCustomModel.mock.calls[0][0]).not.toHaveProperty(
      'owner',
    );
  });

  it('words a refused test by its code', async () => {
    service.testCustomModelPayload.mockResolvedValue({
      ok: false,
      error: 'workspace_role_required',
      code: 'workspace_role_required',
    });
    renderModal(null, 'team');
    fillNew();
    await act(async () =>
      button('settings.customModels.testConnection').click(),
    );
    const alert = document.body.querySelector('[data-slot="alert"]')!;
    expect(alert.textContent).toContain(
      'settings.customModels.team.errors.roleRequired',
    );
    expect(alert.textContent).not.toContain('workspace_role_required');
  });

  it('words a refused save by its code', async () => {
    service.createCustomModel.mockRejectedValue(
      Object.assign(new Error('model_admin_required'), {
        status: 403,
        payload: { success: false, error: 'model_admin_required' },
      }),
    );
    renderModal(null, 'team');
    fillNew();
    await act(async () => button('settings.customModels.save').click());
    expect(document.body.textContent).toContain(
      'settings.customModels.team.errors.modelAdminRequired',
    );
  });

  it("editing a team's model keeps its key when the field is left blank", async () => {
    service.testCustomModel.mockResolvedValue({ ok: true });
    service.updateCustomModel.mockResolvedValue({ ...TEAM_MODEL });
    renderModal(TEAM_MODEL);
    expect(document.body.textContent).toContain(
      'settings.customModels.hints.apiKeyEdit',
    );
    await act(async () =>
      button('settings.customModels.testConnection').click(),
    );
    expect(service.testCustomModel).toHaveBeenCalledWith(
      'm1',
      'token',
      expect.objectContaining({ api_key: '' }),
    );
    await act(async () => button('settings.customModels.save').click());
    const [id, payload] = service.updateCustomModel.mock.calls[0];
    expect(id).toBe('m1');
    expect(payload).not.toHaveProperty('api_key');
    expect(payload).not.toHaveProperty('owner');
  });

  it('asks for the key again once the address moves to another host, and only then', () => {
    renderModal(TEAM_MODEL);
    const [, , baseUrl] = inputs();
    // Another path on the same host keeps the saved key.
    type(baseUrl, 'https://llm.example.com/v2');
    expect(button('settings.customModels.testConnection').disabled).toBe(false);
    expect(button('settings.customModels.save').disabled).toBe(false);
    // Another host (or port, or scheme) needs its own key.
    type(baseUrl, 'https://other.example.com/v1');
    expect(document.body.textContent).toContain(
      'settings.customModels.hints.apiKeyNewHost',
    );
    expect(document.body.textContent).not.toContain(
      'settings.customModels.hints.apiKeyEdit',
    );
    expect(button('settings.customModels.testConnection').disabled).toBe(true);
    expect(button('settings.customModels.save').disabled).toBe(true);
    type(inputs()[3], 'sk-new');
    expect(button('settings.customModels.testConnection').disabled).toBe(false);
    expect(button('settings.customModels.save').disabled).toBe(false);
  });

  it('words a test refused for a new host without its key by its code', async () => {
    service.testCustomModel.mockResolvedValue({
      ok: false,
      error: 'The base URL now points to another host: enter its API key.',
      code: 'api_key_required_for_new_host',
    });
    renderModal(TEAM_MODEL);
    await act(async () =>
      button('settings.customModels.testConnection').click(),
    );
    const alert = document.body.querySelector('[data-slot="alert"]')!;
    expect(alert.textContent).toContain(
      'settings.customModels.errors.apiKeyNewHost',
    );
  });

  it('words a save refused for a new host without its key at the key field', async () => {
    service.updateCustomModel.mockRejectedValue(
      Object.assign(new Error('api_key_required_for_new_host'), {
        status: 400,
        payload: {
          error: 'api_key_required_for_new_host',
          message: 'Enter the API key for the new host.',
        },
      }),
    );
    renderModal(TEAM_MODEL);
    await act(async () => button('settings.customModels.save').click());
    expect(document.body.textContent).toContain(
      'settings.customModels.errors.apiKeyNewHost',
    );
    expect(document.body.textContent).not.toContain('Enter the API key');
  });
});
