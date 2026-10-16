import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import RetrievalOptions, {
  DEFAULT_RETRIEVAL_OPTIONS,
  type DecisionFeatures,
  type RetrievalOptionsValue,
} from './RetrievalOptions';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('RetrievalOptions disclosure', () => {
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

  it('opens the options in a Collapsible the toggle controls', () => {
    act(() => {
      root.render(
        <RetrievalOptions
          value={DEFAULT_RETRIEVAL_OPTIONS}
          onChange={vi.fn()}
        />,
      );
    });
    const toggle = container.querySelector(
      'button[aria-expanded]',
    ) as HTMLButtonElement;
    const body = container.querySelector('[data-slot="collapsible"]');
    expect(body).not.toBeNull();
    expect(toggle.getAttribute('aria-controls')).toBe(body!.id);
    expect(body!.getAttribute('data-state')).toBe('closed');
    act(() => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body!.getAttribute('data-state')).toBe('open');
  });

  it('leaves no gap under the closed toggle: the body carries the space', () => {
    act(() => {
      root.render(
        <RetrievalOptions
          value={DEFAULT_RETRIEVAL_OPTIONS}
          onChange={vi.fn()}
        />,
      );
    });
    const wrapper = container.firstElementChild as HTMLElement;
    expect(wrapper.className.split(' ')).not.toContain('gap-4');
    const collapsible = container.querySelector(
      '[data-slot="collapsible"]',
    ) as HTMLElement;
    const inner = collapsible.firstElementChild!
      .firstElementChild as HTMLElement;
    expect(inner.className.split(' ')).toContain('pt-4');
  });

  it('caps the chunk-size input and explains the limit', () => {
    act(() => {
      root.render(
        <RetrievalOptions
          value={DEFAULT_RETRIEVAL_OPTIONS}
          onChange={vi.fn()}
          alwaysOpen
        />,
      );
    });

    const input = container.querySelector(
      '#chunking-max-tokens',
    ) as HTMLInputElement;
    expect(input.max).toBe('4096');
    expect(container.textContent).toContain('chunking.maxTokensHint');
  });
});

describe('RetrievalOptions relevance controls', () => {
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

  const withPrescreen = (
    backend: 'llm' | 'decision',
  ): RetrievalOptionsValue => ({
    ...DEFAULT_RETRIEVAL_OPTIONS,
    retrieval: {
      ...DEFAULT_RETRIEVAL_OPTIONS.retrieval,
      prescreen: {
        ...DEFAULT_RETRIEVAL_OPTIONS.retrieval.prescreen,
        enabled: true,
        backend,
      },
    },
  });

  const render = (
    value: RetrievalOptionsValue,
    decision?: DecisionFeatures,
    onChange = vi.fn(),
  ) => {
    act(() => {
      root.render(
        <RetrievalOptions
          value={value}
          onChange={onChange}
          alwaysOpen
          decision={decision}
        />,
      );
    });
    return onChange;
  };

  const text = () => container.textContent ?? '';

  it('hides every decision-model control while the operator has not turned it on', () => {
    render(withPrescreen('decision'));
    expect(container.querySelector('#retrieval-reranker')).toBeNull();
    expect(text()).not.toContain('prescreen.backend');
    expect(text()).not.toContain('relevance.minRelevance');
    // A stored decision prescreen runs on the LLM then, so it shows the LLM's knobs.
    expect(text()).toContain('prescreen.batchSize');
    expect(text()).toContain('prescreen.enable');
    expect(text()).not.toContain('prescreen.enableAny');
  });

  it('offers the reranker, and its minimum relevance only when it is on', () => {
    render(DEFAULT_RETRIEVAL_OPTIONS, { rerank: true, prescreen: false });
    expect(container.querySelector('#retrieval-reranker')).not.toBeNull();
    expect(
      container.querySelector('#retrieval-reranker-min-relevance'),
    ).toBeNull();
    render(
      {
        ...DEFAULT_RETRIEVAL_OPTIONS,
        retrieval: {
          ...DEFAULT_RETRIEVAL_OPTIONS.retrieval,
          reranker: { choice: 'on', min_relevance: 0.3, candidate_k: null },
        },
      },
      { rerank: true, prescreen: false },
    );
    const input = container.querySelector(
      '#retrieval-reranker-min-relevance',
    ) as HTMLInputElement;
    expect(input.value).toBe('0.3');
    expect(input.max).toBe('1');
  });

  it('shows the backend and minimum relevance for a prescreen on the model', () => {
    render(withPrescreen('decision'), { rerank: false, prescreen: true });
    expect(text()).toContain('prescreen.backend');
    expect(text()).toContain('relevance.minRelevance');
    expect(text()).not.toContain('prescreen.batchSize');
    expect(text()).toContain('prescreen.enableAny');
    expect(container.querySelector('#retrieval-reranker')).toBeNull();
  });

  it.each(['decision', 'llm'] as const)(
    'explains when the decision cap leaves no candidate count above the chunks (%s)',
    (backend) => {
      const value = withPrescreen(backend);
      render({
        ...value,
        retrieval: {
          ...value.retrieval,
          chunks: 120,
          prescreen: { ...value.retrieval.prescreen, candidate_k: 120 },
        },
      });
      const alert = container.querySelector('[role="alert"]');
      if (backend === 'decision') {
        expect(alert?.textContent).toBe(
          'settings.sources.retrievalOptions.prescreen.candidateKAboveDecisionMax',
        );
        const field = container.querySelector(
          'input[aria-invalid="true"]',
        ) as HTMLInputElement;
        expect(field.value).toBe('120');
      } else {
        expect(alert).toBeNull();
      }
    },
  );

  it('shows no candidate error while the chunks fit the decision cap', () => {
    render(withPrescreen('decision'), { rerank: false, prescreen: true });
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it.each([
    [{ rerank: false, prescreen: true }, 'decision'],
    [{ rerank: true, prescreen: false }, 'llm'],
  ])(
    'preselects the backend of a newly enabled prescreen (%j → %s)',
    (decision, backend) => {
      const onChange = render(DEFAULT_RETRIEVAL_OPTIONS, decision);
      const toggle = container.querySelector(
        '#retrieval-prescreen',
      ) as HTMLButtonElement;
      act(() => toggle.click());
      const next = onChange.mock.calls[0][0] as RetrievalOptionsValue;
      expect(next.retrieval.prescreen.enabled).toBe(true);
      expect(next.retrieval.prescreen.backend).toBe(backend);
    },
  );
});
