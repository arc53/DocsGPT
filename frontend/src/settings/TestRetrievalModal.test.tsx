import i18n from 'i18next';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { beforeAll, describe, expect, it } from 'vitest';

import en from '../locale/en.json';
import { ScoreBadge, type RetrievedChunk } from './TestRetrievalModal';

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
