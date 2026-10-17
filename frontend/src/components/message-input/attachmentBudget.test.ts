import { describe, expect, it } from 'vitest';

import type { Attachment } from '../../upload/uploadSlice';
import {
  DEFAULT_ATTACHMENT_BUDGET_SHARE,
  attachmentTokenTotal,
  exceedsAttachmentBudget,
} from './attachmentBudget';

const row = (overrides: Partial<Attachment>): Attachment => ({
  id: overrides.id ?? 'id',
  fileName: 'f.pdf',
  progress: 100,
  status: 'completed',
  taskId: 't',
  ...overrides,
});

describe('attachmentTokenTotal', () => {
  it('sums completed rows only', () => {
    expect(
      attachmentTokenTotal([
        row({ id: 'a', token_count: 1000 }),
        row({ id: 'b', token_count: 500 }),
        row({ id: 'c', token_count: 9000, status: 'processing' }),
        row({ id: 'd', token_count: 9000, status: 'failed' }),
        row({ id: 'e' }),
      ]),
    ).toBe(1500);
  });
});

describe('exceedsAttachmentBudget', () => {
  it('mirrors the backend default share', () => {
    expect(DEFAULT_ATTACHMENT_BUDGET_SHARE).toBe(0.5);
  });

  it('is false while the files fit the share of the window', () => {
    const files = [row({ token_count: 50_000 })];
    expect(exceedsAttachmentBudget(files, 100_000, 0.5)).toBe(false);
  });

  it('is true once the files pass the share of the window', () => {
    const files = [
      row({ id: 'a', token_count: 30_000 }),
      row({ id: 'b', token_count: 30_000 }),
    ];
    expect(exceedsAttachmentBudget(files, 100_000, 0.5)).toBe(true);
  });

  it('is false without a known window', () => {
    const files = [row({ token_count: 10_000_000 })];
    expect(exceedsAttachmentBudget(files, undefined, 0.5)).toBe(false);
    expect(exceedsAttachmentBudget(files, 0, 0.5)).toBe(false);
  });

  it('falls back to the default share when the server sends none', () => {
    const files = [row({ token_count: 60_000 })];
    expect(exceedsAttachmentBudget(files, 100_000, undefined)).toBe(true);
    expect(exceedsAttachmentBudget(files, 100_000, Number.NaN)).toBe(true);
  });
});
