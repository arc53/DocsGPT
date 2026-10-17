import type { Query } from './conversationModels';
import { composerSubmitTarget, resendPlan } from './turnSubmission';

const failed: Query = {
  prompt: 'summarise these',
  error: 'too large',
  errorCode: 'context_length_exceeded',
  attachments: [
    { id: 'a1', fileName: 'one.pdf' },
    { id: 'a2', fileName: 'two.pdf' },
  ],
};

describe('resendPlan', () => {
  it("re-sends the row's files on a retry, with its key", () => {
    expect(resendPlan(failed, true)).toEqual({
      attachmentIds: ['a1', 'a2'],
      keepIdempotencyKey: true,
      dropRowAttachments: false,
    });
  });

  it("re-sends the row's files on an edit, with a fresh key", () => {
    expect(resendPlan(failed, false).keepIdempotencyKey).toBe(false);
  });

  it('asks without the files once they went to Knowledge', () => {
    // Same overflow again otherwise; and it is a different request, so the
    // first one's key must not answer it.
    expect(
      resendPlan({ ...failed, attachmentsInKnowledge: true }, true),
    ).toEqual({
      attachmentIds: [],
      keepIdempotencyKey: false,
      dropRowAttachments: true,
    });
  });

  it('copes with a row that is gone', () => {
    expect(resendPlan(undefined, true).attachmentIds).toEqual([]);
  });
});

describe('composerSubmitTarget', () => {
  it('starts a new turn after an answer', () => {
    expect(
      composerSubmitTarget({
        question: 'next',
        queries: [{ prompt: 'q', response: 'a' }],
        lastQueryReturnedErr: false,
        composerFileCount: 0,
      }),
    ).toEqual({ kind: 'new' });
  });

  it('retries the failed turn when the composer has no files', () => {
    expect(
      composerSubmitTarget({
        question: 'summarise these',
        queries: [failed],
        lastQueryReturnedErr: true,
        composerFileCount: 0,
      }),
    ).toEqual({ kind: 'retry', index: 0, samePrompt: true });
    expect(
      composerSubmitTarget({
        question: 'only the first one',
        queries: [failed],
        lastQueryReturnedErr: true,
        composerFileCount: 0,
      }),
    ).toEqual({ kind: 'retry', index: 0, samePrompt: false });
  });

  it('starts a new turn with new composer files after an error', () => {
    // Re-sending the failed row would send its files again and drop these.
    expect(
      composerSubmitTarget({
        question: 'try this one instead',
        queries: [failed],
        lastQueryReturnedErr: true,
        composerFileCount: 1,
      }),
    ).toEqual({ kind: 'new' });
  });
});
