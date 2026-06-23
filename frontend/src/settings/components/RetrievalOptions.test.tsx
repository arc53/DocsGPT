import { describe, expect, it } from 'vitest';

import { SourceConfig } from '../../models/misc';
import {
  availableRetrievers,
  configToOptions,
  optionsToConfig,
  isPrescreenConfigValid,
  chunkingChanged,
  scoreThresholdHidden,
  DEFAULT_RETRIEVAL_OPTIONS,
  RetrievalOptionsValue,
} from './RetrievalOptions';

const clone = (v: RetrievalOptionsValue): RetrievalOptionsValue =>
  JSON.parse(JSON.stringify(v));

describe('configToOptions (lenient read)', () => {
  it('returns all defaults for an absent config', () => {
    expect(configToOptions(undefined)).toEqual(DEFAULT_RETRIEVAL_OPTIONS);
  });

  it('returns all defaults for an empty legacy config', () => {
    expect(configToOptions({} as SourceConfig)).toEqual(
      DEFAULT_RETRIEVAL_OPTIONS,
    );
  });

  it('fills missing fields while honoring provided ones', () => {
    const opts = configToOptions({
      chunking: { strategy: 'recursive' },
      retrieval: { chunks: 5 },
    } as SourceConfig);
    expect(opts.chunking.strategy).toBe('recursive');
    expect(opts.chunking.max_tokens).toBe(1250); // default preserved
    expect(opts.retrieval.chunks).toBe(5);
    expect(opts.retrieval.exposure).toBe('prefetch'); // default preserved
    expect(opts.retrieval.prescreen.enabled).toBe(false);
  });

  it('marks prescreen enabled when the stored object is present', () => {
    const opts = configToOptions({
      retrieval: {
        prescreen: { candidate_k: 50, model: 'm', batch_size: 5, max_keep: 9 },
      },
    } as SourceConfig);
    expect(opts.retrieval.prescreen.enabled).toBe(true);
    expect(opts.retrieval.prescreen.candidate_k).toBe(50);
    expect(opts.retrieval.prescreen.max_keep).toBe(9);
  });
});

describe('optionsToConfig (write path)', () => {
  it('emits the carried kind and a full shape', () => {
    const cfg = optionsToConfig(DEFAULT_RETRIEVAL_OPTIONS);
    expect(cfg.kind).toBe('classic');
    expect(cfg.chunking).toBeDefined();
    expect(cfg.retrieval).toBeDefined();
    expect(cfg.graph).toBeDefined();
  });

  it('preserves a non-classic kind (never downgrades a wiki source)', () => {
    const v = clone(DEFAULT_RETRIEVAL_OPTIONS);
    v.kind = 'wiki';
    expect(optionsToConfig(v).kind).toBe('wiki');
  });

  it('forces kind=graphrag when the graphrag retriever is chosen', () => {
    const v = clone(DEFAULT_RETRIEVAL_OPTIONS);
    v.kind = 'classic';
    v.retrieval.retriever = 'graphrag';
    expect(optionsToConfig(v).kind).toBe('graphrag');
  });

  it('round-trips the graph config including model and max_chunks', () => {
    const v = clone(DEFAULT_RETRIEVAL_OPTIONS);
    v.kind = 'graphrag';
    v.retrieval.retriever = 'graphrag';
    v.graph = { extraction_model: 'gpt-x', max_chunks: 50, gleanings: 1 };
    const cfg = optionsToConfig(v);
    expect(cfg.graph).toEqual({
      extraction_model: 'gpt-x',
      max_chunks: 50,
      gleanings: 1,
    });
    expect(configToOptions(cfg)).toEqual(v);
  });

  it('normalizes a whitespace extraction model to null', () => {
    const v = clone(DEFAULT_RETRIEVAL_OPTIONS);
    v.graph.extraction_model = '  ';
    expect(optionsToConfig(v).graph?.extraction_model).toBe(null);
  });

  it('nests prescreen to null when disabled', () => {
    expect(
      optionsToConfig(DEFAULT_RETRIEVAL_OPTIONS).retrieval?.prescreen,
    ).toBe(null);
  });

  it('serializes prescreen object when enabled and trims/normalizes model', () => {
    const v = clone(DEFAULT_RETRIEVAL_OPTIONS);
    v.retrieval.prescreen = {
      enabled: true,
      candidate_k: 30,
      model: '  ', // whitespace -> null
      batch_size: 7,
      max_keep: 6,
    };
    const ps = optionsToConfig(v).retrieval?.prescreen;
    expect(ps).not.toBe(null);
    expect(ps?.model).toBe(null);
    expect(ps?.candidate_k).toBe(30);

    v.retrieval.prescreen.model = '  gpt-x  ';
    expect(optionsToConfig(v).retrieval?.prescreen?.model).toBe('gpt-x');
  });
});

