import i18n from 'i18next';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { beforeAll, describe, expect, it } from 'vitest';

import en from '../locale/en.json';
import {
  CandidateComparison,
  RelevanceScore,
  ScoreBadge,
  relevanceRunText,
  type RetrievalCandidate,
  type RetrievedChunk,
} from './TestRetrievalModal';

const testI18n = i18n.createInstance();

beforeAll(async () => {
  await testI18n.use(initReactI18next).init({
    lng: 'en',
    fallbackLng: 'en',
    resources: { en: { translation: en } },
  });
});

const chunk = (over: Partial<RetrievedChunk>): RetrievedChunk => ({
  rank: 1,
  text: 't',
  title: 't',
  filename: 'f.md',
  source: 'f.md',
  tokens: 10,
  score: null,
  score_kind: null,
  ...over,
});

const render = (c: RetrievedChunk): string =>
  renderToStaticMarkup(
    <I18nextProvider i18n={testI18n}>
      <ScoreBadge chunk={c} />
    </I18nextProvider>,
  );

describe('ScoreBadge', () => {
  // The three score kinds are NOT interchangeable — a cosine similarity is
  // higher-is-better in [0,1] and is what score_threshold compares against, an
  // L2 distance is lower-is-better, and an RRF score only ranks hits against
  // each other. Each must be labelled as itself.
  it('labels a cosine similarity as a similarity', () => {
    const html = render(
      chunk({ score: 0.8241, score_kind: 'cosine_similarity' }),
    );
    expect(html).toContain('similarity');
    expect(html).toContain('0.824');
    expect(html).not.toContain('distance');
  });

  it('labels a FAISS L2 score as a distance, not a similarity', () => {
    const html = render(chunk({ score: 1.6515, score_kind: 'l2_distance' }));
    expect(html).toContain('distance');
    expect(html).toContain('1.651');
    expect(html).not.toContain('similarity');
  });

  it('labels a fused hybrid score as RRF', () => {
    const html = render(chunk({ score: 0.0167, score_kind: 'rrf' }));
    expect(html).toContain('RRF');
    expect(html).toContain('0.017');
  });

  it('says "no score" rather than inventing one', () => {
    const html = render(chunk({ score: null, score_kind: null }));
    expect(html).toContain('no score');
    expect(html).not.toContain('0.000');
  });
});

const inI18n = (node: React.ReactNode): string =>
  renderToStaticMarkup(
    <I18nextProvider i18n={testI18n}>{node}</I18nextProvider>,
  );

describe('relevance in the retrieval test', () => {
  it("shows a scored chunk's relevance as a percentage, and nothing unscored", () => {
    expect(inI18n(<RelevanceScore relevance={0.8123} />)).toContain('81%');
    expect(inI18n(<RelevanceScore relevance={0.8123} />)).toContain(
      'relevance',
    );
    expect(inI18n(<RelevanceScore relevance={null} />)).toBe('');
  });

  it('says what the model did in the run', () => {
    const tr = (key: string, opts?: Record<string, unknown>) =>
      testI18n.t(`settings.sources.testRetrieval.${key}`, opts ?? {});
    expect(
      relevanceRunText({ applied: true, fallback: null, latency_ms: 312 }, tr),
    ).toBe('ordered by relevance in 312 ms');
    expect(
      relevanceRunText({ applied: false, fallback: null, latency_ms: 300 }, tr),
    ).toContain('retriever order kept');
    expect(
      relevanceRunText(
        { applied: false, fallback: 'timeout', latency_ms: 0 },
        tr,
      ),
    ).toContain('(timeout)');
  });

  it('marks each candidate kept, promoted, dropped or not kept', () => {
    const candidate = (
      over: Partial<RetrievalCandidate>,
    ): RetrievalCandidate => ({
      ...chunk({}),
      rank: null,
      rank_before: 1,
      kept: false,
      baseline: false,
      relevance: 0.5,
      ...over,
    });
    const html = inI18n(
      <CandidateComparison
        candidates={[
          candidate({ rank_before: 1, baseline: true, kept: true, rank: 2 }),
          candidate({ rank_before: 2, baseline: true, relevance: 0.04 }),
          candidate({ rank_before: 3, kept: true, rank: 1, relevance: 0.91 }),
          candidate({ rank_before: 4, relevance: null }),
        ]}
      />,
    );
    expect(html).toContain('Kept as #2');
    expect(html).toContain('Dropped');
    expect(html).toContain('Promoted to #1');
    expect(html).toContain('Not kept');
    expect(html).toContain('91%');
    expect(html).toContain('—');
  });
});
