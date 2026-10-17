import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({
  useSelector: () => 'tok',
}));

const admin = vi.hoisted(() => ({
  getSourceDefaults: vi.fn(),
  setSourceDefaults: vi.fn(),
}));
vi.mock('../api/services/adminService', () => ({ default: admin }));
vi.mock('../api/services/userService', () => ({
  default: {
    getConfig: () => Promise.resolve({ json: async () => ({}) }),
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

const body = (over: Record<string, unknown> = {}, retrieval = {}) => ({
  json: async () => ({
    success: true,
    retrieval: { retriever: 'classic', chunks: 6, ...retrieval },
    relevance_model: model(over),
  }),
});

describe('Admin Defaults', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    admin.getSourceDefaults.mockReset();
    admin.setSourceDefaults.mockReset();
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
    expect(text()).toContain('Default retrieval settings for new sources');
    expect(text()).toContain(
      'Applies to sources created from now on. Existing sources keep their own settings.',
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
    expect(retrieval.chunks).toBe(9);
    expect(retrieval.reranker).toBe(null);
    expect(retrieval).not.toHaveProperty('chunking');
    expect(save().disabled).toBe(true);
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

  it('offers a retry when the defaults fail to load', async () => {
    admin.getSourceDefaults.mockRejectedValue(new Error('network'));
    await render();
    expect(text()).toContain('Failed to load the defaults.');
  });
});
