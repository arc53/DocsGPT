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
  getSourceDefaults: vi.fn(),
  setSourceDefaults: vi.fn(),
  getAgentDefaults: vi.fn(),
  setAgentDefaults: vi.fn(),
}));
vi.mock('../api/services/adminService', () => ({ default: admin }));
vi.mock('../api/services/userService', () => ({
  default: {
    getConfig: () => Promise.resolve({ json: async () => ({}) }),
    getGuardrailCatalog: () =>
      Promise.resolve({
        json: async () => ({
          success: true,
          enabled: true,
          checks: [
            {
              name: 'injection_model',
              label: 'Prompt injection (model)',
              description: 'Scores text',
              stages: ['input', 'retrieval'],
              supports_redaction: false,
              latency_hint_ms: 300,
              remote: true,
              item_level: true,
              available: true,
            },
          ],
          stages: ['input', 'retrieval'],
          modes: ['monitor_only', 'scan_all'],
          actions_by_stage: { input: ['flag', 'block'] },
          default_block_message: 'No',
          pii_entities: [],
          default_pii_entities: [],
          floor: null,
        }),
      }),
  },
}));

import Defaults from './Defaults';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const model = (over: Record<string, unknown> = {}) => ({
  enabled: true,
  predicted_s: 2.71,
  timeout_s: 8,
  candidate_k: 20,
  runtime: 'onnx-int8',
  ...over,
});

const injectionModel = (over: Record<string, unknown> = {}) => ({
  enabled: true,
  runtime: 'onnx-int8',
  predicted_input_s: 0.3,
  timeout_s: 2,
  ...over,
});

const body = (over: Record<string, unknown> = {}, retrieval = {}) => ({
  json: async () => ({
    success: true,
    retrieval: { retriever: 'classic', chunks: 6, ...retrieval },
    relevance_model: model(over),
  }),
});

const agentGuardrails = {
  enabled: false,
  mode: 'monitor_only',
  fail_open: true,
  timeout_ms: 2000,
  block_message: "Sorry, I can't help with that request.",
  controls: [],
};

const agentsBody = (guardrails = agentGuardrails, over = {}) => ({
  json: async () => ({
    success: true,
    guardrails,
    injection_model: injectionModel(over),
  }),
});

