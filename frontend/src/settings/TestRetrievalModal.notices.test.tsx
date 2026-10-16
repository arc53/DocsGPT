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
vi.mock('../api/services/userService', () => ({
  default: {
    testSourceRetrieval: (...args: unknown[]) => testSourceRetrieval(...args),
  },
}));

import type { Doc } from '../models/misc';
import TestRetrievalModal from './TestRetrievalModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const doc = (config: Doc['config']): Doc =>
  ({ id: 'src-1', name: 'Handbook', config }) as Doc;

const alerts = () =>
  Array.from(document.body.querySelectorAll<HTMLElement>('[role="alert"]'));

describe('TestRetrievalModal notices', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    testSourceRetrieval.mockReset();
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
          decision={{ rerank: true, prescreen: false }}
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
});
