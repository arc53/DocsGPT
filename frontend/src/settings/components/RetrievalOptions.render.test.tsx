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

  const ON: DecisionFeatures = { relevance: true };

  const withRetrieval = (
    patch: Partial<RetrievalOptionsValue['retrieval']>,
  ): RetrievalOptionsValue => ({
    ...DEFAULT_RETRIEVAL_OPTIONS,
    retrieval: { ...DEFAULT_RETRIEVAL_OPTIONS.retrieval, ...patch },
  });

  const filtering = (min_relevance: number) =>
    withRetrieval({
      reranker: { mode: 'filter', min_relevance, candidate_k: null },
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
  const last = (onChange: ReturnType<typeof vi.fn>) =>
    onChange.mock.calls.at(-1)![0] as RetrievalOptionsValue;
  const advanced = () =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>('button[aria-expanded]'),
    ).find(
      (b) => b.textContent === 'settings.sources.retrievalOptions.advanced',
    )!;
  const strictnessItems = () =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '#retrieval-relevance-strictness [data-slot="toggle-group-item"]',
      ),
    );

  it('hides the Relevance section while the operator has not turned the model on', () => {
    render(filtering(0.3));
    expect(container.querySelector('#retrieval-relevance-mode')).toBeNull();
    expect(text()).not.toContain('relevance.title');
    expect(container.querySelector('#retrieval-relevance-min')).toBeNull();
    // LLM screening is still offered, under Advanced.
    expect(container.querySelector('#retrieval-prescreen')).not.toBeNull();
    expect(text()).not.toContain('prescreen.exclusiveHint');
  });

  it('offers Off, Reorder and Reorder and filter, and no instance default', () => {
    render(DEFAULT_RETRIEVAL_OPTIONS, ON);
    expect(container.querySelector('#retrieval-relevance-mode')).not.toBeNull();
    expect(text()).not.toContain('rerankerChoices');
    // No strictness until the mode filters.
    expect(strictnessItems()).toHaveLength(0);
  });

  it('shows the presets as a segmented control, the stored one on', () => {
    render(filtering(0.5), ON);
    const items = strictnessItems();
    expect(items.map((b) => b.textContent)).toEqual([
      'settings.sources.retrievalOptions.relevance.presets.loose',
      'settings.sources.retrievalOptions.relevance.presets.balanced',
      'settings.sources.retrievalOptions.relevance.presets.strict',
    ]);
    expect(items[2].getAttribute('data-state')).toBe('on');
  });

  it('sets the preset value on a click', () => {
    const onChange = render(filtering(0.3), ON);
    act(() => strictnessItems()[0].click());
    expect(last(onChange).retrieval.reranker.min_relevance).toBe(0.1);
  });

  it('shows a value no preset matches as Custom, and the exact field under Advanced', () => {
    render(filtering(0.25), ON);
    const items = strictnessItems();
    expect(items).toHaveLength(4);
    expect(items[3].getAttribute('data-state')).toBe('on');
    expect(items[3].textContent).toBe(
      'settings.sources.retrievalOptions.relevance.presets.custom',
    );
    // A custom value opens Advanced so the number is in view.
    expect(advanced().getAttribute('aria-expanded')).toBe('true');
    const exact = container.querySelector(
      '#retrieval-relevance-min',
    ) as HTMLInputElement;
    expect(exact.value).toBe('0.25');
    expect(exact.max).toBe('1');
  });

  it('keeps Advanced closed for preset values until opened', () => {
    render(filtering(0.3), ON);
    expect(advanced().getAttribute('aria-expanded')).toBe('false');
    act(() => advanced().click());
    expect(advanced().getAttribute('aria-expanded')).toBe('true');
    const candidates = container.querySelector(
      '#retrieval-relevance-candidates',
    ) as HTMLInputElement;
    expect(candidates.value).toBe('20');
    expect(candidates.max).toBe('100');
  });

  it('renames the score threshold to the similarity threshold, under Advanced', () => {
    render(DEFAULT_RETRIEVAL_OPTIONS, ON);
    expect(text()).toContain('retrieval.similarityThreshold');
    expect(text()).not.toContain('scoreThreshold');
    const field = container.querySelector('#retrieval-score-threshold')!;
    expect(field.closest('[data-slot="collapsible"]')).not.toBeNull();
  });

  it('turns relevance off when LLM screening is turned on', () => {
    const onChange = render(filtering(0.3), ON);
    act(() => advanced().click());
    act(() =>
      (
        container.querySelector('#retrieval-prescreen') as HTMLButtonElement
      ).click(),
    );
    const next = last(onChange);
    expect(next.retrieval.prescreen.enabled).toBe(true);
    expect(next.retrieval.reranker.mode).toBe('off');
    expect(text()).toContain('prescreen.exclusiveHint');
  });

  it('shows LLM screening without a backend picker or minimum relevance', () => {
    render(
      withRetrieval({
        prescreen: {
          ...DEFAULT_RETRIEVAL_OPTIONS.retrieval.prescreen,
          enabled: true,
        },
      }),
      ON,
    );
    // An enabled screening opens Advanced.
    expect(advanced().getAttribute('aria-expanded')).toBe('true');
    expect(text()).toContain('prescreen.batchSize');
    expect(text()).not.toContain('prescreen.backend');
    expect(container.querySelector('#retrieval-relevance-min')).toBeNull();
  });

  it('hides the ingest-time groups for the defaults page', () => {
    act(() => {
      root.render(
        <RetrievalOptions
          value={DEFAULT_RETRIEVAL_OPTIONS}
          onChange={vi.fn()}
          alwaysOpen
          retrievalOnly
        />,
      );
    });
    expect(
      container.querySelector('#chunking-strategy')!.closest('.hidden'),
    ).not.toBeNull();
    // Unlike the retrieval test, both answer-time knobs stay.
    expect(container.querySelector('#retrieval-rephrase')).not.toBeNull();
    expect(container.querySelector('#retrieval-exposure')).not.toBeNull();
  });
});