describe('Admin Defaults', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    admin.getSourceDefaults.mockReset();
    admin.setSourceDefaults.mockReset();
    admin.getAgentDefaults.mockReset();
    admin.setAgentDefaults.mockReset();
    admin.getAgentDefaults.mockResolvedValue(agentsBody());
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () => root.render(<Defaults />));
    for (let i = 0; i < 3; i += 1) await act(async () => Promise.resolve());
  };

  const text = () => container.textContent ?? '';
  const save = () =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === 'Save',
    )!;
  const typeInto = async (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  it('says what it applies to and what relevance costs on this server', async () => {
    admin.getSourceDefaults.mockResolvedValue(body());
    await render();
    expect(text()).toContain(
      'The settings new sources and new agents start with.',
    );
    expect(text()).toContain(
      'Applies to sources created from now on. Existing sources keep their own settings.',
    );
    expect(text()).toContain(
      'Applies to agents created from now on. Existing agents keep their own guardrails.',
    );
    expect(text()).toContain(
      'Adds about 2.7 s per answer on this server (20 candidates, onnx-int8).',
    );
    expect(text()).not.toContain('will time out');
    expect(container.querySelector('#retrieval-relevance-mode')).not.toBeNull();
  });

  it('says the cost is measured once the model loads', async () => {
    admin.getSourceDefaults.mockResolvedValue(body({ predicted_s: null }));
    await render();
    expect(text()).toContain('measured after the model loads');
  });

  it('warns when one call outlasts the relevance timeout', async () => {
    admin.getSourceDefaults.mockResolvedValue(body({ predicted_s: 27.4 }));
    await render();
    const warning = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="alert"]'),
    ).find((el) => el.textContent?.includes('will time out'));
    expect(warning?.className).toContain('text-warning');
    expect(warning?.textContent).toContain('8.0 s timeout');
    expect(warning?.textContent).toContain('DECISION_RELEVANCE_TIMEOUT');
  });

  it('hides relevance and says how to turn the model on while it is off', async () => {
    admin.getSourceDefaults.mockResolvedValue(body({ enabled: false }));
    await render();
    expect(text()).toContain('DECISION_RELEVANCE_ENABLED');
    expect(text()).not.toContain('Adds about');
    expect(container.querySelector('#retrieval-relevance-mode')).toBeNull();
    // LLM screening stays offered.
    expect(container.querySelector('#retrieval-prescreen')).not.toBeNull();
  });

  it('saves the edited retrieval settings and settles on what came back', async () => {
    admin.getSourceDefaults.mockResolvedValue(body());
    admin.setSourceDefaults.mockResolvedValue(body({}, { chunks: 9 }));
    await render();
    expect(save().disabled).toBe(true);
    await typeInto(
      container.querySelector<HTMLInputElement>('#retrieval-chunks')!,
      '9',
    );
    expect(save().disabled).toBe(false);
    await act(async () => save().click());
    const [retrieval, token] = admin.setSourceDefaults.mock.calls[0];
    expect(token).toBe('tok');
    expect(admin.setAgentDefaults).not.toHaveBeenCalled();
    expect(retrieval.chunks).toBe(9);
    expect(retrieval.reranker).toBe(null);
    expect(retrieval).not.toHaveProperty('chunking');
    expect(save().disabled).toBe(true);
  });

  it('keeps an edit made while the save is pending', async () => {
    admin.getSourceDefaults.mockResolvedValue(body());
    let respond: (value: unknown) => void = () => {};
    admin.setSourceDefaults.mockReturnValue(
      new Promise((resolve) => {
        respond = resolve;
      }),
    );
    await render();
    const chunks = () =>
      container.querySelector<HTMLInputElement>('#retrieval-chunks')!;
    await typeInto(chunks(), '9');
    await act(async () => save().click());
    await typeInto(chunks(), '12');
    await act(async () => respond(body({}, { chunks: 9 })));
    for (let i = 0; i < 3; i += 1) await act(async () => Promise.resolve());
    expect(chunks().value).toBe('12');
    expect(save().disabled).toBe(false);
  });

  it('shows a refused save above the form', async () => {
    admin.getSourceDefaults.mockResolvedValue(body());
    admin.setSourceDefaults.mockResolvedValue({
      json: async () => ({
        success: false,
        message:
          'Relevance and LLM screening cannot both be on: set reranker or prescreen, not both.',
      }),
    });
    await render();
    await typeInto(
      container.querySelector<HTMLInputElement>('#retrieval-chunks')!,
      '9',
    );
    await act(async () => save().click());
    const error = container.querySelector<HTMLElement>(
      '[data-slot="alert"][role="alert"].text-destructive',
    );
    expect(error?.textContent).toContain('cannot both be on');
  });

  it('says how to turn the model on while it is off', async () => {
    admin.getSourceDefaults.mockResolvedValue(body());
    admin.getAgentDefaults.mockResolvedValue(
      agentsBody(agentGuardrails, { enabled: false }),
    );
    await render();
    expect(text()).toContain('DECISION_INJECTION_ENABLED=true');
    // The model check is not offered for new agents.
    expect(
      container.querySelector(
        '[data-testid="guardrail-check-injection_model"]',
      ),
    ).toBeNull();
  });

  it('saves the guardrails new agents start with', async () => {
    admin.getSourceDefaults.mockResolvedValue(body());
    const enabled = { ...agentGuardrails, enabled: true };
    admin.setAgentDefaults.mockResolvedValue(agentsBody(enabled));
    await render();
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-testid="guardrails-enabled"]')!
        .click(),
    );
    await act(async () => save().click());
    expect(admin.setSourceDefaults).not.toHaveBeenCalled();
    expect(admin.setAgentDefaults).toHaveBeenCalledWith(enabled, 'tok');
    expect(save().disabled).toBe(true);
  });

  it('offers a retry when the defaults fail to load', async () => {
    admin.getSourceDefaults.mockRejectedValue(new Error('network'));
    await render();
    expect(text()).toContain('Failed to load the defaults.');
  });
});
