import { lastShownIndex } from './shownQueries';

describe('lastShownIndex', () => {
  const summary = {
    prompt: '[Context Compression Summary]',
    response: 's',
    compressionSummary: true,
  };

  it('is the last turn when nothing is hidden', () => {
    expect(lastShownIndex([{ prompt: 'a' }, { prompt: 'b' }])).toBe(1);
  });

  it('skips stored compression summaries at the end', () => {
    expect(lastShownIndex([{ prompt: 'a' }, summary, summary])).toBe(0);
  });

  it('is -1 for an empty list', () => {
    expect(lastShownIndex([])).toBe(-1);
  });
});
