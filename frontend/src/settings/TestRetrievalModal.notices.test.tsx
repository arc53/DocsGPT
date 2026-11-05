import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const testSourceRetrieval = vi.fn();
const updateSourceConfig = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    testSourceRetrieval: (...args: unknown[]) => testSourceRetrieval(...args),
    updateSourceConfig: (...args: unknown[]) => updateSourceConfig(...args),
  },
}));

import type { Doc } from '../models/misc';
import TestRetrievalModal from './TestRetrievalModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const doc = (config: Doc['config'], fields: Partial<Doc> = {}): Doc =>
  ({ id: 'src-1', name: 'Handbook', config, ...fields }) as Doc;

const alerts = () =>
  Array.from(document.body.querySelectorAll<HTMLElement>('[role="alert"]'));

describe('TestRetrievalModal notices', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    testSourceRetrieval.mockReset();
    updateSourceConfig.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = (document: Doc) =>
    act(() => {
      root.render(
        <TestRetrievalModal
          modalState="ACTIVE"
          setModalState={() => undefined}
          document={document}
        />,
      );
    });

  it('sizes the Run button to the query field row', () => {
    render(doc(undefined));
    const run = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('[data-slot="button"]'),
    ).find((b) => b.textContent === 'settings.sources.testRetrieval.run');
    expect(run?.getAttribute('data-size')).toBe('field');
    expect(run?.getAttribute('data-shape')).toBe('default');
    // 38px, the height of the Input beside it.
    expect(run?.className).toContain('h-9.5');
  });

  it('shows an invalid prescreen config as a warning Alert with an icon', () => {
    render(
      doc({
        retrieval: { chunks: 10, prescreen: { candidate_k: 5, max_keep: 3 } },
      } as Doc['config']),
    );

    const warning = alerts().find((el) =>
      el.textContent?.includes(
        'settings.sources.configModal.prescreenInvalidHint',
      ),
    );
    expect(warning).toBeDefined();
    expect(warning?.className).toContain('text-warning');
    expect(warning?.querySelector('svg')).not.toBeNull();
  });

  it('shows a failed run as a destructive Alert with an icon', async () => {
    testSourceRetrieval.mockRejectedValue(new Error('network'));
    render(doc(undefined));

    const input =
      document.body.querySelector<HTMLInputElement>('input[type="text"]');
    expect(input).not.toBeNull();
    const setValue = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )?.set;
    act(() => {
      setValue?.call(input, 'fuel surcharge');
      input?.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      input?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });

    const error = alerts().find((el) =>
      el.textContent?.includes('settings.sources.testRetrieval.errors.failed'),
    );
    expect(error).toBeDefined();
    expect(error?.className).toContain('text-destructive');
    expect(error?.querySelector('svg')).not.toBeNull();
  });

  it('says no chunks in a small text-only EmptyState, not a dashed box', async () => {
    testSourceRetrieval.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        chunks: [],
        total: 0,
        retriever: 'classic',
        latency_ms: 84,
      }),
    });
    render(doc(undefined));
    const input =
      document.body.querySelector<HTMLInputElement>('input[type="text"]');
    const setValue = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )?.set;
    act(() => {
      setValue?.call(input, 'fuel surcharge');
      input?.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      input?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    const empty = document.body.querySelector<HTMLElement>(
      '[data-slot="empty-state"]',
    );
    expect(empty?.dataset.size).toBe('sm');
    expect(empty?.querySelector('svg')).toBeNull();
    expect(document.body.querySelector('.border-dashed')).toBeNull();
  });

  // O5: a result is a place on the modal's card surface (outline Card), and
  // its rank a neutral Badge rather than a fill on a fill.
  it('draws each result as an outline Card with a neutral rank Badge', async () => {
    testSourceRetrieval.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        chunks: [
          {
            rank: 1,
            text: '7.2 Insurance.',
            title: 'Nordhaven',
            filename: 'nordhaven.pdf',
            source: 'nordhaven.pdf',
            tokens: 412,
            score: 0.84,
            score_kind: 'cosine_similarity',
          },
        ],
        total: 1,
        retriever: 'classic',
        latency_ms: 84,
      }),
    });
    render(doc(undefined));
    const input =
      document.body.querySelector<HTMLInputElement>('input[type="text"]');
    const setValue = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )?.set;
    act(() => {
      setValue?.call(input, 'insurance');
      input?.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      input?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    const rank = Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-slot="badge"]'),
    ).find((el) => el.textContent === '#1')!;
    expect(rank).toBeDefined();
    expect(rank.dataset.variant).toBe('neutral');
    expect(rank.className).toContain('font-mono');
    const card = rank.closest<HTMLElement>('[data-slot="card"]')!;
    expect(card).not.toBeNull();
    expect(card.dataset.variant).toBe('outline');
    expect(card.className).not.toContain('bg-muted');
  });

  it('offers the comparison only where the operator turned the model on, and sends it', async () => {
    render(doc(undefined));
    expect(document.body.querySelector('#test-retrieval-compare')).toBeNull();

    testSourceRetrieval.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        chunks: [
          {
            rank: 1,
            text: 'Insurance terms.',
            title: 'Nordhaven',
            filename: 'nordhaven.pdf',
            source: 'nordhaven.pdf',
            tokens: 12,
            score: 0.71,
            score_kind: 'cosine_similarity',
            relevance: 0.88,
          },
        ],
        candidates: [
          {
            rank: null,
            rank_before: 1,
            text: 'Fleet list.',
            title: 'Nordhaven',
            filename: 'nordhaven.pdf',
            source: 'nordhaven.pdf',
            tokens: 9,
            score: 0.84,
            score_kind: 'cosine_similarity',
            relevance: 0.03,
            kept: false,
            baseline: true,
          },
        ],
        relevance: { applied: true, fallback: null, latency_ms: 240 },
        total: 1,
        retriever: 'classic',
        latency_ms: 300,
      }),
    });
    act(() => {
      root.render(
        <TestRetrievalModal
          modalState="ACTIVE"
          setModalState={() => undefined}
          document={doc(undefined)}
          decision={{ relevance: true }}
        />,
      );
    });
    const toggle = document.body.querySelector<HTMLButtonElement>(
      '#test-retrieval-compare',
    );
    expect(toggle).not.toBeNull();
    act(() => toggle!.click());

    const input =
      document.body.querySelector<HTMLInputElement>('input[type="text"]');
    const setValue = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )?.set;
    act(() => {
      setValue?.call(input, 'insurance');
      input?.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      input?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    expect(testSourceRetrieval.mock.calls[0][1].compare).toBe(true);
    const text = document.body.textContent ?? '';
    expect(text).toContain(
      'settings.sources.testRetrieval.relevanceRun.applied',
    );
    expect(text).toContain('settings.sources.testRetrieval.compareTitle');
    expect(text).toContain(
      'settings.sources.testRetrieval.compareStatus.dropped',
    );
    expect(text).toContain('88%');
  });

  const okRun = () =>
    testSourceRetrieval.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        chunks: [],
        total: 0,
        retriever: 'classic',
        latency_ms: 50,
      }),
    });

  const renderWith = (document: Doc, onSaved = vi.fn()) => {
    act(() => {
      root.render(
        <TestRetrievalModal
          modalState="ACTIVE"
          setModalState={() => undefined}
          document={document}
          decision={{ relevance: true }}
          onSaved={onSaved}
        />,
      );
    });
    return onSaved;
  };

  const typeQuery = (value: string) => {
    const input =
      document.body.querySelector<HTMLInputElement>('input[type="text"]')!;
    const setValue = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )?.set;
    act(() => {
      setValue?.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    return input;
  };

  const pick = (label: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '[data-slot="toggle-group-item"]',
      ),
    ).find(
      (b) =>
        b.textContent ===
        `settings.sources.retrievalOptions.relevance.${label}`,
    )!;

  const saveButton = () =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find(
      (b) => b.textContent === 'settings.sources.testRetrieval.saveToSource',
    );

  it('re-runs the test with the strictness picked next to the query', async () => {
    okRun();
    renderWith(doc(undefined));
    typeQuery('insurance');
    expect(pick('modes.off').getAttribute('data-state')).toBe('on');
    await act(async () => pick('presets.strict').click());
    expect(testSourceRetrieval).toHaveBeenCalledTimes(1);
    expect(testSourceRetrieval.mock.calls[0][1].retrieval.reranker).toEqual({
      type: 'decision',
      min_relevance: 0.5,
      candidate_k: null,
    });
    await act(async () => pick('modes.reorder').click());
    expect(testSourceRetrieval.mock.calls[1][1].retrieval.reranker).toEqual({
      type: 'decision',
      min_relevance: null,
      candidate_k: null,
    });
  });

  it('offers no strictness picker while the model is off', () => {
    render(doc(undefined));
    expect(
      document.body.querySelector('[data-slot="toggle-group-item"]'),
    ).toBeNull();
  });

  it('saves the tested retrieval block to the source for an editor', async () => {
    okRun();
    updateSourceConfig.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    });
    const onSaved = renderWith(
      doc({ retrieval: { chunks: 4 }, chunking: { max_tokens: 900 } }),
    );
    // Nothing tested yet, so nothing to save.
    expect(saveButton()?.disabled).toBe(true);
    typeQuery('insurance');
    await act(async () => pick('presets.balanced').click());
    expect(saveButton()?.disabled).toBe(false);
    await act(async () => saveButton()!.click());

    const [id, body] = updateSourceConfig.mock.calls[0];
    expect(id).toBe('src-1');
    // The whole tested retrieval block, and only it: the PATCH keeps the rest.
    expect(Object.keys(body)).toEqual(['retrieval']);
    expect(body.retrieval).toEqual(
      testSourceRetrieval.mock.calls[0][1].retrieval,
    );
    expect(body.retrieval.chunks).toBe(4);
    expect(body.retrieval.reranker.min_relevance).toBe(0.3);
    expect(onSaved).toHaveBeenCalledWith(body.retrieval);
    expect(document.body.textContent).toContain(
      'settings.sources.testRetrieval.savedToSource',
    );
  });

  it('offers no Save to source to a viewer', () => {
    renderWith(
      doc(undefined, {
        access: 'viewer',
        allowed_actions: ['use', 'view_config'],
      }),
    );
    expect(saveButton()).toBeUndefined();
    expect(document.body.textContent).toContain(
      'settings.sources.testRetrieval.notSavedHint',
    );
  });
});