describe('round-trip configToOptions(optionsToConfig(x)) == x', () => {
  it('round-trips the default (prescreen disabled)', () => {
    expect(configToOptions(optionsToConfig(DEFAULT_RETRIEVAL_OPTIONS))).toEqual(
      DEFAULT_RETRIEVAL_OPTIONS,
    );
  });

  it('round-trips a fully-customized canonical value', () => {
    const v: RetrievalOptionsValue = {
      kind: 'classic',
      chunking: {
        strategy: 'parent_child',
        max_tokens: 800,
        min_tokens: 50,
        duplicate_headers: true,
      },
      retrieval: {
        retriever: 'classic',
        exposure: 'agentic_tool',
        chunks: 3,
        score_threshold: 0.25,
        rephrase_query: false,
        prescreen: {
          enabled: true,
          candidate_k: 50,
          model: 'gpt-x',
          batch_size: 5,
          max_keep: 10,
        },
      },
      graph: {
        extraction_model: null,
        max_chunks: null,
        gleanings: 0,
      },
    };
    expect(configToOptions(optionsToConfig(v))).toEqual(v);
  });
});

describe('isPrescreenConfigValid', () => {
  const withPrescreen = (
    chunks: number,
    candidate_k: number,
    max_keep: number,
  ): RetrievalOptionsValue => {
    const v = clone(DEFAULT_RETRIEVAL_OPTIONS);
    v.retrieval.chunks = chunks;
    v.retrieval.prescreen = {
      enabled: true,
      candidate_k,
      model: null,
      batch_size: 10,
      max_keep,
    };
    return v;
  };

  it('is always valid when prescreen is disabled', () => {
    expect(isPrescreenConfigValid(DEFAULT_RETRIEVAL_OPTIONS)).toBe(true);
  });

  it('rejects candidate_k < chunks', () => {
    expect(isPrescreenConfigValid(withPrescreen(5, 3, 3))).toBe(false);
  });

  it('rejects max_keep > candidate_k', () => {
    expect(isPrescreenConfigValid(withPrescreen(2, 10, 15))).toBe(false);
  });

  it('accepts a consistent config', () => {
    expect(isPrescreenConfigValid(withPrescreen(2, 40, 8))).toBe(true);
  });
});

describe('chunkingChanged', () => {
  it('detects a chunking-group change', () => {
    const after = clone(DEFAULT_RETRIEVAL_OPTIONS);
    after.chunking.strategy = 'markdown';
    expect(chunkingChanged(DEFAULT_RETRIEVAL_OPTIONS, after)).toBe(true);
  });

  it('ignores a retrieval-only change', () => {
    const after = clone(DEFAULT_RETRIEVAL_OPTIONS);
    after.retrieval.chunks = 9;
    after.retrieval.rephrase_query = false;
    expect(chunkingChanged(DEFAULT_RETRIEVAL_OPTIONS, after)).toBe(false);
  });
});

describe('availableRetrievers', () => {
  it('always offers classic', () => {
    expect(availableRetrievers('classic', false, false)).toEqual(['classic']);
  });

  it('hides hybrid when unavailable and not already selected', () => {
    expect(availableRetrievers('classic', false, false)).not.toContain(
      'hybrid',
    );
  });

  it('shows hybrid when available', () => {
    expect(availableRetrievers('classic', true, false)).toContain('hybrid');
  });

  it('shows hybrid when already selected even if unavailable', () => {
    expect(availableRetrievers('hybrid', false, false)).toContain('hybrid');
  });

  it('hides graphrag when unavailable and not already selected', () => {
    expect(availableRetrievers('classic', false, false)).not.toContain(
      'graphrag',
    );
  });

  it('shows graphrag when available', () => {
    expect(availableRetrievers('classic', false, true)).toContain('graphrag');
  });

  it('shows graphrag when already selected even if unavailable', () => {
    expect(availableRetrievers('graphrag', false, false)).toContain('graphrag');
  });
});

describe('scoreThresholdHidden', () => {
  it('shows the threshold for the classic retriever', () => {
    expect(scoreThresholdHidden('classic')).toBe(false);
  });

  it('hides the threshold for hybrid and graphrag', () => {
    expect(scoreThresholdHidden('hybrid')).toBe(true);
    expect(scoreThresholdHidden('graphrag')).toBe(true);
  });
});
