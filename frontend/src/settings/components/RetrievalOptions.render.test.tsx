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

  it('offers the file-link switch only where the source has links', () => {
    const onChange = vi.fn();
    act(() => {
      root.render(
        <RetrievalOptions
          value={DEFAULT_RETRIEVAL_OPTIONS}
          onChange={onChange}
          alwaysOpen
        />,
      );
    });
    expect(container.querySelector('#retrieval-show-links')).toBeNull();

    act(() => {
      root.render(
        <RetrievalOptions
          value={DEFAULT_RETRIEVAL_OPTIONS}
          onChange={onChange}
          alwaysOpen
          linksAvailable
        />,
      );
    });
    const toggle = container.querySelector(
      '#retrieval-show-links',
    ) as HTMLButtonElement;
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    act(() => toggle.click());
    expect(onChange.mock.calls.at(-1)![0].retrieval.show_links).toBe(false);
  });

  it('keeps the file-link switch in the Retrieval group, shown on a create form', () => {
    act(() => {
      root.render(
        <RetrievalOptions
          value={DEFAULT_RETRIEVAL_OPTIONS}
          onChange={vi.fn()}
          alwaysOpen
          linksAvailable
          variant="create"
        />,
      );
    });
    // A create form leaves the Filtering group out; the switch is still there.
    expect(container.querySelector('#retrieval-prescreen')).toBeNull();
    expect(container.querySelector('#retrieval-show-links')).not.toBeNull();
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
    // LLM screening is still offered, under Filtering.
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

  it('shows a value no preset matches as Custom, and the exact field under Filtering', () => {
    render(filtering(0.25), ON);
    const items = strictnessItems();
    expect(items).toHaveLength(4);
    expect(items[3].getAttribute('data-state')).toBe('on');
    expect(items[3].textContent).toBe(
      'settings.sources.retrievalOptions.relevance.presets.custom',
    );
    const exact = container.querySelector(
      '#retrieval-relevance-min',
    ) as HTMLInputElement;
    expect(exact.value).toBe('0.25');
    expect(exact.max).toBe('1');
  });

  it('shows the candidates to score while relevance is on, with no toggle', () => {
    render(filtering(0.3), ON);
    expect(container.querySelector('button[aria-controls]')).toBeNull();
    const candidates = container.querySelector(
      '#retrieval-relevance-candidates',
    ) as HTMLInputElement;
    expect(candidates.value).toBe('20');
    expect(candidates.max).toBe('100');
  });

  it('renames the score threshold to the similarity threshold, under Filtering', () => {
    render(DEFAULT_RETRIEVAL_OPTIONS, ON);
    expect(text()).toContain('retrieval.similarityThreshold');
    expect(text()).not.toContain('scoreThreshold');
    const field = container.querySelector('#retrieval-score-threshold')!;
    expect(field.closest('[data-slot="collapsible"]')).toBeNull();
  });

  it('turns relevance off when LLM screening is turned on', () => {
    const onChange = render(filtering(0.3), ON);
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

describe('RetrievalOptions groups', () => {
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
  const FILTER_ROWS = [
    '#retrieval-relevance-min',
    '#retrieval-relevance-candidates',
    '#retrieval-score-threshold',
    '#retrieval-prescreen',
  ];
  const filtering: RetrievalOptionsValue = {
    ...DEFAULT_RETRIEVAL_OPTIONS,
    retrieval: {
      ...DEFAULT_RETRIEVAL_OPTIONS.retrieval,
      reranker: { mode: 'filter', min_relevance: 0.3, candidate_k: null },
    },
  };

  const render = (props: Partial<Parameters<typeof RetrievalOptions>[0]>) => {
    act(() => {
      root.render(
        <RetrievalOptions
          value={filtering}
          onChange={vi.fn()}
          decision={ON}
          {...props}
        />,
      );
    });
  };

  const headings = () =>
    Array.from(container.querySelectorAll('h3')).map((h) => h.textContent);

  it('puts the filtering rows in a flat group of their own, between Relevance and Chunking', () => {
    render({ alwaysOpen: true });
    // No disclosure inside the panel.
    expect(container.querySelector('button[aria-controls]')).toBeNull();
    expect(container.querySelector('[data-slot="collapsible"]')).toBeNull();
    expect(headings()).toEqual([
      'settings.sources.retrievalOptions.retrieval.title · settings.sources.retrievalOptions.retrieval.tag',
      'settings.sources.retrievalOptions.relevance.title · settings.sources.retrievalOptions.relevance.tag',
      'settings.sources.retrievalOptions.filtering.title · settings.sources.retrievalOptions.filtering.tag',
      'settings.sources.retrievalOptions.chunking.title · settings.sources.retrievalOptions.chunking.tag',
    ]);
    const group = Array.from(container.querySelectorAll('h3'))
      .find((h) => h.textContent?.includes('filtering.title'))!
      .closest('div.flex-col')!.parentElement!;
    for (const row of FILTER_ROWS) {
      expect(group.querySelector(row)).not.toBeNull();
    }
    expect(container.textContent).not.toContain('retrievalOptions.createHint');
  });

  it('shows the create forms what matters before ingest, untagged, and where to fine-tune', () => {
    render({ variant: 'create', alwaysOpen: true });
    for (const row of FILTER_ROWS) {
      expect(container.querySelector(row)).toBeNull();
    }
    expect(container.textContent).not.toContain('.tag');
    expect(headings()).toEqual([
      'settings.sources.retrievalOptions.retrieval.title',
      'settings.sources.retrievalOptions.relevance.title',
      'settings.sources.retrievalOptions.chunking.title',
    ]);
    const hint = Array.from(container.querySelectorAll('p')).find(
      (p) => p.textContent === 'settings.sources.retrievalOptions.createHint',
    );
    expect(hint).toBeDefined();
    // Chunking stays: it can only be set before the first ingest.
    expect(container.querySelector('#chunking-strategy')).not.toBeNull();
  });

  it('keeps Filtering on a create form once shown', () => {
    const prescreen = (candidate_k: number) => ({
      ...filtering,
      retrieval: {
        ...filtering.retrieval,
        chunks: 4,
        prescreen: {
          ...filtering.retrieval.prescreen,
          enabled: true,
          candidate_k,
          max_keep: 2,
        },
      },
    });
    const shown = () =>
      container.querySelector('#retrieval-prescreen') !== null;
    // The screening doesn't add up (fewer candidates than chunks): shown.
    render({ variant: 'create', alwaysOpen: true, value: prescreen(2) });
    expect(shown()).toBe(true);
    // Fixing it while typing leaves the group where it is.
    render({ variant: 'create', alwaysOpen: true, value: prescreen(8) });
    expect(shown()).toBe(true);
  });
});
