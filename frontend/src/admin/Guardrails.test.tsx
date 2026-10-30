import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});
vi.mock('react-redux', () => ({
  useSelector: () => 'tok',
}));

const admin = vi.hoisted(() => ({
  getGuardrails: vi.fn(),
  setGuardrails: vi.fn(),
}));
vi.mock('../api/services/adminService', () => ({ default: admin }));
const user = vi.hoisted(() => ({ getGuardrailCatalog: vi.fn() }));
vi.mock('../api/services/userService', () => ({ default: user }));

import Guardrails from './Guardrails';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const model = (over: Record<string, unknown> = {}) => ({
  enabled: true,
  runtime: 'onnx-int8',
  predicted_input_s: 0.31,
  timeout_s: 2,
  ...over,
});

const floor = {
  enabled: true,
  mode: 'scan_all',
  fail_open: true,
  timeout_ms: 2000,
  block_message: "Sorry, I can't help with that request.",
  controls: [
    {
      check: 'injection_model',
      stage: 'input',
      action: 'flag',
      enabled: true,
      settings: { threshold: 0.9, flag_threshold: 0.5 },
    },
  ],
};

const body = (over: Record<string, unknown> = {}) => ({
  json: async () => ({
    success: true,
    floor,
    mcp_description_warnings: false,
    injection_model: model(),
    ...over,
  }),
});

const catalog = {
  success: true,
  enabled: true,
  checks: [
    {
      name: 'injection_model',
      label: 'Prompt injection (model)',
      description: 'Scores text',
      stages: ['attachment', 'input', 'retrieval', 'tool_result'],
      supports_redaction: false,
      latency_hint_ms: 300,
      remote: true,
      item_level: true,
      available: true,
    },
  ],
  stages: ['input', 'retrieval', 'tool_result', 'output', 'attachment'],
  modes: ['monitor_only', 'scan_all'],
  actions_by_stage: { input: ['flag', 'block'] },
  default_block_message: 'No',
  pii_entities: [],
  default_pii_entities: [],
  // The stored floor, which the editor must not show as locking itself.
  floor,
};

describe('Admin Guardrails', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    admin.getGuardrails.mockReset();
    admin.setGuardrails.mockReset();
    user.getGuardrailCatalog.mockReset();
    user.getGuardrailCatalog.mockResolvedValue({ json: async () => catalog });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () => root.render(<Guardrails />));
    for (let i = 0; i < 3; i += 1) await act(async () => Promise.resolve());
  };

  const text = () => container.textContent ?? '';
  const q = (testId: string) =>
    container.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
  const save = () =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === 'Save',
    )!;

  it('edits the rules every agent follows with the agent guardrails controls', async () => {
    admin.getGuardrails.mockResolvedValue(body());
    await render();
    expect(text()).toContain(
      'Rules every agent follows, existing agents included.',
    );
    expect(text()).toContain('Apply these rules to every agent');
    const chip = q('guardrail-stage-injection_model-input')!;
    // Its own control, not one locked by the floor it is editing.
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    expect(chip.getAttribute('aria-disabled')).toBeNull();
    expect(q('guardrail-remove-injection_model-input')).not.toBeNull();
  });

  it('says what the model costs on this server', async () => {
    admin.getGuardrails.mockResolvedValue(body());
    await render();
    expect(text()).toContain(
      'Checking a user message adds about 0.3 s on this server (onnx-int8).',
    );
    expect(text()).not.toContain('will time out');
  });

  it('warns when one check outlasts its deadline', async () => {
    admin.getGuardrails.mockResolvedValue(
      body({ injection_model: model({ predicted_input_s: 4.2 }) }),
    );
    await render();
    expect(text()).toContain('The check will time out on this server');
  });

  it('says how to turn the model on while it is off', async () => {
    admin.getGuardrails.mockResolvedValue(
      body({ injection_model: model({ enabled: false }) }),
    );
    await render();
    expect(text()).toContain('DECISION_INJECTION_ENABLED=true');
    expect(text()).not.toContain('Checking a user message');
  });

  it('saves only what changed and settles on the answer', async () => {
    admin.getGuardrails.mockResolvedValue(body());
    admin.setGuardrails.mockResolvedValue(
      body({ mcp_description_warnings: true }),
    );
    await render();
    expect(save().disabled).toBe(true);
    await act(async () => q('mcp-description-warnings')!.click());
    expect(save().disabled).toBe(false);
    await act(async () => save().click());
    expect(admin.setGuardrails).toHaveBeenCalledWith(
      { mcp_description_warnings: true },
      'tok',
    );
    expect(save().disabled).toBe(true);
    // The catalog is read again, for the floor the agent forms lock.
    expect(user.getGuardrailCatalog).toHaveBeenCalledTimes(2);
  });

  it('sends the edited floor', async () => {
    admin.getGuardrails.mockResolvedValue(body());
    admin.setGuardrails.mockResolvedValue(body({ floor: null }));
    await render();
    await act(async () => q('guardrail-remove-injection_model-input')!.click());
    await act(async () => save().click());
    const [sent] = admin.setGuardrails.mock.calls[0];
    expect(sent).toEqual({ floor: { ...floor, controls: [] } });
  });

  it('shows a refused save above the form', async () => {
    admin.getGuardrails.mockResolvedValue(body());
    admin.setGuardrails.mockResolvedValue({
      json: async () => ({
        success: false,
        message: "floor.controls.0.check: unknown check 'x'",
      }),
    });
    await render();
    await act(async () => q('mcp-description-warnings')!.click());
    await act(async () => save().click());
    const error = container.querySelector<HTMLElement>(
      '[data-slot="alert"][role="alert"].text-destructive',
    );
    expect(error?.textContent).toContain("unknown check 'x'");
  });

  it('offers a retry when the settings fail to load', async () => {
    admin.getGuardrails.mockRejectedValue(new Error('network'));
    await render();
    expect(text()).toContain('Failed to load the guardrails.');
  });
});
