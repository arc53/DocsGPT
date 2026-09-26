import { describe, expect, it } from 'vitest';

import {
  parseAttachmentPlan,
  planEntryFor,
  summarizePlan,
} from './attachmentPlan';
import type { AttachmentPlanEntry } from './conversationModels';

const entry = (
  ref: string,
  id: string,
  status: AttachmentPlanEntry['status'],
  extra: Partial<AttachmentPlanEntry> = {},
): AttachmentPlanEntry => ({
  ref,
  id,
  filename: `${ref}.pdf`,
  status,
  ...extra,
});

describe('planEntryFor', () => {
  const plan = [
    entry('F1', 'pg-1', 'inline', { upload_id: 'up-1' }),
    entry('F2', 'pg-2', 'tool', { aliases: ['pg-9'] }),
  ];

  it('matches the stored id, the upload handle or an alias', () => {
    expect(planEntryFor(plan, { id: 'pg-1', fileName: 'a' })?.ref).toBe('F1');
    expect(planEntryFor(plan, { id: 'up-1', fileName: 'a' })?.ref).toBe('F1');
    expect(planEntryFor(plan, { id: 'pg-9', fileName: 'b' })?.ref).toBe('F2');
  });

  it('returns undefined without a plan or a match', () => {
    expect(planEntryFor(undefined, { id: 'pg-1', fileName: 'a' })).toBe(
      undefined,
    );
    expect(planEntryFor(plan, { id: 'nope', fileName: 'x' })).toBe(undefined);
  });
});

describe('summarizePlan', () => {
  it('counts only the files of this message', () => {
    const plan = [
      entry('F1', 'old', 'tool'),
      entry('F2', 'a', 'inline'),
      entry('F3', 'b', 'partial'),
      entry('F4', 'c', 'tool'),
      entry('F5', 'd', 'omitted'),
    ];
    const files = ['a', 'b', 'c', 'd'].map((id) => ({ id, fileName: id }));
    expect(summarizePlan(plan, files)).toEqual({
      total: 4,
      inFull: 1,
      searchable: 2,
      notIncluded: 1,
    });
  });

  it('says nothing when every file was read in full', () => {
    const plan = [entry('F1', 'a', 'inline')];
    expect(summarizePlan(plan, [{ id: 'a', fileName: 'a' }])).toBeNull();
  });

  it('counts a duplicate upload once', () => {
    const plan = [entry('F1', 'a', 'tool', { aliases: ['b'] })];
    const files = [
      { id: 'a', fileName: 'x' },
      { id: 'b', fileName: 'x' },
    ];
    expect(summarizePlan(plan, files)?.total).toBe(1);
  });
});

describe('parseAttachmentPlan', () => {
  it('drops malformed entries', () => {
    expect(
      parseAttachmentPlan([
        entry('F1', 'a', 'inline'),
        { ref: 'F2', id: 'b', status: 'bogus' },
        null,
        'x',
      ]),
    ).toEqual([entry('F1', 'a', 'inline')]);
  });

  it('returns undefined for a missing or empty plan', () => {
    expect(parseAttachmentPlan(undefined)).toBeUndefined();
    expect(parseAttachmentPlan([])).toBeUndefined();
  });
});
