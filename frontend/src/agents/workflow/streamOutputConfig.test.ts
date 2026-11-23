import { describe, expect, it } from 'vitest';

import {
  DEFAULT_STREAM_OUTPUT,
  normalizeStreamOutput,
  STREAM_OUTPUT_OPTIONS,
} from './streamOutputConfig';

describe('normalizeStreamOutput', () => {
  it('passes the three settings through', () => {
    expect(normalizeStreamOutput('full')).toBe('full');
    expect(normalizeStreamOutput('summary')).toBe('summary');
    expect(normalizeStreamOutput('none')).toBe('none');
  });

  it('reads anything else as the default', () => {
    expect(normalizeStreamOutput(undefined)).toBe(DEFAULT_STREAM_OUTPUT);
    expect(normalizeStreamOutput('everything')).toBe(DEFAULT_STREAM_OUTPUT);
    expect(DEFAULT_STREAM_OUTPUT).toBe('summary');
  });

  it('offers the default first', () => {
    expect(STREAM_OUTPUT_OPTIONS.map((o) => o.value)).toEqual([
      'summary',
      'full',
      'none',
    ]);
  });
});
