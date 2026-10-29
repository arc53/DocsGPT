import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

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
