import { describe, expect, it } from 'vitest';

import { SourceConfig } from '../../models/misc';
import {
  configToOptions,
  optionsToConfig,
  isPrescreenConfigValid,
  chunkingChanged,
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
  it('always emits kind=classic and a full shape', () => {
    const cfg = optionsToConfig(DEFAULT_RETRIEVAL_OPTIONS);
    expect(cfg.kind).toBe('classic');
    expect(cfg.chunking).toBeDefined();
    expect(cfg.retrieval).toBeDefined();
  });

  it('nests prescreen to null when disabled', () => {
    expect(optionsToConfig(DEFAULT_RETRIEVAL_OPTIONS).retrieval.prescreen).toBe(
      null,
    );
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
    const ps = optionsToConfig(v).retrieval.prescreen;
    expect(ps).not.toBe(null);
    expect(ps?.model).toBe(null);
    expect(ps?.candidate_k).toBe(30);

    v.retrieval.prescreen.model = '  gpt-x  ';
    expect(optionsToConfig(v).retrieval.prescreen?.model).toBe('gpt-x');
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
